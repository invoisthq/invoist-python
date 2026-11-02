"""The one error type every Invoist call raises."""

from __future__ import annotations

__all__ = ["InvoistError"]


class InvoistError(Exception):
    """Raised for every failure: an API error, a network problem, a timeout.

    Branch on :attr:`code` or the ``is_*`` properties, never on
    :attr:`message`, whose wording may change.

    Attributes:
        status: The HTTP status, or ``0`` when no response arrived.
        code: A stable machine-readable code. It comes from the API's
            ``{"error": {"code", "message"}}`` envelope, or is one the SDK
            sets itself: ``unexpected_response`` (the body was not that
            envelope), ``network_error``, ``timeout``, ``extraction_timeout``,
            ``invalid_signature`` and ``signature_too_old``.
        message: A human-readable explanation.
        request_id: The ``X-Request-Id`` response header. Quote it when you
            contact support.
        body: The raw response body, when there was one.
    """

    status: int
    code: str
    message: str
    request_id: str | None
    body: str | None

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: str = "unexpected_response",
        request_id: str | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.request_id = request_id
        self.body = body

    @property
    def is_auth_error(self) -> bool:
        """The key is missing, malformed or revoked (401)."""
        return self.status == 401

    @property
    def is_permission_error(self) -> bool:
        """The key is valid but may not do this (403), e.g. a missing scope."""
        return self.status == 403

    @property
    def is_not_found(self) -> bool:
        """No such resource (404)."""
        return self.status == 404

    @property
    def is_rate_limited(self) -> bool:
        """Too many requests (429). The client already retried it."""
        return self.status == 429

    @property
    def is_retryable(self) -> bool:
        """Worth trying again later: no response, 429, or a server error."""
        return self.status == 0 or self.status == 429 or self.status >= 500

    def __str__(self) -> str:
        where = f"status {self.status}" if self.status else "no response"
        detail = f"{where}, code {self.code}"
        if self.request_id:
            detail += f", request {self.request_id}"
        return f"{self.message} ({detail})"

    def __repr__(self) -> str:
        return (
            f"InvoistError(status={self.status!r}, code={self.code!r}, "
            f"message={self.message!r}, request_id={self.request_id!r})"
        )

    def __reduce__(self) -> tuple[object, ...]:
        # Keyword-only fields survive pickling (multiprocessing, task queues).
        return (_rebuild, (self.message, self.status, self.code, self.request_id, self.body))


def _rebuild(
    message: str, status: int, code: str, request_id: str | None, body: str | None
) -> InvoistError:
    return InvoistError(message, status=status, code=code, request_id=request_id, body=body)
