"""The official Python library for the Invoist API.

::

    from invoist import Invoist

    invoist = Invoist(os.environ["INVOIST_API_KEY"])
    result = invoist.extract_and_wait(Path("invoice.pdf"))
    print(result.extraction.vendor_name, result.extraction.total_cents)

:class:`Invoist` is the synchronous client and :class:`AsyncInvoist` the
asynchronous one; both raise :class:`InvoistError` for every failure. The
response types live in :mod:`invoist.models`, and webhook verification in
:mod:`invoist.webhooks`.
"""

from . import models, webhooks
from ._async_client import AsyncBills, AsyncHeldEmails, AsyncInvoist
from ._base import DEFAULT_BASE_URL, USER_AGENT, FileInput
from ._client import Bills, HeldEmails, Invoist
from ._version import __version__
from .errors import InvoistError
from .models import FileDownload
from .webhooks import EventType, verify_webhook

__all__ = [
    "DEFAULT_BASE_URL",
    "USER_AGENT",
    "AsyncBills",
    "AsyncHeldEmails",
    "AsyncInvoist",
    "Bills",
    "EventType",
    "FileDownload",
    "FileInput",
    "HeldEmails",
    "Invoist",
    "InvoistError",
    "__version__",
    "models",
    "verify_webhook",
    "webhooks",
]
