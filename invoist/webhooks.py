"""Verify the webhooks Invoist sends, and the event types they carry.

Every delivery is signed with your endpoint's secret in the
``X-Invoist-Signature`` header. Check it before trusting the body::

    from invoist.webhooks import EventType, verify_webhook

    event = verify_webhook(raw_body, headers["X-Invoist-Signature"], secret)
    if event.type == EventType.EXTRACTION_COMPLETED:
        ...

Pass the **raw request body**, exactly as received. Parsing the JSON and
serialising it again changes the bytes, and the signature with them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timedelta
from enum import StrEnum

import pydantic

from .errors import InvoistError
from .models import WebhookEvent

__all__ = [
    "DEFAULT_TOLERANCE",
    "DELIVERY_HEADER",
    "EVENT_HEADER",
    "SIGNATURE_HEADER",
    "EventType",
    "WebhookEvent",
    "verify_webhook",
]

SIGNATURE_HEADER = "X-Invoist-Signature"
"""The header carrying ``t=<unix seconds>,v1=<hex HMAC-SHA256>``."""
EVENT_HEADER = "X-Invoist-Event"
"""The header carrying the event type."""
DELIVERY_HEADER = "X-Invoist-Delivery"
"""The header carrying a unique id for this delivery attempt."""

DEFAULT_TOLERANCE = 300.0
"""How far, in seconds, a signature's timestamp may be from now (5 minutes)."""

_DIGITS = re.compile(r"[0-9]+")


class EventType(StrEnum):
    """Every event type Invoist sends. Members compare equal to their strings."""

    DOCUMENT_CREATED = "document.created"
    """A document was added; reading it has not finished. ``data`` has ``document_id``."""
    EXTRACTION_COMPLETED = "extraction.completed"
    """A document was read. ``data`` has ``document_id``, ``extraction_id`` and ``status``."""
    EXTRACTION_FAILED = "extraction.failed"
    """A document could not be read. ``data`` has ``document_id`` and ``extraction_id``."""
    REVIEW_ITEM_CREATED = "review_item.created"
    """Something was flagged for a person to check."""
    REVIEW_ITEM_RESOLVED = "review_item.resolved"
    """A flagged item was resolved or dismissed."""
    DOCUMENT_REQUEST_FULFILLED = "document_request.fulfilled"
    """Someone sent the document a request asked for. ``data`` has ``request_id``."""


def _invalid(message: str) -> InvoistError:
    return InvoistError(message, status=400, code="invalid_signature")


def verify_webhook(
    payload: bytes | bytearray | memoryview | str,
    signature_header: str | None,
    secret: str,
    *,
    tolerance: float | timedelta = DEFAULT_TOLERANCE,
    now: float | datetime | None = None,
) -> WebhookEvent:
    """Check a webhook's signature and return its event.

    Args:
        payload: The raw request body, exactly as received: ``request.get_data()``
            in Flask, ``await request.body()`` in FastAPI. A ``str`` is
            encoded as UTF-8.
        signature_header: The ``X-Invoist-Signature`` header.
        secret: The endpoint's signing secret (``whsec_...``).
        tolerance: How far the signature's timestamp may be from ``now``, in
            either direction, in seconds. ``0`` turns the check off; only do
            that to replay a captured delivery in a test.
        now: The current time, as Unix seconds or a datetime. For tests.

    Returns:
        The verified event: ``id``, ``type``, ``created_at`` and ``data``.

    Raises:
        InvoistError: Status 400 with code ``invalid_signature`` (a malformed
            header, or no signature matches), ``signature_too_old`` (the
            timestamp is outside ``tolerance``), or ``invalid_payload`` (the
            signed body is not an event).
    """
    body = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)

    timestamp: str | None = None
    signatures: list[str] = []
    for part in (signature_header or "").split(","):
        key, sep, value = part.strip().partition("=")
        if not sep:
            continue
        if key == "t":
            if timestamp is not None:
                raise _invalid("The X-Invoist-Signature header has more than one timestamp.")
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if timestamp is None or not signatures:
        raise _invalid("The X-Invoist-Signature header needs a t= timestamp and a v1= signature.")
    if not _DIGITS.fullmatch(timestamp):
        raise _invalid("The X-Invoist-Signature timestamp is not a number.")

    expected = (
        hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256)
        .hexdigest()
        .encode("ascii")
    )
    # Compare against every v1, without stopping early, so timing says nothing.
    matched = False
    for candidate in signatures:
        matched |= hmac.compare_digest(expected, candidate.encode("utf-8"))
    if not matched:
        raise _invalid("The webhook signature does not match. Check the secret and the raw body.")

    window = tolerance.total_seconds() if isinstance(tolerance, timedelta) else float(tolerance)
    if window > 0:
        current = (
            now.timestamp() if isinstance(now, datetime) else time.time() if now is None else now
        )
        if abs(current - int(timestamp)) > window:
            raise InvoistError(
                "The webhook's timestamp is outside the allowed window; it may be a replay.",
                status=400,
                code="signature_too_old",
            )

    try:
        return WebhookEvent.model_validate(json.loads(body))
    except (ValueError, pydantic.ValidationError) as exc:
        raise InvoistError(
            "The signed webhook body is not an Invoist event.", status=400, code="invalid_payload"
        ) from exc
