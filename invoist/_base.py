"""What the sync and async clients share: configuration, requests, errors, retries, files."""

from __future__ import annotations

import json
import mimetypes
import os
import platform
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email.message import Message
from pathlib import Path
from typing import IO, Any, TypeAlias, TypeVar
from urllib.parse import quote

import httpx
import pydantic

from ._version import __version__
from .errors import InvoistError
from .models import FileDownload

DEFAULT_BASE_URL = "https://api.invoi.st"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_WAIT_TIMEOUT = 120.0

BASE_DELAY = 0.5
"""The first retry's wait, in seconds; it doubles each attempt."""
MAX_DELAY = 8.0
"""The longest the backoff schedule waits between attempts, in seconds."""
JITTER = 0.2
"""Each backoff wait is randomised by this fraction either way."""
MAX_RETRY_AFTER = 60
"""A ``Retry-After`` longer than this many seconds fails the call instead of waiting."""

USER_AGENT = f"invoist-python/{__version__} (python {platform.python_version()})"

FileContent: TypeAlias = bytes | bytearray | memoryview | IO[bytes] | os.PathLike[str]
FileInput: TypeAlias = FileContent | tuple[str, FileContent] | tuple[str, FileContent, str | None]
"""A file to upload, in any of these forms:

* ``bytes`` (or ``bytearray``/``memoryview``);
* a :class:`pathlib.Path` (or any ``os.PathLike``), read from disk;
* a binary file object, such as ``open("invoice.pdf", "rb")``;
* a tuple ``(filename, content)`` or ``(filename, content, content_type)``,
  where content is any of the above, to choose the name Invoist sees.

The content type is taken from the tuple, else guessed from the filename,
else from the file's first bytes (PDF, PNG, JPEG).
"""

ModelT = TypeVar("ModelT", bound=pydantic.BaseModel)

_RETRY_AFTER = re.compile(r"\s*(\d+)\s*")


@dataclass(frozen=True, slots=True)
class Upload:
    """A file read into memory, so a retry can send it again."""

    filename: str
    content: bytes
    content_type: str


@dataclass(slots=True)
class Request:
    """One API call, described independently of the client that sends it."""

    method: str
    path: str
    params: dict[str, str] | None = None
    json: Any = None
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None
    headers: dict[str, str] = field(default_factory=dict)


class BaseClient:
    """Configuration and request building shared by :class:`Invoist` and :class:`AsyncInvoist`."""

    api_key: str
    base_url: str
    timeout: float
    max_retries: int

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError(
                "An Invoist API key is required: pass api_key=..., for example "
                'Invoist(os.environ["INVOIST_API_KEY"]).'
            )
        if max_retries < 0:
            raise ValueError("max_retries can't be negative.")
        if timeout <= 0:
            raise ValueError("timeout must be a positive number of seconds.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    def __repr__(self) -> str:
        # Never print the key.
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    def _headers(self, request: Request) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            **request.headers,
        }

    def _url(self, path: str) -> str:
        return self.base_url + path


# -- building requests -------------------------------------------------------


def path(template: str, *ids: str) -> str:
    """Fill ``{}`` placeholders with ids, each percent-encoded as one path segment."""
    for value in ids:
        if not isinstance(value, str) or not value:
            raise ValueError("An id must be a non-empty string.")
    return template.format(*(quote(value, safe="") for value in ids))


def query(**params: object) -> dict[str, str] | None:
    """Encode query parameters the way the API reads them.

    ``None`` and ``""`` are left out (an omitted filter and an empty one mean
    different things), booleans become ``true``/``false``, and dates become
    ``YYYY-MM-DD`` (a timezone-aware datetime in local time, the calendar
    date the caller sees).
    """
    out: dict[str, str] = {}
    for key, value in params.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        elif isinstance(value, datetime):
            out[key] = _local(value).date().isoformat()
        elif isinstance(value, date):
            out[key] = value.isoformat()
        else:
            out[key] = str(value)
    return out or None


