# This file is generated from the Invoist OpenAPI document by
# scripts/generate.py (datamodel-code-generator). Do not edit it by hand:
# change the spec, run the script, and commit the result.

"""Request and response models for the Invoist API, generated from its OpenAPI document."""

from __future__ import annotations

from datetime import date as date_aliased
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict, Field, PlainValidator
from typing_extensions import TypeAliasType


def _open_enum(value: Any) -> str:
    """Accept any string for an enum field, so new API values never break parsing."""
    if not isinstance(value, str):
        raise ValueError("expected a string")
    return value


OPEN_ENUM = PlainValidator(_open_enum, json_schema_input_type=str)
"""Marks an enum field as open: known values are typed, unknown ones still parse."""


class InvoistModel(_BaseModel):
    """Base of every model: unknown fields the API adds are kept, never an error."""

    model_config = ConfigDict(
        extra="allow",
    )


class ErrorDetail(InvoistModel):
    code: Annotated[
        str,
        Field(
            examples=[
                "invalid_body",
                "unauthenticated",
                "forbidden",
                "not_found",
                "upload_too_large",
            ]
        ),
    ]
    """
    A stable machine-readable identifier. Branch on this, not the message.
    """
    message: str
    """
    Human-readable explanation. Wording may change; do not parse it.
    """


class Error(InvoistModel):
    error: ErrorDetail


DocumentStatus = TypeAliasType(
    "DocumentStatus", Annotated[Literal["pending", "processing", "done", "failed"], OPEN_ENUM]
)


DocumentSource = TypeAliasType(
    "DocumentSource",
    Annotated[Literal["api", "dashboard", "email", "storage", "sandbox"], OPEN_ENUM],
)
"""
How the document arrived.
"""


class DocumentApproval(InvoistModel):
    """
    Sign-off state. Separate from `status`, which tracks extraction: this is a person's judgement, that is the machine's progress. Always "draft" unless the workspace has an approval mode switched on.
    """

    state: Annotated[Literal["draft", "ready", "approved", "changes_requested"], OPEN_ENUM]
    submitted_by: str | None = None
    submitted_by_name: str | None = None
    """
    Captured at the time, so it survives the person leaving.
    """
    submitted_at: datetime | None = None
    approved_by: str | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None


class DocumentListItem(InvoistModel):
    """
    A document plus a flat summary of its latest extraction.
    """

    id: str
    source: DocumentSource
    original_filename: str
    content_type: str
    byte_size: int
    status: DocumentStatus
    vendor_name: str | None = None
    invoice_number: str | None = None
    reference_number: str | None = None
    total_cents: int | None = None
    base_currency: str | None = None
    """
    The workspace's reporting currency, when one is configured. Null when conversion is off, or when this invoice's currency had no published rate for its date. The invoice's own currency and total_cents remain authoritative.
    """
    base_total_cents: int | None = None
    """
    total_cents converted into base_currency, for reporting only.
    """
    fx_rate: str | None = None
    """
    Reporting-currency units per one unit of the invoice currency, as a decimal string so the exact stored value round-trips.
    """
    fx_rate_date: date_aliased | None = None
    """
    The date of the published rates used, which is the invoice date or the most recent publication before it.
    """
    fx_source: str | None = None
    """
    Who published the rate, e.g. "ecb".
    """
    currency: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    pending_review: int
    """
    Count of unresolved review items.
    """
    flagged: bool
    """
    True when pending_review is above zero.
    """
    created_at: datetime
    updated_at: datetime


ExtractionStatus = TypeAliasType(
    "ExtractionStatus", Annotated[Literal["pending", "done", "failed"], OPEN_ENUM]
)


