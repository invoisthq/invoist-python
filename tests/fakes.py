"""A fake API for the client tests: queued responses, recorded requests, fake time."""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from invoist import AsyncInvoist, Invoist

BASE_URL = "https://api.test"
API_KEY = "inv_sk_test_123"
TESTDATA = Path(__file__).resolve().parent.parent / "testdata" / "conformance"
SPEC = Path(
    os.environ.get("INVOIST_OPENAPI")
    or Path(__file__).resolve().parent.parent / "testdata" / "openapi.yaml"
)
"""The API's OpenAPI document."""


def conformance(name: str) -> dict[str, Any]:
    """Load one of the shared conformance files."""
    data: dict[str, Any] = json.loads((TESTDATA / f"{name}.json").read_text(encoding="utf-8"))
    return data


Reply = httpx.Response | Exception | Callable[[httpx.Request], Awaitable[httpx.Response]]


def reply(
    status: int = 200, body: Any = None, headers: dict[str, str] | None = None
) -> httpx.Response:
    """A JSON response (or an empty one when ``body`` is ``None``)."""
    if body is None:
        return httpx.Response(status, headers=headers)
    return httpx.Response(status, json=body, headers=headers)


class FakeAPI:
    """Answers requests from a queue and records each one."""

    def __init__(self, *replies: Reply) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []
        self.now = 1000.0

    def queue(self, *replies: Reply) -> None:
        """Add more replies."""
        self.replies.extend(replies)

    def _next(self, request: httpx.Request) -> Reply:
        request.read()
        self.requests.append(request)
        if not self.replies:
            raise AssertionError(f"unexpected request {request.method} {request.url}")
        return self.replies.pop(0)

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Sync transport handler."""
        item = self._next(request)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, httpx.Response), "sync clients can't await a reply"
        return item

    async def ahandle(self, request: httpx.Request) -> httpx.Response:
        """Async transport handler."""
        item = self._next(request)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, httpx.Response):
            return item
        return await item(request)

    def sleep(self, seconds: float) -> None:
        """Record a wait and move the fake clock on, instead of waiting."""
        self.sleeps.append(seconds)
        self.now += seconds

    async def asleep(self, seconds: float) -> None:
        """Async :meth:`sleep`."""
        self.sleep(seconds)

    def clock(self) -> float:
        """The fake monotonic clock."""
        return self.now

    @property
    def last(self) -> httpx.Request:
        """The most recent request."""
        return self.requests[-1]


def sync_client(api: FakeAPI, **options: Any) -> Invoist:
    """An :class:`Invoist` that talks to ``api``."""
    client = Invoist(
        API_KEY,
        base_url=BASE_URL,
        http_client=httpx.Client(transport=httpx.MockTransport(api.handle)),
        **options,
    )
    client._sleep = api.sleep
    client._clock = api.clock
    return client


def async_client(api: FakeAPI, **options: Any) -> AsyncInvoist:
    """An :class:`AsyncInvoist` that talks to ``api``."""
    client = AsyncInvoist(
        API_KEY,
        base_url=BASE_URL,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(api.ahandle)),
        **options,
    )
    client._sleep = api.asleep
    client._clock = api.clock
    return client


# -- sample API objects ------------------------------------------------------

ID = "01a19812-0000-7000-8000-0000000000aa"
TS = "2026-11-01T10:40:00Z"

DOCUMENT: dict[str, Any] = {
    "id": ID,
    "source": "api",
    "original_filename": "invoice.pdf",
    "content_type": "application/pdf",
    "byte_size": 1234,
    "status": "processing",
    "created_at": TS,
    "updated_at": TS,
}


def extraction(status: str = "done", **fields: Any) -> dict[str, Any]:
    """An extraction in ``status``."""
    return {
        "id": "01a19812-0000-7000-8000-0000000000bb",
        "document_id": ID,
        "engine": "invoist-extraction-v1",
        "status": status,
        "vendor_name": "Northwind Oy",
        "total_cents": 4800,
        "currency": "EUR",
        "invoice_date": "2026-10-15",
        "created_at": TS,
        "updated_at": TS,
        **fields,
    }


def document_detail(status: str | None = "done") -> dict[str, Any]:
    """``GET /v1/documents/{id}``, with an extraction in ``status`` (or none)."""
    body: dict[str, Any] = {"document": DOCUMENT, "review_queue": []}
    if status is not None:
        body["extraction"] = extraction(status)
    return body


DOCUMENT_LIST_ITEM: dict[str, Any] = {
    **DOCUMENT,
    "status": "done",
    "vendor_name": "Northwind Oy",
    "total_cents": 4800,
    "pending_review": 0,
    "flagged": False,
}

REVIEW_ITEM: dict[str, Any] = {
    "id": "01a19812-0000-7000-8000-0000000000cc",
    "document_id": ID,
    "extraction_id": "01a19812-0000-7000-8000-0000000000bb",
    "reason": "low_confidence",
    "status": "pending",
    "created_at": TS,
}

REVIEW_LIST_ITEM: dict[str, Any] = {
    **REVIEW_ITEM,
    "original_filename": "invoice.pdf",
    "content_type": "application/pdf",
    "document_status": "done",
}

CATEGORY: dict[str, Any] = {"id": ID, "name": "Software", "is_default": True, "created_at": TS}

USAGE: dict[str, Any] = {
    "period_start": TS,
    "total_calls": 3,
    "total_documents": 2,
    "total_cost_cents": 20,
    "by_day": [{"day": "2026-11-01", "calls": 3, "documents": 2}],
}

STATS: dict[str, Any] = {
    "documents_this_month": 2,
    "documents_total": 10,
    "pending_review_count": 1,
    "period_start": TS,
    "plan": "growth",
}

WEBHOOK_ENDPOINT: dict[str, Any] = {
    "id": ID,
    "url": "https://example.com/hook",
    "description": "",
    "events": ["*"],
    "enabled": True,
    "consecutive_failures": 0,
    "created_at": TS,
}

BILL_RECORD: dict[str, Any] = {"paid_at": TS, "paid_by": ID, "assigned_to": None}

BILL: dict[str, Any] = {
    **DOCUMENT_LIST_ITEM,
    "due_date": "2026-11-15",
    "bill": {"paid_at": None, "paid_by": None, "assigned_to": None},
    "kind": None,
    "related": {"document_id": None, "link": ""},
    "letter": None,
    "logo": "northwind.example",
}

BILL_DETAIL: dict[str, Any] = {
    "document": DOCUMENT,
    "extraction": extraction("done"),
    "review_queue": [],
    "bill": BILL_RECORD,
}

BILLS_SUMMARY: dict[str, Any] = {
    "unpaid": 2,
    "overdue": 1,
    "due_soon": [{"currency": "EUR", "count": 2, "total_cents": 9600}],
    "days": 30,
    "today": "2026-11-01",
}

BILLS_STATS: dict[str, Any] = {
    "month": "2026-10",
    "totals": [
        {"currency": "EUR", "count": 2, "paid_count": 1, "total_cents": 9600, "paid_cents": 4800}
    ],
    "trend": [{"month": "2026-10", "currency": "EUR", "count": 2, "total_cents": 9600}],
    "top_senders": [{"name": "Northwind Oy", "count": 2}],
    "senders": [{"name": "Northwind Oy", "count": 2}],
}

HELD_EMAIL: dict[str, Any] = {
    "id": ID,
    "from_email": "bills@northwind.example",
    "subject": "Your bill",
    "status": "held",
    "created_at": TS,
    "hold_reason": "new_sender",
    "sender": "verified",
    "files": [
        {"id": ID, "filename": "bill.pdf", "content_type": "application/pdf", "size_bytes": 99}
    ],
}
