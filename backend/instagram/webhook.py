"""Reading what Instagram actually sent.

Three routes reach the library, and they are not equally good. Stating the
difference here rather than discovering it later is the point of this module:

**mention** -- someone commented `@your.account` on a post. The payload carries a
`media_id`, and the Graph API turns that into the real permalink *and* the full
caption. This is the route worth using, and it is how savetolist.com works.

**dm_reel / dm_share** -- someone sent the reel into a direct message. The
payload carries a title and an expiring `lookaside.fbsbx.com` asset that needs
the access token. It does **not** carry a permalink and it does **not** carry a
caption. A reel saved this way has nothing to search on until its audio has been
transcribed, and that has to be said on the item rather than left to be noticed.

**dm_link** -- someone pasted an instagram.com link as message text. A real
permalink, and nothing else: Instagram blocks reading the page behind it.

A fourth outcome is not a route at all. Meta delivers some shares as an
unsupported-message notification carrying nothing recoverable; those are recorded
and ignored, never turned into an item made up from the little that arrived.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

ROUTES = ("mention", "dm_reel", "dm_share", "dm_link", "unsupported")

#: A post, a reel or a TV permalink. `share/` is Instagram's short form and
#: resolves to one of the others.
_PERMALINK = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv|share)/[A-Za-z0-9_\-]+/?",
    re.IGNORECASE,
)


class Attachment(BaseModel):
    type: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    mid: str | None = None
    text: str | None = None
    is_echo: bool = False
    is_unsupported: bool = False
    attachments: list[Attachment] = Field(default_factory=list)


class Party(BaseModel):
    id: str | None = None


class Messaging(BaseModel):
    sender: Party = Field(default_factory=Party)
    recipient: Party = Field(default_factory=Party)
    timestamp: int | None = None
    message: Message | None = None


class Change(BaseModel):
    field: str | None = None
    value: dict[str, Any] = Field(default_factory=dict)


class Entry(BaseModel):
    id: str | None = None
    time: int | None = None
    messaging: list[Messaging] = Field(default_factory=list)
    changes: list[Change] = Field(default_factory=list)


class WebhookBody(BaseModel):
    object: str | None = None
    entry: list[Entry] = Field(default_factory=list)


@dataclass(frozen=True)
class Inbound:
    """One thing Instagram told us about, normalised."""

    delivery_key: str
    route: str
    sender_id: str | None
    received_at: int | None
    raw: dict[str, Any]

    @property
    def is_mention(self) -> bool:
        return self.route == "mention"


def permalink_in(text: str | None) -> str | None:
    match = _PERMALINK.search(text or "")
    return match.group(0) if match else None


#: Anything past this is milliseconds, not seconds. Meta sends `entry.time` in
#: seconds and `messaging[].timestamp` in milliseconds, in the same delivery, and
#: nothing in the payload says so. Comparing the second against a seconds clock
#: makes every direct message look decades old, which the freshness window then
#: silently drops -- a feature that appears to do nothing at all.
_MILLISECONDS_FROM = 100_000_000_000


def _seconds(value: int | None) -> int | None:
    if not value:
        return None
    return int(value // 1000) if value > _MILLISECONDS_FROM else int(value)


def _fallback_key(payload: dict[str, Any]) -> str:
    """A key for a delivery that named nothing we can key on.

    Hashing the payload means Meta's retry of the same unidentifiable delivery
    still collides with the first, which is the entire job of the key.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "raw:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _from_messaging(item: Messaging, entry_time: int | None) -> Inbound | None:
    message = item.message
    if message is None or message.is_echo:
        # An echo is our own reply coming back. Ingesting it would save the
        # confirmation we just sent.
        return None

    sender = item.sender.id
    key = f"dm:{message.mid}" if message.mid else _fallback_key(item.model_dump())
    raw = item.model_dump()

    for attachment in message.attachments:
        kind = (attachment.type or "").lower()
        if kind in ("ig_reel", "reel", "video"):
            return Inbound(key, "dm_reel", sender, _seconds(item.timestamp) or entry_time, raw)
        if kind in ("share", "image", "story_mention"):
            return Inbound(key, "dm_share", sender, _seconds(item.timestamp) or entry_time, raw)

    if permalink_in(message.text):
        return Inbound(key, "dm_link", sender, _seconds(item.timestamp) or entry_time, raw)

    if message.is_unsupported or message.attachments:
        return Inbound(key, "unsupported", sender, _seconds(item.timestamp) or entry_time, raw)

    # Plain text with no link. Someone talking to the account, not saving.
    return None


def _from_change(change: Change, entry_time: int | None) -> Inbound | None:
    if (change.field or "").lower() not in ("mentions", "mention"):
        return None
    value = change.value or {}
    media_id = value.get("media_id") or value.get("media", {}).get("id")
    if not media_id:
        return None
    comment_id = value.get("comment_id") or ""
    return Inbound(
        delivery_key=f"mention:{media_id}:{comment_id}",
        route="mention",
        sender_id=str(value.get("from", {}).get("id") or "") or None,
        received_at=entry_time,
        raw=value,
    )


def parse(body: WebhookBody) -> list[Inbound]:
    """Everything worth acting on in one delivery.

    Meta batches: one POST can carry several entries, and one entry can carry
    both `messaging` and `changes`. Walking only the first of each is how a
    delivery quietly loses half of itself.
    """
    found: list[Inbound] = []
    for entry in body.entry:
        for item in entry.messaging:
            inbound = _from_messaging(item, entry.time)
            if inbound is not None:
                found.append(inbound)
        for change in entry.changes:
            inbound = _from_change(change, entry.time)
            if inbound is not None:
                found.append(inbound)
    return found


def reel_details(raw: dict[str, Any]) -> dict[str, Any]:
    """Title, asset URL and video id out of a direct-message attachment."""
    message = raw.get("message") or {}
    for attachment in message.get("attachments") or []:
        payload = attachment.get("payload") or {}
        if payload.get("url") or payload.get("title"):
            return {
                "title": (payload.get("title") or "").strip(),
                "url": payload.get("url"),
                "video_id": str(payload.get("video_id") or "") or None,
                "type": attachment.get("type"),
            }
    return {"title": "", "url": None, "video_id": None, "type": None}