def format_month(value: str | date | None) -> str | None:
    """Format a month as ``YYYY-MM``; a date or datetime gives its month in local time."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, datetime):
        value = _local(value)
    return f"{value.year:04d}-{value.month:02d}"


def _local(value: datetime) -> datetime:
    """A datetime in local time; a naive one is taken to be local already."""
    return value.astimezone() if value.tzinfo is not None else value


# -- files -------------------------------------------------------------------


def _sniff(content: bytes) -> str | None:
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


_EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}


def _read(content: FileContent) -> tuple[bytes, str | None]:
    """Read file content into bytes, with the name it carries, if any."""
    if isinstance(content, bytes | bytearray | memoryview):
        return bytes(content), None
    if isinstance(content, os.PathLike):
        file_path = Path(content)
        return file_path.read_bytes(), file_path.name
    if hasattr(content, "read"):
        data = content.read()
        if not isinstance(data, bytes):
            raise TypeError("Open the file in binary mode ('rb'): it returned text.")
        name = getattr(content, "name", None)
        return data, Path(name).name if isinstance(name, str) and name else None
    raise TypeError(
        f"Can't upload a {type(content).__name__}: pass bytes, a pathlib.Path, "
        "a binary file object, or a (filename, content[, content_type]) tuple."
    )


def to_upload(file: FileInput) -> Upload:
    """Normalise any accepted file form into an in-memory :class:`Upload`."""
    filename: str | None
    content_type: str | None = None
    if isinstance(file, tuple):
        if len(file) == 2:
            filename, raw = file
        elif len(file) == 3:
            filename, raw, content_type = file
        else:
            raise TypeError("A file tuple is (filename, content) or (filename, content, type).")
        content, _ = _read(raw)
    else:
        content, filename = _read(file)
    sniffed = _sniff(content)
    if not content_type and filename:
        content_type = mimetypes.guess_type(filename)[0]
    content_type = content_type or sniffed or "application/octet-stream"
    if not filename:
        filename = "upload" + _EXTENSIONS.get(content_type, "")
    return Upload(filename, content, content_type)


def multipart(field_name: str, uploads: list[Upload]) -> list[tuple[str, tuple[str, bytes, str]]]:
    """The ``files`` argument httpx takes; it chooses the multipart boundary itself."""
    return [(field_name, (u.filename, u.content, u.content_type)) for u in uploads]


# -- responses ---------------------------------------------------------------


def retry_delay(attempt: int, retry_after: str | None) -> float | None:
    """Seconds to wait before retry number ``attempt + 1``, or ``None`` not to retry.

    A ``Retry-After`` header with whole seconds wins, since the server knows
    best, unless it asks for more than a minute: then the call fails at once
    rather than hang. Any other ``Retry-After`` (an HTTP date) is ignored.
    Otherwise ``0.5s * 2**attempt`` with +-20% jitter, capped at 8s.
    """
    if retry_after is not None:
        match = _RETRY_AFTER.fullmatch(retry_after)
        if match:
            seconds = int(match.group(1))
            return float(seconds) if seconds <= MAX_RETRY_AFTER else None
    return backoff(attempt)


def backoff(attempt: int) -> float:
    """The backoff schedule: ``0.5s * 2**attempt`` with +-20% jitter, capped at 8s."""
    delay = BASE_DELAY * 2.0**attempt
    jittered = delay * random.uniform(1 - JITTER, 1 + JITTER)  # noqa: S311 - not cryptographic
    return min(jittered, MAX_DELAY)


def error_from_response(response: httpx.Response) -> InvoistError:
    """Turn a failed response into :class:`InvoistError`, reading its error envelope."""
    status = response.status_code
    request_id = response.headers.get("X-Request-Id")
    text = response.text if response.content else None
    fallback = f"Request failed with status {status}"
    envelope: Any = None
    if text:
        try:
            envelope = json.loads(text)
        except ValueError:
            envelope = None
    detail = envelope.get("error") if isinstance(envelope, dict) else None
    if isinstance(detail, dict):
        code = detail.get("code")
        message = detail.get("message")
        return InvoistError(
            message if isinstance(message, str) and message else fallback,
            status=status,
            code=code if isinstance(code, str) and code else "unexpected_response",
            request_id=request_id,
            body=text,
        )
    return InvoistError(
        fallback, status=status, code="unexpected_response", request_id=request_id, body=text
    )


def network_error(exc: httpx.RequestError) -> InvoistError:
    """An error for a request that never got a response."""
    if isinstance(exc, httpx.TimeoutException):
        return InvoistError(
            f"The request timed out: {exc or type(exc).__name__}", status=0, code="timeout"
        )
    return InvoistError(
        f"The request failed before a response arrived: {exc or type(exc).__name__}",
        status=0,
        code="network_error",
    )


def _unexpected(response: httpx.Response, reason: str) -> InvoistError:
    return InvoistError(
        f"The API's response could not be read: {reason}",
        status=response.status_code,
        code="unexpected_response",
        request_id=response.headers.get("X-Request-Id"),
        body=response.text if response.content else None,
    )


def json_body(response: httpx.Response) -> Any:
    """The decoded JSON of a successful response, or ``None`` when it has no body."""
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise _unexpected(response, "it is not JSON") from exc


def parse(model: type[ModelT], response: httpx.Response, key: str | None = None) -> ModelT:
    """Validate a response (or one key of it) as ``model``."""
    data = json_body(response)
    if key is not None:
        data = data.get(key) if isinstance(data, dict) else None
    try:
        return model.model_validate(data)
    except pydantic.ValidationError as exc:
        raise _unexpected(response, str(exc)) from exc


def parse_list(model: type[ModelT], response: httpx.Response, key: str) -> list[ModelT]:
    """Validate the list under ``key`` of a response, item by item, as ``model``."""
    data = json_body(response)
    items = data.get(key) if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise _unexpected(response, f"expected a list under {key!r}")
    try:
        return [model.model_validate(item) for item in items]
    except pydantic.ValidationError as exc:
        raise _unexpected(response, str(exc)) from exc


def download(response: httpx.Response) -> FileDownload:
    """A binary response as :class:`FileDownload`."""
    filename: str | None = None
    disposition = response.headers.get("Content-Disposition")
    if disposition:
        header = Message()
        header["Content-Disposition"] = disposition
        filename = header.get_filename()
    return FileDownload(
        content=response.content,
        content_type=response.headers.get("Content-Type", "application/octet-stream"),
        filename=filename,
    )


def extraction_timeout(document_id: str, timeout: float) -> InvoistError:
    """The error ``wait_for_extraction`` raises when its time runs out."""
    return InvoistError(
        f"The extraction of document {document_id} did not finish within {timeout:g}s.",
        status=0,
        code="extraction_timeout",
    )
