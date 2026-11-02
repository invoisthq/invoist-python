"""Client behaviour (SPEC §3-§6) against a fake transport: nothing here touches the network."""

from __future__ import annotations

import asyncio
import io
import json
import pickle
import platform
import re
from datetime import UTC, date, datetime
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

import httpx
import pytest

import invoist
from invoist import AsyncInvoist, Invoist, InvoistError
from invoist._base import backoff, retry_delay

from .fakes import (
    API_KEY,
    BASE_URL,
    BILLS_STATS,
    BILLS_SUMMARY,
    DOCUMENT,
    ID,
    USAGE,
    FakeAPI,
    async_client,
    document_detail,
    extraction,
    reply,
    sync_client,
)

EXTRACTED = {"document": DOCUMENT, "extraction": extraction("pending"), "duplicate": False}


def _parts(request: httpx.Request) -> list[tuple[str | None, str | None, str, bytes]]:
    """Each multipart part's field name, filename, content type and bytes."""
    head = f"Content-Type: {request.headers['Content-Type']}\r\n\r\n".encode()
    message = BytesParser(policy=HTTP).parsebytes(head + request.content)
    out = []
    for part in message.iter_parts():
        payload = part.get_payload(decode=True)
        assert isinstance(payload, bytes)
        name = part.get_param("name", header="content-disposition")
        out.append(
            (
                name if isinstance(name, str) else None,
                part.get_filename(),
                part.get_content_type(),
                payload,
            )
        )
    return out


# -- construction ------------------------------------------------------------


@pytest.mark.parametrize("key", ["", "   "])
def test_an_empty_key_fails_at_construction(key: str) -> None:
    with pytest.raises(ValueError, match="API key is required"):
        Invoist(key)
    with pytest.raises(ValueError, match="API key is required"):
        AsyncInvoist(key)


def test_defaults() -> None:
    client = Invoist(API_KEY)
    assert client.base_url == "https://api.invoi.st"
    assert client.timeout == 60
    assert client.max_retries == 2
    client.close()


def test_base_url_trailing_slashes_are_trimmed() -> None:
    api = FakeAPI(reply(200, USAGE))
    client = Invoist(
        API_KEY,
        base_url="https://api.test///",
        http_client=httpx.Client(transport=httpx.MockTransport(api.handle)),
    )
    client.get_usage()
    assert str(api.last.url) == "https://api.test/v1/usage"


def test_repr_never_shows_the_key() -> None:
    assert API_KEY not in repr(sync_client(FakeAPI()))


def test_an_injected_http_client_is_left_open() -> None:
    http = httpx.Client(transport=httpx.MockTransport(FakeAPI().handle))
    with Invoist(API_KEY, http_client=http):
        pass
    assert not http.is_closed
    owned = Invoist(API_KEY)
    with owned:
        pass
    assert owned._http.is_closed


async def test_async_context_manager_closes_its_own_client() -> None:
    async with AsyncInvoist(API_KEY) as client:
        pass
    assert client._http.is_closed


# -- headers -----------------------------------------------------------------


def test_every_request_sends_auth_accept_and_user_agent() -> None:
    api = FakeAPI(reply(200, USAGE), httpx.Response(200, content=b"%PDF"))
    client = sync_client(api)
    client.get_usage()
    client.get_document_file(ID)
    for request in api.requests:
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["User-Agent"] == (
            f"invoist-python/{invoist.__version__} (python {platform.python_version()})"
        )
    assert re.fullmatch(
        r"invoist-python/\d+\.\d+\.\d+ \(python \d+\.\d+\.\d+\S*\)", invoist.USER_AGENT
    )


def test_json_bodies_are_sent_as_json() -> None:
    api = FakeAPI(
        reply(
            201,
            {
                "endpoint": {
                    "id": ID,
                    "url": "u",
                    "description": "d",
                    "events": [],
                    "enabled": True,
                    "consecutive_failures": 0,
                    "created_at": "2026-11-01T10:40:00Z",
                    "secret": "s",
                }
            },
        )
    )
    sync_client(api).create_webhook_endpoint(
        "https://example.com/hook", events=["extraction.completed"], description="Ledger"
    )
    assert api.last.headers["Content-Type"] == "application/json"
    assert json.loads(api.last.content) == {
        "url": "https://example.com/hook",
        "events": ["extraction.completed"],
        "description": "Ledger",
    }


