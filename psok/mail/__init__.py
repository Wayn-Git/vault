"""Mail, read directly from Gmail rather than through the connector.

See `psok.mail.gmail` for why this does not go through `google-gmail`.
"""

from psok.mail.gmail import (
    MailAccount,
    MailUnavailable,
    accounts,
    labels,
    modify_labels,
    reply,
    thread,
    threads,
)

__all__ = [
    "MailAccount",
    "MailUnavailable",
    "accounts",
    "labels",
    "modify_labels",
    "reply",
    "thread",
    "threads",
]
