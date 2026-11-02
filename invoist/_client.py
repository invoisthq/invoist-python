"""The synchronous client, :class:`Invoist`."""

from __future__ import annotations

import builtins
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from types import TracebackType
from typing import Literal

import httpx

from ._base import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TIMEOUT,
    DEFAULT_WAIT_TIMEOUT,
    BaseClient,
    FileInput,
    Request,
    backoff,
    download,
    error_from_response,
    extraction_timeout,
    format_month,
    multipart,
    network_error,
    parse,
    parse_list,
    path,
    query,
    retry_delay,
    to_upload,
)
from .models import (
    BatchResult,
    Bill,
    BillDetail,
    BillRecord,
    BillsStats,
    BillsSummary,
    Category,
    DocumentDetail,
    DocumentListItem,
    DocumentStatus,
    ExtractAndWaitResult,
    Extraction,
    ExtractResult,
    FileDownload,
    HeldEmail,
    ReviewQueueItem,
    ReviewQueueListItem,
    ReviewStatus,
    StatsOverview,
    Usage,
    WebhookEndpointList,
    WebhookEndpointWithSecret,
)

__all__ = ["Bills", "HeldEmails", "Invoist"]


class Invoist(BaseClient):
    """The Invoist API client.

    Create one per application and reuse it: it keeps connections open.
    Close it with :meth:`close`, or use it as a context manager::

        from invoist import Invoist

        with Invoist(os.environ["INVOIST_API_KEY"]) as invoist:
            result = invoist.extract_and_wait(Path("invoice.pdf"))
            print(result.extraction.vendor_name, result.extraction.total_cents)

    A business's key uses the methods on the client itself; a household's
    key uses :attr:`bills` and :attr:`held_emails`.

    Args:
        api_key: Your API key (``inv_sk_...``) or an OAuth access token
            (``inv_at_...``). Required.
        base_url: The API's address. Trailing slashes are ignored.
        timeout: Seconds each attempt may take, uploads included.
        max_retries: How many times to retry a request that failed with no
            response, a 429 or a 5xx. ``0`` turns retrying off.
        http_client: An ``httpx.Client`` to send requests with, for proxies,
            custom TLS, or tests. You keep ownership: :meth:`close` leaves it
            open.
    """

    bills: Bills
    """A household's bills (Invoist Personal)."""
    held_emails: HeldEmails
    """Emails forwarded to a household that wait for approval."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(api_key, base_url=base_url, timeout=timeout, max_retries=max_retries)
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else httpx.Client()
        self._sleep: Callable[[float], None] = time.sleep
        self._clock: Callable[[], float] = time.monotonic
        self.bills = Bills(self)
        self.held_emails = HeldEmails(self)

    # -- lifecycle -------------------------------------------------------------

    def close(self) -> None:
        """Close the connections this client opened. An injected ``http_client`` stays open."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Invoist:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- transport -------------------------------------------------------------

    def _send(self, request: Request) -> httpx.Response:
        """Send a request, retrying what is safe to retry, and return a successful response."""
        url = self._url(request.path)
        headers = self._headers(request)
        attempt = 0
        while True:
            try:
                response = self._http.request(
                    request.method,
                    url,
                    params=request.params,
                    json=request.json,
                    files=request.files,
                    headers=headers,
                    timeout=self.timeout,
                )
            except httpx.RequestError as exc:
                error = network_error(exc)
                if attempt >= self.max_retries:
                    raise error from exc
                delay = backoff(attempt)
            else:
                if response.is_success:
                    return response
                error = error_from_response(response)
                if not error.is_retryable or attempt >= self.max_retries:
                    raise error
                wait = retry_delay(attempt, response.headers.get("Retry-After"))
                if wait is None:  # the server asked for more than a minute
                    raise error
                delay = wait
            self._sleep(delay)
            attempt += 1

    # -- extraction ------------------------------------------------------------

    def extract(self, file: FileInput, *, idempotency_key: str | None = None) -> ExtractResult:
        """Submit a PDF, PNG or JPEG (up to 20 MB) to be read.

        Returns as soon as the file is accepted, with ``extraction.status``
        ``pending``: reading happens in the background. Use
        :meth:`wait_for_extraction` or the ``extraction.completed`` webhook
        for the result, or :meth:`extract_and_wait` to do both.

        Sending the same bytes again is safe: you get the existing document
        back with ``duplicate=True`` and are not billed twice.

        Args:
            file: The file; see :data:`invoist.FileInput` for the accepted forms.
            idempotency_key: A key you choose per logical upload. Repeating
                it replays the first response, even if the bytes differ
                slightly (a re-encoded export). Reusing it for a different
                file raises :class:`InvoistError` with status 422.
        """
        upload = to_upload(file)
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        response = self._send(
            Request("POST", "/v1/extract", files=multipart("file", [upload]), headers=headers)
        )
        return parse(ExtractResult, response)

    def extract_batch(self, files: Iterable[FileInput]) -> BatchResult:
        """Submit up to 10 files in one call.

        Each goes through the same pipeline as :meth:`extract`. One bad file
        does not fail the rest: ``results`` holds each file's own outcome, in
        the order given, with ``error`` set on the ones that were rejected.
        """
        uploads = [to_upload(f) for f in files]
        if not uploads:
            raise ValueError("extract_batch needs at least one file.")
        response = self._send(
            Request("POST", "/v1/extract/batch", files=multipart("files", uploads))
        )
        return parse(BatchResult, response)

    def wait_for_extraction(
        self,
        document_id: str,
        *,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> Extraction:
        """Poll a document until its extraction finishes, and return the extraction.

        Returns when the status is ``done`` *or* ``failed``: a document that
        could not be read is an answer (see ``error_message``), not an
        exception.

        Args:
            document_id: The document to wait for.
            timeout: Seconds to wait in total.
            poll_interval: Seconds between polls.

        Raises:
            InvoistError: With code ``extraction_timeout`` when ``timeout``
                passes first, or any error from fetching the document.
        """
        deadline = self._clock() + timeout
        while True:
            extraction = self.get_document(document_id).extraction
            if extraction is not None and extraction.status != "pending":
                return extraction
            if self._clock() + poll_interval > deadline:
                raise extraction_timeout(document_id, timeout)
            self._sleep(poll_interval)

    def extract_and_wait(
        self,
        file: FileInput,
        *,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        idempotency_key: str | None = None,
    ) -> ExtractAndWaitResult:
        """:meth:`extract` a file, then :meth:`wait_for_extraction` for its result."""
        result = self.extract(file, idempotency_key=idempotency_key)
        extraction = result.extraction
        if extraction is None or extraction.status == "pending":
            extraction = self.wait_for_extraction(
                result.document.id, timeout=timeout, poll_interval=poll_interval
            )
        return ExtractAndWaitResult(document=result.document, extraction=extraction)

    # -- documents -------------------------------------------------------------

    def list_documents(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        status: DocumentStatus | None = None,
        flagged: bool | None = None,
        q: str | None = None,
        category: str | None = None,
    ) -> list[DocumentListItem]:
        """List documents, newest first.

        Args:
            limit: At most this many (default 50, at most 200).
            offset: Skip this many, for paging.
            status: Only documents in this status.
            flagged: ``True`` for only documents with open review items. ``False``
                is the same as leaving it out.
            q: Match on filename, vendor, invoice number or reference.
            category: A category id, or ``"none"`` for uncategorised ones.
        """
        params = query(
            limit=limit,
            offset=offset,
            status=status,
            flagged=True if flagged else None,  # the API reads false as no filter
            q=q,
            category=category,
        )
        response = self._send(Request("GET", "/v1/documents", params=params))
        return parse_list(DocumentListItem, response, "documents")

    def get_document(self, document_id: str) -> DocumentDetail:
        """Fetch a document with its extraction and review items."""
        response = self._send(Request("GET", path("/v1/documents/{}", document_id)))
        return parse(DocumentDetail, response)

    def get_document_file(self, document_id: str) -> FileDownload:
        """Download a document's original file, byte for byte."""
        response = self._send(Request("GET", path("/v1/documents/{}/file", document_id)))
        return download(response)

    # -- review queue ----------------------------------------------------------

    def list_review_queue(self, *, status: ReviewStatus | None = None) -> list[ReviewQueueListItem]:
        """List the items flagged for a person to check, optionally only those in ``status``."""
        response = self._send(Request("GET", "/v1/review-queue", params=query(status=status)))
        return parse_list(ReviewQueueListItem, response, "review_queue")

    def resolve_review_item(
        self, item_id: str, status: Literal["resolved", "dismissed"] = "resolved"
    ) -> ReviewQueueItem:
        """Close a review item as ``resolved`` (checked and fine) or ``dismissed``."""
        response = self._send(
            Request("POST", path("/v1/review-queue/{}/resolve", item_id), json={"status": status})
        )
        return parse(ReviewQueueItem, response, "review_queue_item")

    # -- workspace -------------------------------------------------------------

    def list_categories(self) -> list[Category]:
        """List the workspace's spend categories."""
        response = self._send(Request("GET", "/v1/categories"))
        return parse_list(Category, response, "categories")

    def get_usage(self) -> Usage:
        """Usage for the current billing period, with a per-day breakdown."""
        return parse(Usage, self._send(Request("GET", "/v1/usage")))

    def get_stats(self) -> StatsOverview:
        """Document counts, the pending review count, and the plan's allowance."""
        return parse(StatsOverview, self._send(Request("GET", "/v1/stats/overview")))

    # -- webhook endpoints -----------------------------------------------------

    def list_webhook_endpoints(self) -> WebhookEndpointList:
        """List registered webhook endpoints, and every event type they can subscribe to."""
        return parse(WebhookEndpointList, self._send(Request("GET", "/v1/webhook-endpoints")))

    def create_webhook_endpoint(
        self,
        url: str,
        *,
        events: Sequence[str] | None = None,
        description: str | None = None,
    ) -> WebhookEndpointWithSecret:
        """Register a URL to receive signed events.

        The result's ``secret`` is shown only this once: store it, and pass
        it to :func:`invoist.webhooks.verify_webhook`.

        Args:
            url: The HTTP or HTTPS address to deliver to.
            events: Event types (see :class:`invoist.webhooks.EventType`), or
                ``["*"]``. Everything when omitted.
            description: A note for yourself.
        """
        body: dict[str, object] = {"url": url}
        if events is not None:
            body["events"] = list(events)
        if description is not None:
            body["description"] = description
        response = self._send(Request("POST", "/v1/webhook-endpoints", json=body))
        return parse(WebhookEndpointWithSecret, response, "endpoint")

    def delete_webhook_endpoint(self, endpoint_id: str) -> None:
        """Remove a webhook endpoint. Deliveries to it stop at once."""
        self._send(Request("DELETE", path("/v1/webhook-endpoints/{}", endpoint_id)))


class Bills:
    """A household's bills (Invoist Personal), as ``invoist.bills``.

    These need a household's key or assistant, which holds ``bills:read``,
    and ``bills:write`` to mark bills paid.
    """

    def __init__(self, client: Invoist) -> None:
        self._client = client

    def list(
        self,
        *,
        paid: bool | None = None,
        month: str | date | None = None,
        sender: str | None = None,
        q: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> builtins.list[Bill]:
        """List the household's bills; unpaid ones come soonest-due first.

        Args:
            paid: ``True`` for paid bills, ``False`` for bills still to pay;
                both when omitted.
            month: Only this month's bills, as ``"YYYY-MM"`` or a date in it.
            sender: Only this sender's bills.
            q: Match on filename, sender, bill number or reference, across
                every month.
            limit: At most this many (default 50, at most 200).
            offset: Skip this many, for paging.
        """
        params = query(
            paid=paid, month=format_month(month), sender=sender, q=q, limit=limit, offset=offset
        )
        response = self._client._send(Request("GET", "/v1/bills", params=params))
        return parse_list(Bill, response, "bills")

    def get(self, bill_id: str) -> BillDetail:
        """Everything about one bill: what was read, its warnings, its letters, who paid."""
        response = self._client._send(Request("GET", path("/v1/bills/{}", bill_id)))
        return parse(BillDetail, response)

    def get_file(self, bill_id: str) -> FileDownload:
        """Download a bill's original file, byte for byte."""
        response = self._client._send(Request("GET", path("/v1/bills/{}/file", bill_id)))
        return download(response)

    def summary(self, *, today: str | date | None = None, days: int | None = None) -> BillsSummary:
        """What there is to pay: unpaid and overdue counts, and what falls due soon.

        Args:
            today: The household's own date, within two days of the server's.
            days: How far ahead "due soon" reaches (default 30).
        """
        params = query(today=today, days=days)
        response = self._client._send(Request("GET", "/v1/bills/summary", params=params))
        return parse(BillsSummary, response)

    def stats(self, *, month: str | date | None = None, sender: str | None = None) -> BillsStats:
        """A month at a glance: totals, the twelve months to it, and the biggest senders.

        Args:
            month: The month, as ``"YYYY-MM"`` or a date in it; the current one when omitted.
            sender: Narrow the totals and the trend to one sender.
        """
        params = query(month=format_month(month), sender=sender)
        response = self._client._send(Request("GET", "/v1/bills/stats", params=params))
        return parse(BillsStats, response)

    def mark_paid(self, bill_id: str) -> BillRecord:
        """Mark a bill, and its letters, as paid. Needs ``bills:write``."""
        response = self._client._send(Request("POST", path("/v1/bills/{}/paid", bill_id)))
        return parse(BillRecord, response, "bill")

    def mark_unpaid(self, bill_id: str) -> BillRecord:
        """Mark a bill as not paid after all. Needs ``bills:write``."""
        response = self._client._send(Request("DELETE", path("/v1/bills/{}/paid", bill_id)))
        return parse(BillRecord, response, "bill")


class HeldEmails:
    """Emails forwarded to a household that wait for approval, as ``invoist.held_emails``."""

    def __init__(self, client: Invoist) -> None:
        self._client = client

    def list(self) -> builtins.list[HeldEmail]:
        """List the waiting emails, oldest first. Approving a sender is done in the app."""
        response = self._client._send(Request("GET", "/v1/held-emails"))
        return parse_list(HeldEmail, response, "held_emails")