def test_resolve_review_item_sends_its_status() -> None:
    item = {
        "id": ID,
        "document_id": ID,
        "extraction_id": ID,
        "reason": "duplicate",
        "status": "dismissed",
        "created_at": "2026-11-01T10:40:00Z",
    }
    api = FakeAPI(reply(200, {"review_queue_item": item}), reply(200, {"review_queue_item": item}))
    client = sync_client(api)
    client.resolve_review_item(ID)
    assert json.loads(api.requests[0].content) == {"status": "resolved"}
    client.resolve_review_item(ID, "dismissed")
    assert json.loads(api.requests[1].content) == {"status": "dismissed"}


def test_ids_are_percent_encoded_as_one_segment() -> None:
    api = FakeAPI(reply(200, document_detail()))
    sync_client(api).get_document("a/b?c")
    assert api.last.url.raw_path == b"/v1/documents/a%2Fb%3Fc"


def test_an_empty_id_is_refused_before_any_request() -> None:
    api = FakeAPI()
    with pytest.raises(ValueError, match="id"):
        sync_client(api).bills.get("")
    assert api.requests == []


# -- query encoding ----------------------------------------------------------


def test_booleans_months_and_omitted_empties() -> None:
    api = FakeAPI(reply(200, {"bills": []}), reply(200, {"bills": []}))
    client = sync_client(api)
    client.bills.list(paid=False, month=date(2026, 3, 15), sender="", q=None, limit=10, offset=0)
    assert dict(api.last.url.params) == {
        "paid": "false",
        "month": "2026-03",
        "limit": "10",
        "offset": "0",
    }
    client.bills.list(paid=True, month="2026-10", sender="Helen Oy")
    assert dict(api.last.url.params) == {"paid": "true", "month": "2026-10", "sender": "Helen Oy"}


def test_no_filters_means_no_query_string() -> None:
    api = FakeAPI(reply(200, {"documents": []}))
    sync_client(api).list_documents()
    assert api.last.url.query == b""


def test_document_filters() -> None:
    api = FakeAPI(reply(200, {"documents": []}))
    sync_client(api).list_documents(
        limit=5, offset=10, status="done", flagged=True, q="Helen", category="none"
    )
    assert dict(api.last.url.params) == {
        "limit": "5",
        "offset": "10",
        "status": "done",
        "flagged": "true",
        "q": "Helen",
        "category": "none",
    }


def test_flagged_false_is_left_out() -> None:
    api = FakeAPI(reply(200, {"documents": []}))
    sync_client(api).list_documents(flagged=False)
    assert api.last.url.query == b""


def test_summary_and_stats_dates() -> None:
    api = FakeAPI(reply(200, BILLS_SUMMARY), reply(200, BILLS_STATS), reply(200, BILLS_STATS))
    client = sync_client(api)
    client.bills.summary(today=datetime(2026, 11, 1, 23, 30), days=7)
    assert dict(api.requests[0].url.params) == {"today": "2026-11-01", "days": "7"}
    client.bills.stats(month=datetime(2026, 10, 31, 12, 0), sender="Helen Oy")
    assert dict(api.requests[1].url.params) == {"month": "2026-10", "sender": "Helen Oy"}
    client.bills.stats()
    assert api.requests[2].url.query == b""


def test_aware_datetimes_are_formatted_in_local_time() -> None:
    moment = datetime(2026, 10, 31, 23, 30, tzinfo=UTC)
    local = moment.astimezone()
    api = FakeAPI(reply(200, BILLS_SUMMARY), reply(200, {"bills": []}))
    client = sync_client(api)
    client.bills.summary(today=moment)
    assert api.requests[0].url.params["today"] == local.date().isoformat()
    client.bills.list(month=moment)
    assert api.requests[1].url.params["month"] == f"{local.year:04d}-{local.month:02d}"


def test_review_queue_status_filter() -> None:
    api = FakeAPI(reply(200, {"review_queue": []}))
    sync_client(api).list_review_queue(status="pending")
    assert dict(api.last.url.params) == {"status": "pending"}


# -- uploads -----------------------------------------------------------------