class ExtractionJob(InvoistModel):
    """
    Progress of the background run that produces an extraction. Reading a document is queued work, so this reports how that work is going: whether it is waiting, running, finished, or has given up.
    """

    status: Annotated[Literal["queued", "running", "succeeded", "failed"], OPEN_ENUM]
    """
    `queued` is waiting for a worker, which includes waiting out the backoff between attempts. `failed` means every attempt was used or the failure was one that retrying cannot fix.
    """
    attempt_count: int
    """
    Attempts made so far, including the one currently running.
    """
    max_attempts: int
    """
    Attempts allowed before the run is abandoned. Deliberately small, since every attempt is a real extraction.
    """
    retryable: bool
    """
    True when the run has stopped and can be started again. Retrying is a fresh run and is billed as one.
    """
    next_attempt_at: datetime | None = None
    """
    When the next attempt is due. Present only while a retry is genuinely still coming, so its absence on a queued job means the job has not started yet rather than that it is stalled.
    """


class LineItem(InvoistModel):
    description: str
    quantity: float
    unit: str | None = None
    sku: str | None = None
    unit_price_cents: int | None = None
    """
    Unit price in whole cents. Null when the price is not an exact number of cents, which happens on utility and fuel invoices priced per unit below one cent. Read unit_price_micros for those.
    """
    unit_price_micros: int | None = None
    """
    Unit price in millionths of one currency unit, exact for sub-cent prices. 8.72 cents per kWh is 87200. Set whenever a unit price is printed, including when unit_price_cents is also set.
    """
    line_total_cents: int | None = None
    tax_cents: int | None = None
    discount_cents: int | None = None


class RegionBox(InvoistModel):
    """
    A rectangle on the page image, normalized 0 to 1, origin top-left.
    """

    x: float
    y: float
    w: float
    h: float


class WebhookEndpoint(InvoistModel):
    id: str
    url: str
    description: str
    events: list[str]
    """
    Subscribed event types; ["*"] means everything.
    """
    enabled: bool
    consecutive_failures: int
    last_delivery_at: datetime | None = None
    last_status: int | None = None
    auto_disabled_at: datetime | None = None
    """
    Set when repeated failures paused this endpoint automatically.
    """
    created_at: datetime


class WebhookEndpointWithSecret(WebhookEndpoint):
    secret: str
    """
    HMAC key for X-Invoist-Signature. Returned only here and on rotation, never readable again.
    """


class Discovery(InvoistModel):
    page: int | None = None
    """
    1-based page this pin belongs to. Absent or 0 means page 1, which is how discoveries extracted before multi-page support are stored.
    """
    x: float
    """
    Normalized 0 to 1 across that page's image.
    """
    y: float
    """
    Normalized 0 to 1 down that page's image.
    """
    label: str


class CustomValue(InvoistModel):
    key: str
    label: str
    value: str | None = None
    confidence: float | None = None


class Quality(InvoistModel):
    readability: float
    """
    0 to 1, where 1 is crisp and fully legible.
    """
    issues: list[
        Annotated[
            Literal["blurry", "cropped", "low_contrast", "rotated", "handwritten", "partial"],
            OPEN_ENUM,
        ]
    ]


ReviewStatus = TypeAliasType(
    "ReviewStatus", Annotated[Literal["pending", "resolved", "dismissed"], OPEN_ENUM]
)


ReviewReason = TypeAliasType(
    "ReviewReason",
    Annotated[
        Literal[
            "low_confidence",
            "total_mismatch",
            "poor_quality",
            "duplicate",
            "unusual_vendor",
            "bank_details_changed",
            "amount_anomaly",
            "amount_over_limit",
            "missing_po_number",
        ],
        OPEN_ENUM,
    ],
)
"""
Why the item was flagged.
"""


class ReviewQueueItem(InvoistModel):
    id: str
    document_id: str
    extraction_id: str
    reason: ReviewReason
    status: ReviewStatus
    created_at: datetime
    resolved_at: datetime | None = None


