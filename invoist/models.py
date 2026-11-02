"""Every type the client returns.

Most are generated from the API's OpenAPI document (``invoist/_generated``).
The few defined here are response envelopes the spec writes inline, and a
test checks them against the spec so they cannot fall behind it.

All models keep fields the API adds after this release (read them with
``model.model_extra``) and accept enum values it adds as plain strings.
Money is integer minor units (``total_cents``), never a float.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ._generated.models import (
    BatchResultItem,
    Bill,
    BillChainMember,
    BillChainMemberWarning,
    BillDetail,
    BillDetailChain,
    BillKind,
    BillLetter,
    BillRecord,
    BillRelated,
    BillsDue,
    BillsStats,
    BillsStatsSender,
    BillsStatsTopSender,
    BillsStatsTotal,
    BillsStatsTrendItem,
    BillsSummary,
    Category,
    CustomValue,
    Discovery,
    Document,
    DocumentApproval,
    DocumentListItem,
    DocumentSource,
    DocumentStatus,
    ErrorDetail,
    Extraction,
    ExtractionJob,
    ExtractionStatus,
    FraudIndicator,
    HeldEmail,
    HeldEmailFile,
    InvoistModel,
    LineItem,
    Quality,
    RegionBox,
    ReviewQueueItem,
    ReviewQueueListItem,
    ReviewReason,
    ReviewStatus,
    StatsOverview,
    Usage,
    UsageByDayItem,
    WebhookEndpoint,
    WebhookEndpointWithSecret,
)

__all__ = [
    "BatchResult",
    "BatchResultItem",
    "Bill",
    "BillChainMember",
    "BillChainMemberWarning",
    "BillDetail",
    "BillDetailChain",
    "BillKind",
    "BillLetter",
    "BillRecord",
    "BillRelated",
    "BillsDue",
    "BillsStats",
    "BillsStatsSender",
    "BillsStatsTopSender",
    "BillsStatsTotal",
    "BillsStatsTrendItem",
    "BillsSummary",
    "Category",
    "CustomValue",
    "Discovery",
    "Document",
    "DocumentApproval",
    "DocumentDetail",
    "DocumentListItem",
    "DocumentSource",
    "DocumentStatus",
    "ErrorDetail",
    "ExtractAndWaitResult",
    "ExtractResult",
    "Extraction",
    "ExtractionJob",
    "ExtractionStatus",
    "FileDownload",
    "FraudIndicator",
    "HeldEmail",
    "HeldEmailFile",
    "InvoistModel",
    "LineItem",
    "Quality",
    "RegionBox",
    "ReviewQueueItem",
    "ReviewQueueListItem",
    "ReviewReason",
    "ReviewStatus",
    "StatsOverview",
    "Usage",
    "UsageByDayItem",
    "WebhookEndpoint",
    "WebhookEndpointList",
    "WebhookEndpointWithSecret",
    "WebhookEvent",
]


class ExtractResult(InvoistModel):
    """What ``extract`` returns: the stored document and its extraction.

    A new upload answers with ``extraction.status == "pending"``; reading
    happens in the background. ``duplicate`` is true when these exact bytes
    were already extracted in this workspace: the existing document comes
    back and nothing new is created or billed.
    """

    document: Document
    extraction: Extraction | None = None
    duplicate: bool


class BatchResult(InvoistModel):
    """What ``extract_batch`` returns: one outcome per file, in order."""

    results: list[BatchResultItem]
    accepted: int
    """How many files were accepted and queued."""
    rejected: int
    """How many files failed validation or could not be stored."""


class DocumentDetail(InvoistModel):
    """A document with its extraction and review items."""

    document: Document
    extraction: Extraction | None = None
    """Absent until an extraction exists; ``status`` is ``pending`` until reading finishes."""
    extraction_job: ExtractionJob | None = None
    """How the background run producing the extraction is going."""
    review_queue: list[ReviewQueueItem]
    period_locked: bool | None = None
    """Whether the document's month is closed, so it can be read but not edited."""


class ExtractAndWaitResult(InvoistModel):
    """What ``extract_and_wait`` returns: the document and its finished extraction."""

    document: Document
    extraction: Extraction
    """Finished: ``status`` is ``done`` or ``failed``, never ``pending``."""


class WebhookEndpointList(InvoistModel):
    """What ``list_webhook_endpoints`` returns."""

    endpoints: list[WebhookEndpoint]
    known_events: list[str]
    """Every event type an endpoint can subscribe to."""


class WebhookEvent(InvoistModel):
    """A verified webhook event, as returned by :func:`invoist.webhooks.verify_webhook`."""

    id: str
    """The event's id. The same event delivered twice keeps its id, so use it to deduplicate."""
    type: str
    """The event type, e.g. ``extraction.completed``; see :class:`invoist.webhooks.EventType`."""
    created_at: datetime
    data: dict[str, Any]
    """The event's payload, which depends on ``type``."""


@dataclass(frozen=True, slots=True)
class FileDownload:
    """A downloaded original file: its bytes exactly as uploaded, and their type."""

    content: bytes
    content_type: str
    """The stored content type, e.g. ``application/pdf``."""
    filename: str | None = None
    """The file's name, when the response named one."""

    def __len__(self) -> int:
        return len(self.content)

    def __repr__(self) -> str:
        return (
            f"FileDownload(content_type={self.content_type!r}, filename={self.filename!r}, "
            f"size={len(self.content)})"
        )
