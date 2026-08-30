"""Gmail, read and written directly, using the account the connector signed in.

**Why not through the `google-gmail` connector.** It works, and PSOK's agent
still uses it -- fifteen tools, and they are the right shape for a model. They
are the wrong shape for a screen. `search_gmail_messages` answers with prose::

    Found 2 messages matching 'in:inbox':

    📧 MESSAGES:
      1. Message ID: 1a04cfc61d6dd362
         Subject: Final Hours: ...

That is written to be read by a language model, and a view built on it would be
a regular expression over someone else's help text -- silently wrong the first
time `workspace-mcp` rewords a heading. The same call to Gmail returns JSON with
the same fields in it.

**Where the credentials come from.** `workspace-mcp` stores the account it
signed in at `~/.google_workspace_mcp/credentials/<address>.json`, holding the
OAuth client, the refresh token and the granted scopes. This module *reads* that
file and never writes it: the file belongs to the connector, refreshing it here
would race the process that owns it, and a corrupted store means signing in
again on a Google app whose consent already expires weekly. Access tokens minted
here live in memory for this process only.

The consequence, stated rather than discovered: **this depends on the connector
having signed in at least once**, and on the shape of that file. Both are
checked on every call, and a failure says which -- `MailUnavailable` names the
missing piece and the screen shows the sentence.

**Scopes** are whatever that sign-in was granted. On the machine this was
written for that is Gmail only: read, modify, send, compose, labels. A call
needing more says so rather than returning a bare 403.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from email.message import EmailMessage
from html import unescape
from pathlib import Path
from typing import Any

from backend.runtime.http import _client

log = logging.getLogger(__name__)

#: Where `workspace-mcp` keeps the accounts it has signed in.
CREDENTIALS_DIR = Path("~/.google_workspace_mcp/credentials").expanduser()

API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"

#: Refresh this long before the stored token actually expires, so a call does
#: not race the boundary and fail on a token that was valid when it was picked.
EXPIRY_MARGIN_SECONDS = 120

#: How many message metadata fetches to have in flight at once. Gmail's list
#: call returns ids only, so a page of twenty threads is twenty more requests;
#: serially that is a page load measured in seconds, and unbounded it is a burst
#: Gmail answers with 429.
FETCH_CONCURRENCY = 10


class MailUnavailable(RuntimeError):
    """Mail cannot be read right now, with a sentence saying why.

    Deliberately one exception with a readable message rather than a family of
    them: every caller does the same thing with it -- shows it to the user --
    and the difference between "nobody has signed in" and "the token was
    refused" is information for a person, not a branch for a program.
    """


@dataclass(frozen=True)
class MailAccount:
    address: str
    scopes: tuple[str, ...]
    #: When this account was signed in, as a unix timestamp. Google expires a
    #: test user's consent seven days after it is given, so this is the number
    #: the interface counts down from.
    signed_in_at: float

    @property
    def can_send(self) -> bool:
        wanted = ("gmail.send", "gmail.modify", "mail.google.com")
        return any(s.endswith(wanted) for s in self.scopes)

    @property
    def can_modify(self) -> bool:
        return any(s.endswith(("gmail.modify", "mail.google.com")) for s in self.scopes)


def accounts() -> list[MailAccount]:
    """Every Google account the connector has signed in, newest first."""
    if not CREDENTIALS_DIR.is_dir():
        return []
    out: list[MailAccount] = []
    for path in CREDENTIALS_DIR.glob("*@*"):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not data.get("refresh_token"):
            continue  # a file written before a sign-in finished
        out.append(
            MailAccount(
                address=path.stem,
                scopes=tuple(data.get("scopes") or ()),
                signed_in_at=path.stat().st_mtime,
            )
        )
    return sorted(out, key=lambda a: a.signed_in_at, reverse=True)


def _preferred() -> MailAccount:
    found = accounts()
    if not found:
        raise MailUnavailable(
            "No Google account is signed in. Open Connectors, choose Gmail, and press Connect."
        )
    return found[0]


# Access tokens, per address. Never written back to the connector's file -- see
# the module docstring. Lost on restart, which costs one refresh call.
_TOKENS: dict[str, tuple[str, float]] = {}


async def _access_token(address: str) -> str:
    cached = _TOKENS.get(address)
    if cached and cached[1] - EXPIRY_MARGIN_SECONDS > time.time():
        return cached[0]

    path = CREDENTIALS_DIR / f"{address}.json"
    try:
        data = json.loads(path.read_text())
    except OSError as exc:
        raise MailUnavailable(
            f"The stored Google account for {address} could not be read. Sign in again"
            " from Connectors."
        ) from exc
    except ValueError as exc:
        raise MailUnavailable(
            f"The stored Google account for {address} is not readable JSON. Sign in again"
            " from Connectors."
        ) from exc

    missing = [k for k in ("refresh_token", "client_id", "client_secret") if not data.get(k)]
    if missing:
        raise MailUnavailable(
            f"The stored Google account for {address} is missing {', '.join(missing)}."
            " Sign in again from Connectors."
        )

    response = await _client(30.0).post(
        data.get("token_uri") or TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": data["refresh_token"],
            "client_id": data["client_id"],
            "client_secret": data["client_secret"],
        },
    )
    if response.status_code != 200:
        # The overwhelmingly common cause, and the one worth naming: Google
        # expires a test user's consent seven days after it is given, and the
        # refresh token dies with the grant rather than with the token.
        raise MailUnavailable(
            f"Google refused to refresh the sign-in for {address}"
            f" ({response.status_code}). A Google app in Testing expires consent after"
            " seven days — sign in again from Connectors."
        )
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise MailUnavailable(f"Google returned no access token for {address}.")
    _TOKENS[address] = (token, time.time() + float(payload.get("expires_in") or 3600))
    return token


async def _call(
    method: str,
    path: str,
    *,
    address: str | None = None,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    account = _preferred() if address is None else MailAccount(address, (), 0.0)
    token = await _access_token(account.address)
    response = await _client(30.0).request(
        method,
        f"{API}{path}",
        params=params,
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code == 401:
        # The cached token was rejected. Drop it and let the next call mint a
        # fresh one rather than failing every request until a restart.
        _TOKENS.pop(account.address, None)
        raise MailUnavailable(
            "Google rejected the sign-in. Open Connectors and sign in to Gmail again."
        )
    if response.status_code == 403:
        raise MailUnavailable(
            "This Google sign-in was not granted the access that needs — add the scope"
            " under Data Access in the Google console and sign in again."
        )
    if response.status_code >= 400:
        raise MailUnavailable(f"Gmail answered {response.status_code}: {response.text[:200]}")
    return response.json() if response.content else {}


def _header(message: dict[str, Any], name: str) -> str:
    for header in (message.get("payload") or {}).get("headers") or []:
        if str(header.get("name", "")).lower() == name.lower():
            return str(header.get("value") or "")
    return ""


def _summarise(message: dict[str, Any]) -> dict[str, Any]:
    label_ids = message.get("labelIds") or []
    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "subject": _header(message, "Subject") or "(no subject)",
        "from": _header(message, "From"),
        "to": _header(message, "To"),
        "date": _header(message, "Date"),
        "snippet": message.get("snippet") or "",
        "unread": "UNREAD" in label_ids,
        "starred": "STARRED" in label_ids,
        "labels": [x for x in label_ids if not x.startswith("CATEGORY_")],
    }


def _decode(data: str | None) -> str:
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", "replace")
    except (ValueError, UnicodeDecodeError):
        return ""


#: Elements whose *contents* are not the message -- a stylesheet is not text
#: that was written to be read.
_DROPPED_ELEMENTS = re.compile(
    r"<(script|style|head|title)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
#: Tags that end a line when they open or close. Everything else just goes.
_LINE_BREAKS = re.compile(r"</?(br|p|div|tr|li|h[1-6]|table|blockquote)\b[^>]*>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_BLANK_RUNS = re.compile(r"\n\s*\n\s*\n+")
#: Zero-width padding. Marketing mail pads its preheader -- the grey line a
#: client shows next to the subject -- with hundreds of joiners and byte-order
#: marks so the preview is not filled by the body. Stripped to text they are
#: invisible characters separated by spaces, and the first screen of the message
#: is fifty lines of nothing.
_INVISIBLE = re.compile(
    r"[\u00ad\u034f\u180e\u200b-\u200f\u2028\u2029\u202a-\u202e"
    r"\u2060-\u206f\u2800\ufeff]"
)
_SPACE_RUNS = re.compile(r"[ \t]{2,}")


def _html_to_text(html: str) -> str:
    """A readable approximation of an HTML mail, as plain text.

    Most mail that matters arrives as `multipart/alternative` and this is never
    reached. Marketing mail often ships HTML only, and the choice for it is
    between showing markup, rendering somebody else's HTML in the app, or
    reducing it. Rendering is the one option not taken: an inbox is the most
    hostile input a personal system has, and a view that executes what arrives
    in it is a different feature with a different threat model.

    Deliberately not a parser. It drops what is not prose, turns the tags that
    end a line into newlines, removes the rest, and unescapes entities.
    """
    text = _DROPPED_ELEMENTS.sub(" ", html)
    text = _LINE_BREAKS.sub("\n", text)
    text = _TAGS.sub("", text)
    text = unescape(text)
    text = _INVISIBLE.sub("", text)
    text = _SPACE_RUNS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_RUNS.sub("\n\n", text).strip()


def _body_of(payload: dict[str, Any]) -> tuple[str, bool]:
    """The readable body, and whether it had to be reduced from HTML.

    Gmail nests parts arbitrarily deep -- an `alternative` inside a `mixed`
    inside a `related` is ordinary -- so this walks rather than checking the
    first two levels.
    """
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime = part.get("mimeType") or ""
        data = (part.get("body") or {}).get("data")
        if mime == "text/plain" and data:
            plain.append(_decode(data))
        elif mime == "text/html" and data:
            html.append(_decode(data))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    if plain:
        return "\n".join(plain).strip(), False
    return _html_to_text("\n".join(html)), bool(html)


async def threads(query: str = "in:inbox", limit: int = 25) -> list[dict[str, Any]]:
    """The newest messages matching a Gmail search, summarised.

    One `messages.list` for the ids, then a metadata fetch per message --
    Gmail has no call that returns a page of headers. The fetches are
    concurrent and bounded; serially a page took as many round trips as it had
    rows.
    """
    listing = await _call(
        "GET", "/messages", params={"q": query, "maxResults": max(1, min(limit, 100))}
    )
    ids = [m.get("id") for m in (listing.get("messages") or []) if m.get("id")]
    if not ids:
        return []

    gate = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def fetch(message_id: str) -> dict[str, Any] | None:
        async with gate:
            try:
                return await _call(
                    "GET",
                    f"/messages/{message_id}",
                    params={
                        "format": "metadata",
                        "metadataHeaders": ["Subject", "From", "To", "Date"],
                    },
                )
            except MailUnavailable:
                # One message that cannot be read must not empty the inbox.
                log.info("could not read message %s", message_id)
                return None

    fetched = await asyncio.gather(*(fetch(i) for i in ids))
    return [_summarise(m) for m in fetched if m]


async def thread(thread_id: str) -> dict[str, Any]:
    """One conversation, with every message's body."""
    data = await _call("GET", f"/threads/{thread_id}", params={"format": "full"})
    messages = data.get("messages") or []
    if not messages:
        raise MailUnavailable("That conversation has no messages, or was deleted.")
    out = []
    for message in messages:
        summary = _summarise(message)
        summary["body"], summary["body_from_html"] = _body_of(message.get("payload") or {})
        out.append(summary)
    return {
        "id": data.get("id") or thread_id,
        "subject": out[0]["subject"],
        "messages": out,
    }


