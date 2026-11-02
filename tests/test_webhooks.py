"""verify_webhook beyond the shared vectors: input forms, options and edge cases."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from invoist import EventType, InvoistError
from invoist.webhooks import DELIVERY_HEADER, EVENT_HEADER, SIGNATURE_HEADER, verify_webhook

SECRET = "whsec_test"
T = 1793520000
EVENT = {
    "id": "evt_1",
    "type": "extraction.completed",
    "created_at": "2026-11-01T10:40:00Z",
    "data": {"document_id": "d", "status": "done"},
}
BODY = json.dumps(EVENT, ensure_ascii=False).encode()


def sign(body: bytes, t: int = T, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()


def test_returns_a_typed_event() -> None:
    event = verify_webhook(BODY, f"t={T},v1={sign(BODY)}", SECRET, now=T)
    assert event.id == "evt_1"
    assert event.type == EventType.EXTRACTION_COMPLETED
    assert event.created_at == datetime(2026, 11, 1, 10, 40, tzinfo=UTC)
    assert event.data == {"document_id": "d", "status": "done"}


def test_accepts_str_bytearray_and_memoryview() -> None:
    header = f"t={T},v1={sign(BODY)}"
    for payload in (BODY.decode(), bytearray(BODY), memoryview(BODY)):
        assert verify_webhook(payload, header, SECRET, now=T).id == "evt_1"


def test_tolerance_and_now_accept_timedelta_and_datetime() -> None:
    header = f"t={T},v1={sign(BODY)}"
    later = datetime.fromtimestamp(T + 60, tz=UTC)
    assert verify_webhook(BODY, header, SECRET, tolerance=timedelta(minutes=2), now=later)
    with pytest.raises(InvoistError) as caught:
        verify_webhook(BODY, header, SECRET, tolerance=timedelta(seconds=30), now=later)
    assert caught.value.code == "signature_too_old"


def test_uses_the_real_clock_by_default() -> None:
    import time

    now = int(time.time())
    assert verify_webhook(BODY, f"t={now},v1={sign(BODY, now)}", SECRET).id == "evt_1"
    with pytest.raises(InvoistError) as caught:
        verify_webhook(BODY, f"t={T - 10_000},v1={sign(BODY, T - 10_000)}", SECRET)
    assert caught.value.code == "signature_too_old"


@pytest.mark.parametrize(
    "header",
    [
        None,
        f"t={T},t={T},v1={sign(BODY)}",
        f"t=+{T},v1={sign(BODY)}",
        f"t={T}.0,v1={sign(BODY)}",
        f"t={T},v1=",
        f"t={T},v1=é",
    ],
)
def test_malformed_headers_are_invalid(header: str | None) -> None:
    with pytest.raises(InvoistError) as caught:
        verify_webhook(BODY, header, SECRET, now=T)
    assert (caught.value.status, caught.value.code) == (400, "invalid_signature")


def test_a_signed_body_that_is_not_an_event() -> None:
    body = b"not json"
    with pytest.raises(InvoistError) as caught:
        verify_webhook(body, f"t={T},v1={sign(body)}", SECRET, now=T)
    assert (caught.value.status, caught.value.code) == (400, "invalid_payload")


def test_event_types_and_headers() -> None:
    assert [e.value for e in EventType] == [
        "document.created",
        "extraction.completed",
        "extraction.failed",
        "review_item.created",
        "review_item.resolved",
        "document_request.fulfilled",
    ]
    assert str(EventType.DOCUMENT_CREATED) == "document.created"
    assert (SIGNATURE_HEADER, EVENT_HEADER, DELIVERY_HEADER) == (
        "X-Invoist-Signature",
        "X-Invoist-Event",
        "X-Invoist-Delivery",
    )
