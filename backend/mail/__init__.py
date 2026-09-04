"""Mail, read directly from Gmail rather than through the connector.

See `backend.mail.gmail` for why this does not go through `google-gmail`.
"""

from backend.mail.gmail import (
    MailAccount,
    MailUnavailable,
    accounts,
    labels,
    modify_labels,
    reply,
    thread,
    threads,
    unread_count,
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
    "unread_count",
]