class ReviewQueueListItem(InvoistModel):
    """
    A review item plus a summary of the document it belongs to.
    """

    id: str
    document_id: str
    extraction_id: str
    reason: ReviewReason
    status: ReviewStatus
    created_at: datetime
    resolved_at: datetime | None = None
    original_filename: str
    content_type: str
    document_status: DocumentStatus
    vendor_name: str | None = None
    invoice_number: str | None = None
    reference_number: str | None = None
    total_cents: int | None = None
    currency: str | None = None


class Category(InvoistModel):
    id: str
    name: str
    is_default: bool
    """
    Part of the set seeded with the workspace.
    """
    created_at: datetime


class UsageByDayItem(InvoistModel):
    day: date_aliased | None = None
    calls: int | None = None
    documents: int | None = None


class Usage(InvoistModel):
    period_start: datetime
    total_calls: int
    total_documents: int
    total_cost_cents: int
    by_day: list[UsageByDayItem]


class StatsOverview(InvoistModel):
    documents_this_month: int
    documents_total: int
    pending_review_count: int
    period_start: datetime
    plan: Annotated[Literal["starter", "growth", "scale"], OPEN_ENUM]
    documents_included: int | None = None
    """
    Monthly allowance for the plan. Absent for plans without a fixed allowance.
    """


class BillRecord(InvoistModel):
    """
    The household's own record on a bill.
    """

    paid_at: datetime | None
    """
    When it was marked paid.
    """
    paid_by: str | None
    """
    Who marked it paid.
    """
    assigned_to: str | None
    """
    Who is meant to pay it.
    """


BillKind = TypeAliasType(
    "BillKind",
    Annotated[
        Literal[
            "invoice",
            "reminder",
            "debt_collection",
            "credit_note",
            "receipt",
            "payment_confirmation",
        ],
        OPEN_ENUM,
    ]
    | None,
)
"""
What a document is. Null is an ordinary invoice.
"""


class BillRelated(InvoistModel):
    """
    The bill a letter or receipt is linked to, and how.
    """

    document_id: str | None
    link: str
    """
    `matched` or `confirmed` when linked, `suggested` when Invoist only thinks so, empty when unlinked.
    """


class BillLetter(InvoistModel):
    """
    The newest reminder or collection letter about a bill, which says what is owed now.
    """

    document_id: str
    kind: Annotated[Literal["reminder", "debt_collection"], OPEN_ENUM]
    total_cents: int | None = None
    currency: str | None = None
    due_date: date_aliased | None = None
    added_cents: int | None = None
    """
    Fees and interest added on top of the original.
    """
    count: int
    """
    How many letters came for this bill.
    """


class Bill(DocumentListItem):
    """
    One bill in a household's list.
    """

    due_date: date_aliased | None = None
    bill: BillRecord
    kind: BillKind
    related: BillRelated
    letter: BillLetter | None
    proof_document_id: str | None = None
    """
    A receipt or payment confirmation found for this bill.
    """
    logo: str | None
    """
    The domain whose logo stands for the sender, when Invoist shows one: never on a bill with an open warning, never for a domain that imitates another the household knows.
    """


class BillChainMemberWarning(InvoistModel):
    id: str
    reason: ReviewReason


class BillChainMember(InvoistModel):
    """
    One document of a bill's chain (the bill and its letters).
    """

    document_id: str
    kind: BillKind
    link: str | None = None
    status: DocumentStatus
    original_filename: str
    vendor_name: str | None = None
    invoice_number: str | None = None
    reference_number: str | None = None
    currency: str | None = None
    total_cents: int | None = None
    date: date_aliased
    due_date: date_aliased | None = None
    paid_at: datetime | None = None
    fees_cents: int | None = None
    interest_cents: int | None = None
    original_amount_cents: int | None = None
    original_creditor: str | None = None
    vendor_iban: str | None = None
    vendor_bic: str | None = None
    payment_account: str | None = None
    warnings: list[BillChainMemberWarning] | None = None


class BillDetailChain(InvoistModel):
    """
    The bill and its letters, when it has any.
    """

    root_id: str
    members: list[BillChainMember]


