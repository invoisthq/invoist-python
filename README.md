# Invoist for Python

The official Python library for the [Invoist API](https://invoi.st/docs).
Send Invoist an invoice or receipt and get back what it says: the sender,
the amounts, the dates, every line, and anything worth a second look. A
household can read its bills and mark them paid.

[![PyPI](https://img.shields.io/pypi/v/invoist)](https://pypi.org/project/invoist/)
[![Python](https://img.shields.io/pypi/pyversions/invoist)](https://pypi.org/project/invoist/)

## Install

```sh
pip install invoist
```

Python 3.11 or newer. It depends on [httpx](https://www.python-httpx.org/)
and [Pydantic](https://docs.pydantic.dev/).

## For a business

Read an invoice and wait for the result:

```python
import os
from pathlib import Path
from invoist import Invoist

invoist = Invoist(os.environ["INVOIST_API_KEY"])
result = invoist.extract_and_wait(Path("invoice.pdf"))
print(result.extraction.vendor_name, result.extraction.total_cents, result.extraction.currency)
```

Create a key in Invoist under **Integrations › API**. It is shown once, so
keep it in your secret store, and never ship it in an app or a web page.

## For a household

A household's key (from **Settings › AI assistants** in Invoist Personal)
works with its bills:

```python
import os
from invoist import Invoist

invoist = Invoist(os.environ["INVOIST_API_KEY"])
for bill in invoist.bills.list(paid=False):
    print(bill.vendor_name, bill.total_cents, bill.currency, bill.due_date)
```

## Amounts and dates

Money is always a whole number of minor units: `total_cents=48000` with
`currency="EUR"` is €480.00. There are no floats, so nothing gets rounded on
the way. Dates are `datetime.date`, and times are timezone-aware
`datetime.datetime`.

Every result is a typed [Pydantic](https://docs.pydantic.dev/) model, so
your editor knows every field. When the API adds a field after this release,
it is kept (`model.model_extra`) rather than causing an error, and a new
value in a field like `status` comes through as a plain string.

## Reading documents

`extract` returns as soon as Invoist has the file. Reading it takes a few
seconds and happens in the background.

```python
result = invoist.extract(Path("receipt.jpg"))
document_id = result.document.id
```

A file can be `bytes`, a `pathlib.Path`, an open binary file, or a tuple
`(filename, content)` or `(filename, content, content_type)` when you want
to choose the name Invoist shows.

Then get the result in one of three ways:

- **Wait for it**: `invoist.wait_for_extraction(document_id)` checks every
  2 seconds for up to 2 minutes (both adjustable with `poll_interval` and
  `timeout`). `extract_and_wait` does both steps at once.
- **Get a webhook** when it's done, so nothing waits. See [Webhooks](#webhooks).
- **Check yourself** with `invoist.get_document(document_id)`.

A document Invoist could not read is an answer, not an exception:

```python
extraction = invoist.wait_for_extraction(document_id)
if extraction.status == "failed":
    print("Could not read it:", extraction.error_message)
```

Sending the same file twice is safe: Invoist returns the document it already
has (`result.duplicate` is `True`) and does not bill you again. To retry a
file that may differ slightly, such as one exported again, give it an
`idempotency_key`; a key reused for a different file raises an error with
status 422.

```python
invoist.extract(Path("invoice.pdf"), idempotency_key="order-1042")
```

Up to 10 files in one call, each with its own outcome:

```python
batch = invoist.extract_batch([Path("a.pdf"), Path("b.pdf")])
print(batch.accepted, batch.rejected)
for item in batch.results:
    print(item.filename, item.error.message if item.error else item.document_id)
```

### Everything else for a business

```python
invoist.list_documents(status="done", flagged=True, q="Northwind", limit=50, offset=0)
invoist.get_document(document_id)               # the document, its extraction, its review items
invoist.get_document_file(document_id)          # FileDownload: .content, .content_type, .filename
invoist.list_review_queue(status="pending")     # what Invoist flagged for a person to check
invoist.resolve_review_item(item_id)            # or resolve_review_item(item_id, "dismissed")
invoist.list_categories()
invoist.get_usage()
invoist.get_stats()
invoist.list_webhook_endpoints()                # .endpoints and .known_events
invoist.create_webhook_endpoint("https://example.com/invoist", events=["extraction.completed"])
invoist.delete_webhook_endpoint(endpoint_id)
```

### Everything for a household

```python
from datetime import date

invoist.bills.list(paid=False, month=date(2026, 11, 1), sender="Northwind", q="", limit=50)
invoist.bills.get(bill_id)                      # what was read, warnings, letters, who paid
invoist.bills.get_file(bill_id)                 # FileDownload
invoist.bills.summary()                         # unpaid, overdue, and what falls due soon
invoist.bills.stats(month="2026-10")            # a month's totals and biggest senders
invoist.bills.mark_paid(bill_id)                # needs a key allowed to mark bills paid
invoist.bills.mark_unpaid(bill_id)
invoist.held_emails.list()                      # forwarded emails waiting for approval
```

`month` takes `"YYYY-MM"` or any date in that month, and `today` a date;
a datetime counts by its date in your local time.

## Async

`AsyncInvoist` has the same methods, each awaitable:

```python
import asyncio, os
from invoist import AsyncInvoist

async def main() -> None:
    async with AsyncInvoist(os.environ["INVOIST_API_KEY"]) as invoist:
        summary = await invoist.bills.summary()
        print(summary.unpaid, "unpaid,", summary.overdue, "overdue")

asyncio.run(main())
```

To cancel a call, cancel its task or wrap it in `asyncio.timeout(...)`.

Create one client and reuse it: it keeps connections open. Close it with
`close()` (`aclose()` for async) or use `with` / `async with`.

## Errors

Every failure raises `InvoistError`: an error from the API, no connection,
or a timeout.

```python
from invoist import InvoistError

try:
    invoist.bills.mark_paid(bill_id)
except InvoistError as err:
    if err.is_permission_error:
        print("This key may only read bills.")
    else:
        print(err.status, err.code, err.message, err.request_id)
```

| Field | What it is |
|---|---|
| `status` | The HTTP status, or `0` when no response arrived |
| `code` | A stable code such as `invalid_api_key` or `rate_limited`. Branch on this. |
| `message` | A human explanation. Its wording may change. |
| `request_id` | Quote this when you contact support. |
| `body` | The raw response body |

There are also `is_auth_error` (401), `is_permission_error` (403),
`is_not_found` (404), `is_rate_limited` (429) and `is_retryable` (no
response, 429 or 5xx). With no response, `code` is `network_error` or
`timeout`; when a server returns something that isn't Invoist's error format
(a proxy's error page, say), it is `unexpected_response`.

## Retries and timeouts

The client retries a request up to twice when there was no response, or the
API answered 429 or 5xx. It waits as long as the `Retry-After` header says,
otherwise 0.5s, then 1s, and so on (a little randomised, at most 8s). If
the server asks for a wait longer than a minute, the call fails at once
with that error instead of hanging. It never retries other errors, since sending the same bad request again would
fail again. Uploads are retried too: they are safe to repeat.

```python
invoist = Invoist(
    key,
    timeout=30,       # seconds per attempt (default 60)
    max_retries=0,    # turn retrying off (default 2)
)
```

To use a proxy, custom certificates or your own transport, pass an
`httpx.Client` (or `httpx.AsyncClient`) as `http_client`.

## Webhooks

Invoist signs every webhook with your endpoint's secret.
`verify_webhook` checks the signature and the time it was sent, and returns
the event, or raises `InvoistError` with status 400.

Always pass the **raw request body**, exactly as received. If you parse the
JSON and turn it back into text, the bytes change and the check fails.

With Flask:

```python
import os
from flask import Flask, request
from invoist import InvoistError
from invoist.webhooks import EventType, verify_webhook

app = Flask(__name__)

@app.post("/webhooks/invoist")
def invoist_webhook():
    try:
        event = verify_webhook(
            request.get_data(),                        # the raw body
            request.headers.get("X-Invoist-Signature"),
            os.environ["INVOIST_WEBHOOK_SECRET"],
        )
    except InvoistError:
        return "", 400
    if event.type == EventType.EXTRACTION_COMPLETED:
        print("Read document", event.data["document_id"])
    return "", 204
```

With FastAPI:

```python
import os
from fastapi import FastAPI, HTTPException, Request, Response
from invoist import InvoistError
from invoist.webhooks import EventType, verify_webhook

app = FastAPI()

@app.post("/webhooks/invoist")
async def invoist_webhook(request: Request) -> Response:
    try:
        event = verify_webhook(
            await request.body(),                      # the raw body
            request.headers.get("X-Invoist-Signature"),
            os.environ["INVOIST_WEBHOOK_SECRET"],
        )
    except InvoistError:
        raise HTTPException(status_code=400) from None
    if event.type == EventType.EXTRACTION_COMPLETED:
        print("Read document", event.data["document_id"])
    return Response(status_code=204)
```

The event has `id`, `type`, `created_at` and `data`. The same event can
arrive more than once, so use `event.id` to skip ones you've handled.
`EventType` lists every type: `DOCUMENT_CREATED`, `EXTRACTION_COMPLETED`,
`EXTRACTION_FAILED`, `REVIEW_ITEM_CREATED`, `REVIEW_ITEM_RESOLVED` and
`DOCUMENT_REQUEST_FULFILLED`. The `X-Invoist-Event` and `X-Invoist-Delivery`
headers carry the type and a delivery id.

A signature more than 5 minutes from now, in either direction, is refused
(`signature_too_old`). Change that with `tolerance=` (seconds or a
`timedelta`).

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/generate.py   # rebuild invoist/_generated from openapi.yaml
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy
.venv/bin/pytest                       # INVOIST_API_KEY=... also runs read-only live tests
```

`invoist/_generated/models.py` is generated from the API's OpenAPI document
(`testdata/openapi.yaml`). Don't edit it by hand. `testdata/conformance` holds the test
cases every Invoist SDK must pass.

## Links

- [API documentation](https://invoi.st/docs)
- [Changelog](CHANGELOG.md)
- [Security policy](SECURITY.md)
- [MIT license](LICENSE)
