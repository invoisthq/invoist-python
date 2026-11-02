"""Read-only calls against a real API, skipped unless INVOIST_API_KEY is set.

    INVOIST_API_KEY=inv_sk_... [INVOIST_BASE_URL=http://localhost:8080] pytest tests/test_live.py

Works with a business key or a household's: each test uses the calls the
key's kind allows. Nothing here creates, changes or deletes anything.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest

from invoist import DEFAULT_BASE_URL, AsyncInvoist, Invoist, InvoistError

KEY = os.environ.get("INVOIST_API_KEY", "")
BASE_URL = os.environ.get("INVOIST_BASE_URL") or DEFAULT_BASE_URL
MISSING_ID = "00000000-0000-0000-0000-000000000000"

pytestmark = pytest.mark.skipif(not KEY, reason="set INVOIST_API_KEY to run live tests")


@pytest.fixture(scope="module")
def client() -> Iterator[Invoist]:
    with Invoist(KEY, base_url=BASE_URL) as c:
        yield c


@pytest.fixture(scope="module")
def household(client: Invoist) -> bool:
    """Whether the key is a household's, which answers only the bills routes."""
    try:
        client.get_usage()
    except InvoistError as err:
        if err.is_permission_error:
            return True
        raise
    return False


@pytest.fixture
async def aclient() -> AsyncIterator[AsyncInvoist]:
    async with AsyncInvoist(KEY, base_url=BASE_URL) as c:
        yield c


def test_a_bad_key_is_an_auth_error() -> None:
    with (
        Invoist("inv_sk_definitely_not_real", base_url=BASE_URL) as bad,
        pytest.raises(InvoistError) as caught,
    ):
        bad.get_usage()
    assert caught.value.is_auth_error
    assert caught.value.code


def test_reads(client: Invoist, household: bool) -> None:
    if household:
        summary = client.bills.summary()
        assert summary.unpaid >= 0
        assert isinstance(client.bills.list(limit=5), list)
        client.bills.stats()
        assert isinstance(client.held_emails.list(), list)
    else:
        assert client.get_usage().total_calls >= 0
        assert isinstance(client.list_documents(limit=5), list)
        assert isinstance(client.list_categories(), list)
        client.get_stats()


def test_a_missing_id_is_not_found(client: Invoist, household: bool) -> None:
    fetch = client.bills.get if household else client.get_document
    with pytest.raises(InvoistError) as caught:
        fetch(MISSING_ID)
    assert caught.value.is_not_found
    assert caught.value.request_id


async def test_async_reads(aclient: AsyncInvoist, household: bool) -> None:
    if household:
        assert (await aclient.bills.summary()).days > 0
    else:
        assert (await aclient.get_usage()).total_documents >= 0