async def labels() -> list[dict[str, Any]]:
    data = await _call("GET", "/labels")
    return [
        {"id": label.get("id"), "name": label.get("name"), "type": label.get("type")}
        for label in (data.get("labels") or [])
    ]


async def modify_labels(
    message_id: str, *, add: list[str] | None = None, remove: list[str] | None = None
) -> dict[str, Any]:
    """Add and remove labels on one message. Archiving is removing `INBOX`."""
    body = {"addLabelIds": add or [], "removeLabelIds": remove or []}
    return _summarise(await _call("POST", f"/messages/{message_id}/modify", body=body))


async def reply(thread_id: str, body: str) -> dict[str, Any]:
    """Reply to the last message in a thread, in the thread.

    The `In-Reply-To` and `References` headers are what make Gmail -- and every
    other mail client -- file the answer under the conversation rather than
    starting a new one beside it. `threadId` alone is not enough: Gmail accepts
    it and still shows the reply as its own thread for the recipient.
    """
    conversation = await thread(thread_id)
    last = conversation["messages"][-1]
    full = await _call("GET", f"/messages/{last['id']}", params={"format": "metadata"})
    message_id_header = _header(full, "Message-ID")
    references = _header(full, "References")

    account = _preferred()
    subject = conversation["subject"]
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    mail = EmailMessage()
    mail["To"] = _header(full, "Reply-To") or last["from"]
    mail["From"] = account.address
    mail["Subject"] = subject
    if message_id_header:
        mail["In-Reply-To"] = message_id_header
        mail["References"] = f"{references} {message_id_header}".strip()
    mail.set_content(body)

    raw = base64.urlsafe_b64encode(mail.as_bytes()).decode()
    sent = await _call("POST", "/messages/send", body={"raw": raw, "threadId": thread_id})
    return {"id": sent.get("id"), "thread_id": sent.get("threadId") or thread_id}