class BillsDue(InvoistModel):
    currency: str
    count: int
    total_cents: int


class BillsSummary(InvoistModel):
    unpaid: int
    """
    Bills not marked paid.
    """
    overdue: int
    """
    Unpaid bills past their due date.
    """
    due_soon: list[BillsDue]
    """
    Per currency, the unpaid bills due by today plus `days`, overdue ones included.
    """
    days: int
    today: date_aliased


class BillsStatsTotal(InvoistModel):
    currency: str
    count: int
    paid_count: int
    total_cents: int
    paid_cents: int


class BillsStatsTrendItem(InvoistModel):
    month: str
    currency: str
    count: int
    total_cents: int


class BillsStatsTopSender(InvoistModel):
    name: str
    currency: str | None = None
    count: int
    total_cents: int | None = None
    logo: str | None = None


class BillsStatsSender(InvoistModel):
    name: str
    count: int


class BillsStats(InvoistModel):
    month: str
    """
    `YYYY-MM`
    """
    totals: list[BillsStatsTotal]
    trend: list[BillsStatsTrendItem]
    """
    Up to twelve months ending with `month`, per currency; months with no bills are absent.
    """
    top_senders: list[BillsStatsTopSender]
    senders: list[BillsStatsSender]
    """
    Everyone who has sent the household bills, most bills first.
    """


