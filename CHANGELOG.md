# Changelog

All notable changes to this package are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Every Invoist SDK shares one
version number.

## 1.0.1 - 2026-11-02

- No change to the API or to how the library behaves.
- The repository now holds its own copy of the API's OpenAPI spec in
  `testdata/openapi.yaml`. The models are generated from it, and the tests
  that compare the models with the spec run in this repository too.
- Test data uses made-up company names.

## [1.0.0] - 2026-11-01

The first stable release, implementing the cross-language Invoist SDK
specification.

### Added

- `Invoist` (sync) and `AsyncInvoist` (async) clients on httpx, with an
  injectable `http_client`, context-manager support and a
  `User-Agent: invoist-python/<version> (python <version>)` header.
- Every API method: `extract`, `extract_batch`, `list_documents`,
  `get_document`, `get_document_file`, `wait_for_extraction`,
  `extract_and_wait`, `list_review_queue`, `resolve_review_item`,
  `list_categories`, `get_usage`, `get_stats`, `list_webhook_endpoints`,
  `create_webhook_endpoint` and `delete_webhook_endpoint`.
- Households (Invoist Personal): `client.bills.list/get/get_file/summary/stats/mark_paid/mark_unpaid`
  and `client.held_emails.list`.
- Typed Pydantic v2 models generated from the API's OpenAPI document, in
  `invoist.models`. Fields and enum values the API adds later are kept rather
  than rejected.
- Uploads from bytes, a `pathlib.Path`, a binary file object or a
  `(filename, content[, content_type])` tuple, buffered so retries resend them.
- Downloads as `FileDownload` (bytes, content type and filename).
- Automatic retries of network failures, 429 and 5xx, honouring
  `Retry-After` (failing at once when it asks for more than 60 seconds),
  otherwise exponential backoff with jitter capped at 8s.
- `InvoistError` for every failure, with `status`, `code`, `message`,
  `request_id`, `body` and the `is_*` predicates.
- `invoist.webhooks.verify_webhook` with signature rotation, a symmetric
  timestamp window, and `EventType` constants.

### Changed

- Requires Python 3.11 or newer.
- Built on httpx instead of requests, and returns models instead of dicts.
- `resolve_review_queue_item` is now `resolve_review_item`, and
  `verify_webhook` takes `(payload, signature_header, secret)` positionally,
  as the specification names them.

[1.0.0]: https://github.com/invoisthq/invoist-python/releases/tag/v1.0.0
