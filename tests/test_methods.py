"""Every API method sends the right HTTP method and path and returns the right type.

Each case runs against both clients; the async one awaits the same call.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from invoist import AsyncInvoist, FileDownload, Invoist
from invoist import models as m

from .fakes import (
    BILL,
    BILL_DETAIL,
    BILL_RECORD,
    BILLS_STATS,
    BILLS_SUMMARY,
    CATEGORY,
    DOCUMENT,
    DOCUMENT_LIST_ITEM,
    HELD_EMAIL,
    ID,
    REVIEW_ITEM,
    REVIEW_LIST_ITEM,
    SPEC,
    STATS,
    USAGE,
    WEBHOOK_ENDPOINT,
    FakeAPI,
    async_client,
    document_detail,
    extraction,
    reply,
    sync_client,
)

Client = Invoist | AsyncInvoist


@dataclass(frozen=True)
class Case:
    """One method call, the request it must send, and what it must return."""

    name: str
    call: Callable[[Any], Any]
    method: str
    path: str
    response: httpx.Response
    returns: type | tuple[type, ...] | None


def _file(content: bytes, content_type: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=content,
        headers={
            "Content-Type": content_type,
            "Content-Disposition": 'inline; filename="Lasku 10.pdf"',
        },
    )


CASES = [
    Case(
        "extract",
        lambda c: c.extract(b"%PDF-1.4"),
        "POST",
        "/v1/extract",
        reply(201, {"document": DOCUMENT, "extraction": extraction("pending"), "duplicate": False}),
        m.ExtractResult,
    ),
    Case(
        "extract_batch",
        lambda c: c.extract_batch([b"%PDF-1.4", b"%PDF-1.5"]),
        "POST",
        "/v1/extract/batch",
        reply(
            200,
            {"results": [{"filename": "a.pdf", "document_id": ID}], "accepted": 1, "rejected": 0},
        ),
        m.BatchResult,
    ),
    Case(
        "list_documents",
        lambda c: c.list_documents(),
        "GET",
        "/v1/documents",
        reply(200, {"documents": [DOCUMENT_LIST_ITEM]}),
        list,
    ),
    Case(
        "get_document",
        lambda c: c.get_document(ID),
        "GET",
        f"/v1/documents/{ID}",
        reply(200, document_detail()),
        m.DocumentDetail,
    ),
    Case(
        "get_document_file",
        lambda c: c.get_document_file(ID),
        "GET",
        f"/v1/documents/{ID}/file",
        _file(b"%PDF-1.4 bytes", "application/pdf"),
        FileDownload,
    ),
    Case(
        "wait_for_extraction",
        lambda c: c.wait_for_extraction(ID),
        "GET",
        f"/v1/documents/{ID}",
        reply(200, document_detail("done")),
        m.Extraction,
    ),
    Case(
        "list_review_queue",
        lambda c: c.list_review_queue(),
        "GET",
        "/v1/review-queue",
        reply(200, {"review_queue": [REVIEW_LIST_ITEM]}),
        list,
    ),
    Case(
        "resolve_review_item",
        lambda c: c.resolve_review_item(ID),
        "POST",
        f"/v1/review-queue/{ID}/resolve",
        reply(200, {"review_queue_item": {**REVIEW_ITEM, "status": "resolved"}}),
        m.ReviewQueueItem,
    ),
    Case(
        "list_categories",
        lambda c: c.list_categories(),
        "GET",
        "/v1/categories",
        reply(200, {"categories": [CATEGORY]}),
        list,
    ),
    Case("get_usage", lambda c: c.get_usage(), "GET", "/v1/usage", reply(200, USAGE), m.Usage),
    Case(
        "get_stats",
        lambda c: c.get_stats(),
        "GET",
        "/v1/stats/overview",
        reply(200, STATS),
        m.StatsOverview,
    ),
    Case(
        "list_webhook_endpoints",
        lambda c: c.list_webhook_endpoints(),
        "GET",
        "/v1/webhook-endpoints",
        reply(200, {"endpoints": [WEBHOOK_ENDPOINT], "known_events": ["document.created"]}),
        m.WebhookEndpointList,
    ),
    Case(
        "create_webhook_endpoint",
        lambda c: c.create_webhook_endpoint("https://example.com/hook"),
        "POST",
        "/v1/webhook-endpoints",
        reply(201, {"endpoint": {**WEBHOOK_ENDPOINT, "secret": "whsec_x"}}),
        m.WebhookEndpointWithSecret,
    ),
    Case(
        "delete_webhook_endpoint",
        lambda c: c.delete_webhook_endpoint(ID),
        "DELETE",
        f"/v1/webhook-endpoints/{ID}",
        httpx.Response(204),
        None,
    ),
    Case(
        "bills.list",
        lambda c: c.bills.list(),
        "GET",
        "/v1/bills",
        reply(200, {"bills": [BILL]}),
        list,
    ),
    Case(
        "bills.get",
        lambda c: c.bills.get(ID),
        "GET",
        f"/v1/bills/{ID}",
        reply(200, BILL_DETAIL),
        m.BillDetail,
    ),
    Case(
        "bills.get_file",
        lambda c: c.bills.get_file(ID),
        "GET",
        f"/v1/bills/{ID}/file",
        _file(b"\x89PNG\r\n\x1a\n", "image/png"),
        FileDownload,
    ),
    Case(
        "bills.summary",
        lambda c: c.bills.summary(),
        "GET",
        "/v1/bills/summary",
        reply(200, BILLS_SUMMARY),
        m.BillsSummary,
    ),
    Case(
        "bills.stats",
        lambda c: c.bills.stats(),
        "GET",
        "/v1/bills/stats",
        reply(200, BILLS_STATS),
        m.BillsStats,
    ),
    Case(
        "bills.mark_paid",
        lambda c: c.bills.mark_paid(ID),
        "POST",
        f"/v1/bills/{ID}/paid",
        reply(200, {"bill": BILL_RECORD}),
        m.BillRecord,
    ),
    Case(
        "bills.mark_unpaid",
        lambda c: c.bills.mark_unpaid(ID),
        "DELETE",
        f"/v1/bills/{ID}/paid",
        reply(200, {"bill": {**BILL_RECORD, "paid_at": None, "paid_by": None}}),
        m.BillRecord,
    ),
    Case(
        "held_emails.list",
        lambda c: c.held_emails.list(),
        "GET",
        "/v1/held-emails",
        reply(200, {"held_emails": [HELD_EMAIL]}),
        list,
    ),
]

LIST_ITEM_TYPES = {
    "list_documents": m.DocumentListItem,
    "list_review_queue": m.ReviewQueueListItem,
    "list_categories": m.Category,
    "bills.list": m.Bill,
    "held_emails.list": m.HeldEmail,
}


def _fresh(response: httpx.Response) -> httpx.Response:
    """A new copy, since a client takes ownership of the responses it receives."""
    return httpx.Response(response.status_code, headers=response.headers, content=response.content)


def _check(case: Case, api: FakeAPI, result: Any) -> None:
    assert len(api.requests) == 1
    assert api.last.method == case.method
    assert api.last.url.path == case.path
    if case.returns is None:
        assert result is None
        return
    assert isinstance(result, case.returns)
    if isinstance(result, list):
        assert len(result) == 1
        assert isinstance(result[0], LIST_ITEM_TYPES[case.name])


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_sync_method(case: Case) -> None:
    api = FakeAPI(_fresh(case.response))
    _check(case, api, case.call(sync_client(api)))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
async def test_async_method(case: Case) -> None:
    api = FakeAPI(_fresh(case.response))
    pending = case.call(async_client(api))
    assert inspect.isawaitable(pending)
    _check(case, api, await pending)


def test_extract_and_wait_hits_extract_then_document() -> None:
    api = FakeAPI(
        reply(201, {"document": DOCUMENT, "extraction": extraction("pending"), "duplicate": False}),
        reply(200, document_detail("done")),
    )
    result = sync_client(api).extract_and_wait(b"%PDF-1.4")
    assert [(r.method, r.url.path) for r in api.requests] == [
        ("POST", "/v1/extract"),
        ("GET", f"/v1/documents/{ID}"),
    ]
    assert result.extraction.status == "done"


def test_the_sync_and_async_clients_have_the_same_methods() -> None:
    def public(obj: object) -> set[str]:
        return {n for n in dir(obj) if not n.startswith("_")}

    assert public(Invoist) - {"close"} == public(AsyncInvoist) - {"aclose"}
    sync = sync_client(FakeAPI())
    asynchronous = async_client(FakeAPI())
    assert public(sync.bills) == public(asynchronous.bills)
    assert public(sync.held_emails) == public(asynchronous.held_emails)


def test_every_operation_in_the_spec_has_a_method() -> None:
    if not SPEC.is_file():
        pytest.skip("openapi.yaml is not next to this checkout")
    import yaml

    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    operations = {
        (method.upper(), template)
        for template, item in spec["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    covered = {(case.method, re.sub(re.escape(ID), "{id}", case.path)) for case in CASES}
    assert operations - covered == set(), "operations in openapi.yaml with no SDK method"