def test_extract_sends_multipart_with_name_and_type() -> None:
    api = FakeAPI(reply(201, EXTRACTED))
    result = sync_client(api).extract(("Lasku 10.pdf", b"%PDF-1.4 data"), idempotency_key="job-42")
    assert api.last.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert api.last.headers["Idempotency-Key"] == "job-42"
    assert _parts(api.last) == [("file", "Lasku 10.pdf", "application/pdf", b"%PDF-1.4 data")]
    assert result.duplicate is False
    assert result.extraction is not None
    assert result.extraction.status == "pending"


def test_no_idempotency_key_header_unless_given() -> None:
    api = FakeAPI(reply(201, EXTRACTED))
    sync_client(api).extract(b"%PDF-1.4")
    assert "Idempotency-Key" not in api.last.headers


def test_bare_bytes_get_a_name_from_their_content() -> None:
    api = FakeAPI(reply(201, EXTRACTED), reply(201, EXTRACTED), reply(201, EXTRACTED))
    client = sync_client(api)
    client.extract(b"%PDF-1.7")
    client.extract(b"\xff\xd8\xff\xe0 jpeg")
    client.extract(b"no idea")
    assert [p[0][1:3] for p in map(_parts, api.requests)] == [
        ("upload.pdf", "application/pdf"),
        ("upload.jpg", "image/jpeg"),
        ("upload", "application/octet-stream"),
    ]