class HeldEmailFile(InvoistModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int


class HeldEmail(InvoistModel):
    """
    An email forwarded to the household that waits for approval.
    """

    id: str
    from_email: str
    subject: str
    status: str
    reason: str | None = None
    attachments: int | None = None
    documents: int | None = None
    created_at: datetime
    hold_reason: (
        Annotated[Literal["new_sender", "unverified_sender", "no_plan", "quota_used"], OPEN_ENUM]
        | None
    ) = None
    """
    Why it waits. The sender reasons wait for a person; the plan reasons clear by themselves.
    """
    held_until: datetime | None = None
    """
    When it is deleted if nobody acts.
    """
    resolved_at: datetime | None = None
    bounced: bool | None = None
    forwarded_by: str | None = None
    """
    The household member whose forwarding rule passed it on.
    """
    original_from: str | None = None
    """
    Who wrote it first, when forwarded by hand.
    """
    lookalike_of: str | None = None
    """
    A known domain this sender's imitates.
    """
    sender: Annotated[Literal["verified", "failed", "unknown"], OPEN_ENUM]
    """
    What the mail server found about the From address.
    """
    files: list[HeldEmailFile]
    logo: str | None = None


class BatchResultItem(InvoistModel):
    """
    One file's outcome from POST /v1/extract/batch. A rejected file carries `error` and omits the document fields; an accepted one carries the document fields and omits `error`.
    """

    filename: str
    document_id: str | None = None
    extraction_id: str | None = None
    status: DocumentStatus | None = None
    duplicate: bool | None = None
    """
    True when this file's bytes were already extracted in this workspace.
    """
    error: ErrorDetail | None = None
    """
    Present only when this file was rejected.
    """


class Document(InvoistModel):
    id: str
    source: DocumentSource
    original_filename: str
    content_type: Annotated[str, Field(examples=["application/pdf"])]
    byte_size: int
    status: DocumentStatus
    approval: DocumentApproval | None = None
    created_at: datetime
    updated_at: datetime


class FraudIndicator(InvoistModel):
    signal: str
    """
    Model-reported signals are one of `math_mismatch`,
    `font_inconsistency`, `implausible_dates`, `round_total`,
    `vendor_details_off`, `possible_edit`. Engine-reported signals
    add `vendor_bank_change` and `vendor_amount_anomaly`.

    """
    severity: Annotated[Literal["low", "medium", "high"], OPEN_ENUM]
    description: str
    source: Annotated[Literal["model", "engine"], OPEN_ENUM]
    """
    `model` when read off the page; `engine` when derived from workspace history.
    """
    page: int | None = None
    """
    1-based page number when the finding has a location.
    """
    box: RegionBox | None = None


class Extraction(InvoistModel):
    id: str
    document_id: str
    engine: Annotated[str, Field(examples=["invoist-extraction-v1"])]
    status: ExtractionStatus
    document_kind: (
        Annotated[
            Literal[
                "invoice",
                "reminder",
                "debt_collection",
                "credit_note",
                "receipt",
                "payment_confirmation",
            ],
            OPEN_ENUM,
        ]
        | None
    ) = None
    """
    What the document is. Null when the reader could not tell, and on documents read before this field existed; treat null as an ordinary invoice.
    """
    invoice_number: str | None = None
    invoice_date: date_aliased | None = None
    """
    Absent when not printed on the document.
    """
    due_date: date_aliased | None = None
    """
    Absent when not printed on the document.
    """
    po_number: str | None = None
    reference_number: str | None = None
    """
    The payment or bank reference, distinct from the invoice number.
    """
    vendor_name: str | None = None
    vendor_address: str | None = None
    customer_name: str | None = None
    currency: str | None = None
    """
    ISO 4217 code, e.g. EUR.
    """
    subtotal_cents: int | None = None
    tax_cents: int | None = None
    total_cents: int | None = None
    base_currency: str | None = None
    """
    The workspace's reporting currency, when one is configured. Null when conversion is off, or when this invoice's currency had no published rate for its date.
    """
    base_total_cents: int | None = None
    """
    total_cents converted into base_currency, for reporting only.
    """
    fx_rate: str | None = None
    """
    Reporting-currency units per one unit of the invoice currency, as a decimal string.
    """
    fx_rate_date: date_aliased | None = None
    """
    The date of the published rates used.
    """
    fx_source: str | None = None
    """
    Who published the rate, e.g. "ecb".
    """
    confidence: dict[str, Any] | None = None
    """
    Per-field confidence between 0 and 1, keyed by field name.
    """
    line_items: list[LineItem] | None = None
    details: dict[str, Any] | None = None
    """
    Optional commercial extras (payment terms, tax IDs, IBAN, shipping). On a reminder, collection letter or credit note it also carries original_invoice_number, original_invoice_date, original_creditor, original_amount_cents, fees_cents and interest_cents: the earlier invoice it is about and what was added.
    """
    fraud_indicators: list[FraudIndicator] | None = None
    """
    Heuristic observations worth a second look. Never a determination
    that a document is fraudulent.

    """
    file_metadata: dict[str, Any] | None = None
    """
    Facts read from the file's own EXIF or PDF metadata, never inferred.
    """
    custom: list[CustomValue] | None = None
    """
    Workspace-declared custom fields, filled during extraction.
    """
    discoveries: list[Discovery] | None = None
    """
    Coordinate-pinned findings on the first page image.
    """
    quality: Quality | None = None
    category_id: str | None = None
    category_source: Annotated[Literal["model", "user", "memory"], OPEN_ENUM] | None = None
    """
    Who chose the category.
    """
    auto_approved: bool | None = None
    """
    True when this skipped the review queue because the vendor had a clean track record.
    """
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    edited_at: datetime | None = None
    """
    When a person last corrected these fields by hand. Absent if the extraction has never been edited, so its presence is how you tell a human-reviewed record from a purely automatic one.
    """


class BillDetail(InvoistModel):
    """
    One bill with everything read from it.
    """

    document: Document
    extraction: Extraction | None = None
    extraction_job: ExtractionJob | None = None
    review_queue: list[ReviewQueueItem]
    """
    The bill's warnings; open ones have status `pending`.
    """
    period_locked: bool | None = None
    bill: BillRecord
    related: BillRelated | None = None
    chain: BillDetailChain | None = None
    """
    The bill and its letters, when it has any.
    """
    suggested_bill: BillChainMember | None = None
    suggested_letters: list[BillChainMember] | None = None
    logo: str | None = None
