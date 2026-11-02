"""The shared conformance vectors (testdata/conformance), run case by case on both clients."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from invoist import InvoistError, verify_webhook

from .fakes import FakeAPI, async_client, conformance, reply, sync_client

ERRORS = conformance("errors")["cases"]
RETRIES = conformance("retries")["cases"]
WEBHOOKS = conformance("webhooks")

PREDICATES = [
    "is_auth_error",
    "is_permission_error",
    "is_not_found",
    "is_rate_limited",
    "is_retryable",
]


def _named(cases: list[dict[str, Any]]) -> pytest.MarkDecorator:
    return pytest.mark.parametrize("case", cases, ids=[c["name"] for c in cases])


# -- errors.json -------------------------------------------------------------


def _error_response(case: dict[str, Any]) -> httpx.Response:
    return httpx.Response(case["status"], headers=case["headers"], content=case["body"].encode())


def _check_error(case: dict[str, Any], err: InvoistError) -> None:
    expect = case["expect"]
    assert err.status == case["status"]
    assert err.code == expect["code"]
    assert err.message == expect["message"]
    assert err.request_id == expect["request_id"]
    assert err.body == (case["body"] or None)
    for predicate in PREDICATES:
        assert getattr(err, predicate) is expect[predicate], predicate


@_named(ERRORS)
def test_error_sync(case: dict[str, Any]) -> None:
    api = FakeAPI(_error_response(case))
    with pytest.raises(InvoistError) as caught:
        sync_client(api, max_retries=0).get_usage()
    _check_error(case, caught.value)


@_named(ERRORS)
async def test_error_async(case: dict[str, Any]) -> None:
    api = FakeAPI(_error_response(case))
    with pytest.raises(InvoistError) as caught:
        await async_client(api, max_retries=0).get_usage()
    _check_error(case, caught.value)


# -- retries.json ------------------------------------------------------------


def _retry_replies(case: dict[str, Any]) -> list[httpx.Response | Exception]:
    out: list[httpx.Response | Exception] = []
    for r in case["responses"]:
        if r["status"] == 0:
            out.append(httpx.ConnectError("connection refused"))
            continue
        headers = {"Retry-After": r["retry_after"]} if "retry_after" in r else None
        body: dict[str, Any] = (
            {"categories": []} if r["status"] < 400 else {"error": {"code": "x", "message": "x"}}
        )
        out.append(reply(r["status"], body, headers))
    return out


def _check_retries(case: dict[str, Any], api: FakeAPI, error: InvoistError | None) -> None:
    expect = case["expect"]
    assert len(api.requests) == expect["attempts"]
    assert len(api.sleeps) == expect["attempts"] - 1
    if expect["ok"]:
        assert error is None
    else:
        assert error is not None
        assert error.status == expect["status"]
    # No waits_ms means every wait follows the backoff schedule.
    waits = expect.get("waits_ms") or [None] * (expect["attempts"] - 1)
    for attempt, (want_ms, slept) in enumerate(zip(waits, api.sleeps, strict=True)):
        if want_ms is None:
            backoff = 0.5 * 2**attempt
            assert backoff * 0.8 <= slept <= backoff * 1.2
        else:
            assert slept == want_ms / 1000


@_named(RETRIES)
def test_retries_sync(case: dict[str, Any]) -> None:
    api = FakeAPI(*_retry_replies(case))
    client = sync_client(api, max_retries=2)
    error: InvoistError | None = None
    try:
        client.list_categories()
    except InvoistError as exc:
        error = exc
    _check_retries(case, api, error)


@_named(RETRIES)
async def test_retries_async(case: dict[str, Any]) -> None:
    api = FakeAPI(*_retry_replies(case))
    client = async_client(api, max_retries=2)
    error: InvoistError | None = None
    try:
        await client.list_categories()
    except InvoistError as exc:
        error = exc
    _check_retries(case, api, error)


# -- webhooks.json -----------------------------------------------------------


@_named(WEBHOOKS["cases"])
def test_webhook(case: dict[str, Any]) -> None:
    expect = case["expect"]

    def verify() -> Any:
        return verify_webhook(
            case["payload"].encode("utf-8"),
            case["header"],
            WEBHOOKS["secret"],
            tolerance=case["tolerance"],
            now=case["now"],
        )

    if expect["ok"]:
        assert verify().type == expect["type"]
    else:
        with pytest.raises(InvoistError) as caught:
            verify()
        assert caught.value.status == 400
        assert caught.value.code == expect["code"]