def test_paths_and_file_objects(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.png"
    receipt.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    api = FakeAPI(reply(201, EXTRACTED), reply(201, EXTRACTED), reply(201, EXTRACTED))
    client = sync_client(api)
    client.extract(receipt)
    with receipt.open("rb") as handle:
        client.extract(handle)
    client.extract(("scan", io.BytesIO(b"bytes"), "image/jpeg"))
    assert [p[0] for p in map(_parts, api.requests)] == [
        ("file", "receipt.png", "image/png", b"\x89PNG\r\n\x1a\nimage"),
        ("file", "receipt.png", "image/png", b"\x89PNG\r\n\x1a\nimage"),
        ("file", "scan", "image/jpeg", b"bytes"),
    ]


def test_text_mode_files_are_refused() -> None:
    with pytest.raises(TypeError, match="binary mode"):
        sync_client(FakeAPI()).extract(io.StringIO("text"))  # type: ignore[arg-type]


def test_batch_sends_one_files_part_per_file() -> None:
    body = {"results": [{"filename": "a.pdf"}, {"filename": "b.png"}], "accepted": 2, "rejected": 0}
    api = FakeAPI(reply(200, body))
    result = sync_client(api).extract_batch([("a.pdf", b"%PDF"), ("b.png", b"\x89PNG\r\n\x1a\n")])
    assert [(p[0], p[1]) for p in _parts(api.last)] == [("files", "a.pdf"), ("files", "b.png")]
    assert result.accepted == 2


def test_batch_needs_a_file() -> None:
    with pytest.raises(ValueError, match="at least one"):
        sync_client(FakeAPI()).extract_batch([])


def test_an_upload_is_buffered_so_a_retry_resends_it() -> None:
    api = FakeAPI(reply(503), reply(201, EXTRACTED))
    sync_client(api).extract(("a.pdf", io.BytesIO(b"%PDF stream")))
    assert len(api.requests) == 2
    assert _parts(api.requests[0]) == _parts(api.requests[1])
    assert _parts(api.requests[1])[0][3] == b"%PDF stream"


async def test_async_upload() -> None:
    api = FakeAPI(reply(201, EXTRACTED))
    await async_client(api).extract(("a.pdf", b"%PDF"), idempotency_key="k")
    assert _parts(api.last) == [("file", "a.pdf", "application/pdf", b"%PDF")]
    assert api.last.headers["Idempotency-Key"] == "k"


# -- responses ---------------------------------------------------------------


def test_binary_downloads_keep_bytes_type_and_name() -> None:
    content = bytes(range(256))
    api = FakeAPI(
        httpx.Response(
            200,
            content=content,
            headers={
                "Content-Type": "application/pdf",
                "Content-Disposition": 'inline; filename="Lasku.pdf"',
            },
        )
    )
    file = sync_client(api).get_document_file(ID)
    assert file.content == content
    assert file.content_type == "application/pdf"
    assert file.filename == "Lasku.pdf"
    assert len(file) == 256


def test_a_download_without_a_name() -> None:
    api = FakeAPI(httpx.Response(200, content=b"x", headers={"Content-Type": "image/png"}))
    file = sync_client(api).bills.get_file(ID)
    assert (file.content, file.content_type, file.filename) == (b"x", "image/png", None)


def test_a_204_returns_none() -> None:
    api = FakeAPI(httpx.Response(204))
    sync_client(api).delete_webhook_endpoint(ID)
    assert api.last.method == "DELETE"


def test_unknown_fields_and_enum_values_are_kept() -> None:
    body = {**USAGE, "brand_new_field": {"x": 1}}
    api = FakeAPI(
        reply(200, body),
        reply(
            200,
            {
                "review_queue": [
                    {
                        "id": ID,
                        "document_id": ID,
                        "extraction_id": ID,
                        "reason": "a_reason_from_the_future",
                        "status": "pending",
                        "created_at": "2026-11-01T10:40:00Z",
                        "original_filename": "a.pdf",
                        "content_type": "application/pdf",
                        "document_status": "done",
                    }
                ]
            },
        ),
    )
    client = sync_client(api)
    usage = client.get_usage()
    assert usage.model_extra == {"brand_new_field": {"x": 1}}
    assert str(client.list_review_queue()[0].reason) == "a_reason_from_the_future"


def test_money_is_int_and_dates_are_dates() -> None:
    api = FakeAPI(reply(200, document_detail("done")))
    detail = sync_client(api).get_document(ID)
    assert detail.extraction is not None
    assert detail.extraction.total_cents == 4800
    assert isinstance(detail.extraction.total_cents, int)
    assert detail.extraction.invoice_date == date(2026, 10, 15)


def test_a_success_that_does_not_fit_the_model_is_an_invoist_error() -> None:
    api = FakeAPI(reply(200, {"documents": "nope"}), httpx.Response(200, content=b"<html>"))
    client = sync_client(api)
    with pytest.raises(InvoistError) as caught:
        client.list_documents()
    assert (caught.value.status, caught.value.code) == (200, "unexpected_response")
    with pytest.raises(InvoistError) as caught:
        client.get_usage()
    assert caught.value.code == "unexpected_response"
    assert caught.value.body == "<html>"


# -- errors ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (httpx.ConnectError("refused"), "network_error"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectTimeout("slow"), "timeout"),
        (httpx.RemoteProtocolError("bad"), "network_error"),
    ],
)
def test_no_response_is_status_zero(exc: Exception, code: str) -> None:
    api = FakeAPI(exc)
    with pytest.raises(InvoistError) as caught:
        sync_client(api, max_retries=0).get_usage()
    assert (caught.value.status, caught.value.code, caught.value.is_retryable) == (0, code, True)
    assert isinstance(caught.value.__cause__, httpx.RequestError)


def test_errors_print_usefully_and_pickle() -> None:
    err = InvoistError(
        "invalid API key", status=401, code="invalid_api_key", request_id="req_1", body="{}"
    )
    assert str(err) == "invalid API key (status 401, code invalid_api_key, request req_1)"
    copy = pickle.loads(pickle.dumps(err))  # noqa: S301 - our own object
    assert (copy.message, copy.status, copy.code, copy.request_id, copy.body) == (
        "invalid API key",
        401,
        "invalid_api_key",
        "req_1",
        "{}",
    )


# -- retries -----------------------------------------------------------------


def test_backoff_doubles_with_jitter_and_caps_at_eight_seconds() -> None:
    for attempt in range(10):
        delay = backoff(attempt)
        base = 0.5 * 2**attempt
        assert min(base * 0.8, 8.0) <= delay <= min(base * 1.2, 8.0)
    assert backoff(20) == 8.0


@pytest.mark.parametrize(("header", "expected"), [("3", 3.0), ("0", 0.0), (" 2 ", 2.0)])
def test_retry_after_seconds_win(header: str, expected: float) -> None:
    assert retry_delay(3, header) == expected


@pytest.mark.parametrize(("header", "expected"), [("60", 60.0), ("61", None), ("3600", None)])
def test_a_retry_after_over_a_minute_is_not_waited_for(header: str, expected: float | None) -> None:
    assert retry_delay(0, header) == expected


@pytest.mark.parametrize("header", ["soon", "1.5", "-1", "Wed, 21 Oct 2026 07:28:00 GMT"])
def test_a_retry_after_that_is_not_whole_seconds_falls_back_to_backoff(header: str) -> None:
    delay = retry_delay(0, header)
    assert delay is not None
    assert 0.4 <= delay <= 0.6


def test_max_retries_zero_means_one_attempt() -> None:
    api = FakeAPI(reply(503))
    with pytest.raises(InvoistError):
        sync_client(api, max_retries=0).get_usage()
    assert len(api.requests) == 1
    assert api.sleeps == []


def test_downloads_are_retried_too() -> None:
    api = FakeAPI(reply(502), httpx.Response(200, content=b"%PDF"))
    assert sync_client(api).get_document_file(ID).content == b"%PDF"
    assert len(api.requests) == 2


async def test_async_cancellation_is_not_retried() -> None:
    started = asyncio.Event()

    async def hang(_: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    api = FakeAPI(hang, reply(200, USAGE))
    task = asyncio.create_task(async_client(api).get_usage())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(api.requests) == 1
    assert api.sleeps == []


# -- waiting for an extraction -----------------------------------------------


def test_wait_polls_until_done() -> None:
    api = FakeAPI(
        reply(200, document_detail(None)),
        reply(200, document_detail("pending")),
        reply(200, document_detail("done")),
    )
    result = sync_client(api).wait_for_extraction(ID, poll_interval=1.5)
    assert result.status == "done"
    assert len(api.requests) == 3
    assert api.sleeps == [1.5, 1.5]


def test_wait_returns_a_failed_extraction() -> None:
    failed = document_detail(None)
    failed["extraction"] = extraction("failed", error_message="unreadable scan")
    api = FakeAPI(reply(200, document_detail("pending")), reply(200, failed))
    result = sync_client(api).wait_for_extraction(ID)
    assert (result.status, result.error_message) == ("failed", "unreadable scan")
    assert api.sleeps == [2.0]


def test_wait_times_out() -> None:
    api = FakeAPI(*[reply(200, document_detail("pending")) for _ in range(10)])
    with pytest.raises(InvoistError) as caught:
        sync_client(api).wait_for_extraction(ID, timeout=5, poll_interval=2)
    assert (caught.value.status, caught.value.code) == (0, "extraction_timeout")
    assert len(api.requests) == 3
    assert sum(api.sleeps) <= 5


def test_wait_defaults_to_two_minutes_every_two_seconds() -> None:
    api = FakeAPI(*[reply(200, document_detail("pending")) for _ in range(61)])
    with pytest.raises(InvoistError):
        sync_client(api).wait_for_extraction(ID)
    assert set(api.sleeps) == {2.0}
    assert len(api.requests) == 61


def test_extract_and_wait_skips_polling_when_already_done() -> None:
    done = {"document": DOCUMENT, "extraction": extraction("done"), "duplicate": True}
    api = FakeAPI(reply(200, done))
    result = sync_client(api).extract_and_wait(b"%PDF")
    assert result.extraction.status == "done"
    assert len(api.requests) == 1


async def test_async_wait_and_timeout() -> None:
    api = FakeAPI(reply(200, document_detail("pending")), reply(200, document_detail("done")))
    client = async_client(api)
    assert (await client.wait_for_extraction(ID)).status == "done"
    api.queue(*[reply(200, document_detail("pending")) for _ in range(3)])
    with pytest.raises(InvoistError) as caught:
        await client.wait_for_extraction(ID, timeout=4, poll_interval=2)
    assert caught.value.code == "extraction_timeout"


async def test_async_extract_and_wait() -> None:
    api = FakeAPI(reply(201, EXTRACTED), reply(200, document_detail("done")))
    result = await async_client(api).extract_and_wait(b"%PDF")
    assert result.document.id == ID
    assert result.extraction.status == "done"


def test_base_url_is_used_for_requests() -> None:
    api = FakeAPI(reply(200, USAGE))
    sync_client(api).get_usage()
    assert str(api.last.url).startswith(BASE_URL)
