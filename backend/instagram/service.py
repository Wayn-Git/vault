"""Turning one delivery into one library item.

The order in `process` is load-bearing. **The library row is created as early as
it can be**, from whatever is already known, and everything slow is added to it
afterwards -- a download, ffmpeg, a transcription, a model call, a reply. Each of
those is wrapped so a failure writes a sentence into `capture_note` and carries
on. The item survives all of them failing, which is the library's existing rule
rather than a new one: a capture that goes wrong still logs the fact that you
saved something.

What the three routes actually yield, since they are not equal and the item has
to say which one it came from:

* **mention** -- the permalink and the full caption. The route worth using.
* **dm_reel / dm_share** -- a title and an expiring asset. No permalink, no
  caption. Only a transcript gives it anything to search on.
* **dm_link** -- a permalink and nothing else; Instagram will not serve the page.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.config import InstagramSettings, load_instagram
from backend.instagram import signature
from backend.instagram.client import InstagramClient, InstagramError, unwrap_mentioned_media
from backend.instagram.store import InstagramEventStore
from backend.instagram.webhook import permalink_in, reel_details
from backend.library.service import LibraryService
from backend.library.store import media_path, thumbnail_path
from backend.media.audio import MediaError, extract_audio, ffmpeg_missing, probe_duration
from backend.media.download import DownloadError, fetch_to
from backend.runtime.transcribe import (
    TranscriptionUnavailable,
    resolve_transcriber,
    transcribe,
    unavailable_reason,
)

log = logging.getLogger(__name__)

MAX_THUMBNAIL_BYTES = 5 * 1024 * 1024
#: Per sender, per hour. A person saving reels does perhaps twenty; this is well
#: clear of that and well short of somebody filling a database.
MAX_PER_SENDER_HOURLY = 30

NO_CAPTION_NOTE = (
    "sent as a direct message, which carries the video and a title but no caption"
    " and no link back to the reel"
)


class IngestService:
    def __init__(
        self,
        *,
        library: LibraryService | None = None,
        client: InstagramClient | None = None,
        store: InstagramEventStore | None = None,
        settings: InstagramSettings | None = None,
        transcriber=None,
        downloader=None,
        extractor=None,
        prober=None,
    ):
        # Everything injected, so a test never reaches Instagram, a CDN, ffmpeg
        # or a transcription API.
        self._library = library
        self._client = client
        self.store = store or InstagramEventStore()
        self._settings = settings
        self._transcribe = transcriber or transcribe
        # Whether anything can turn speech into text is normally a question about
        # the machine's configuration. When a transcriber is handed in, the answer
        # is yes by construction, and asking the global resolver instead would
        # gate on a fact about a different object.
        self._can_transcribe = (lambda: True) if transcriber else (
            lambda: resolve_transcriber() is not None
        )
        self._download = downloader or fetch_to
        self._extract_audio = extractor or extract_audio
        self._probe = prober or probe_duration

    @property
    def settings(self) -> InstagramSettings:
        return self._settings if self._settings is not None else load_instagram()

    @property
    def library(self) -> LibraryService:
        if self._library is None:
            self._library = LibraryService()
        return self._library

    @property
    def client(self) -> InstagramClient:
        if self._client is None:
            self._client = InstagramClient()
        return self._client

    # -- who may write to the library ------------------------------------

    def refuse_reason(self, route: str, sender_id: str | None) -> str | None:
        """Why this delivery is not being acted on, or None."""
        settings = self.settings
        if route == "mention" and settings.mentions_from == "anyone":
            return None
        if not settings.allow_senders:
            return (
                "nobody is on the allowlist yet, so nothing is being saved."
                " Allow this sender in Settings to start."
            )
        if not settings.allows(sender_id):
            return f"{sender_id or 'this sender'} is not on the allowlist"
        if sender_id and self.store.accepted_since(sender_id) >= MAX_PER_SENDER_HOURLY:
            return f"{sender_id} has sent more than {MAX_PER_SENDER_HOURLY} things this hour"
        return None

    # -- the work --------------------------------------------------------

    async def process(self, event) -> str:
        """Act on one claimed event. Returns the terminal status."""
        route = event["route"]
        sender = event["sender_id"]
        payload: dict[str, Any] = json.loads(event["payload"])

        refusal = self.refuse_reason(route, sender)
        if refusal:
            self.store.finish(event["id"], status="ignored", note=refusal)
            return "ignored"

        if route == "unsupported":
            self.store.finish(
                event["id"],
                status="ignored",
                note="Instagram sent this as an unsupported message, which carries"
                " nothing to save. Comment-mention the reel instead -- that route"
                " carries the caption and the link.",
            )
            return "ignored"

        try:
            details = await self._resolve(route, payload)
        except InstagramError as exc:
            self.store.finish(event["id"], status="failed", note=str(exc))
            return "failed"

        if not details:
            self.store.finish(
                event["id"], status="ignored", note="this delivery named nothing to save"
            )
            return "ignored"

        captured = await self.library.capture_media(**details["item"])
        item_id = captured.item["id"]
        if captured.already_logged:
            # Still worth answering. Someone re-sending a reel wants to know
            # where it went, and silence reads as the thing having been dropped.
            await self._maybe_reply(sender, captured.item["title"], already=True)
            self.store.finish(
                event["id"],
                status="done",
                note="already in the library",
                library_item_id=item_id,
            )
            return "done"

        notes: list[str] = [details["item"].get("capture_note") or ""]
        notes.append(await self._add_thumbnail(item_id, details.get("thumbnail_url")))
        notes.append(await self._add_transcript(item_id, details.get("media_url")))

        if self.settings.enrich:
            try:
                await self.library.enrich(item_id)
            except Exception as exc:  # enrichment is the last thing, never the item
                log.warning("enrichment failed for library item %s: %s", item_id, exc)

        note = " · ".join(n for n in notes if n) or None
        if note:
            self.library.store.update(item_id, capture_note=note)

        await self._maybe_reply(sender, captured.item["title"])
        self.store.finish(event["id"], status="done", library_item_id=item_id)
        return "done"

    async def _resolve(self, route: str, payload: dict) -> dict | None:
        if route == "mention":
            return await self._resolve_mention(payload)
        if route in ("dm_reel", "dm_share"):
            return self._resolve_dm(payload)
        if route == "dm_link":
            return self._resolve_link(payload)
        return None

    async def _resolve_mention(self, payload: dict) -> dict | None:
        media_id = str(payload.get("media_id") or "")
        owner = self.settings.owner_ig_id
        if not media_id or not owner:
            return None
        media = unwrap_mentioned_media(await self.client.mentioned_media(owner, media_id))
        caption = (media.get("caption") or "").strip()
        permalink = media.get("permalink")
        return {
            "item": {
                "title": _title_from(caption) or f"an Instagram post ({media_id})",
                "kind": "video" if media.get("media_type") == "VIDEO" else "article",
                "url": permalink,
                "author": media.get("username"),
                "site": "Instagram",
                "source_ref": f"instagram:media:{media_id}",
                "text": caption,
                "text_source": "caption" if caption else "none",
                "capture_note": "" if caption else "this post has no caption",
            },
            "thumbnail_url": media.get("thumbnail_url") or media.get("media_url"),
            "media_url": media.get("media_url") if media.get("media_type") == "VIDEO" else None,
        }

    def _resolve_dm(self, payload: dict) -> dict | None:
        reel = reel_details(payload)
        if not (reel["url"] or reel["title"]):
            return None
        video_id = reel["video_id"] or ""
        return {
            "item": {
                "title": reel["title"] or "a reel sent to you",
                "kind": "video",
                # Deliberately not the lookaside URL. That is an expiring asset,
                # not a link anyone could follow later, and putting it in `url`
                # would put a dead address in front of the user as if it worked.
                "url": None,
                "site": "Instagram",
                "source_ref": f"instagram:reel:{video_id}" if video_id else None,
                "text": "",
                "text_source": "none",
                "capture_note": NO_CAPTION_NOTE,
            },
            "thumbnail_url": None,
            "media_url": reel["url"],
        }

    def _resolve_link(self, payload: dict) -> dict | None:
        text = ((payload.get("message") or {}).get("text")) or ""
        permalink = permalink_in(text)
        if not permalink:
            return None
        return {
            "item": {
                "title": "an Instagram link you sent",
                "kind": "video",
                "url": permalink,
                "site": "Instagram",
                "source_ref": f"instagram:link:{permalink.rstrip('/').rsplit('/', 1)[-1]}",
                "text": "",
                "text_source": "none",
                "capture_note": "saved from a link. Instagram does not serve the"
                " caption behind it, so this is findable by its address.",
            },
            "thumbnail_url": None,
            "media_url": None,
        }

    async def _add_thumbnail(self, item_id: int, url: str | None) -> str:
        if not url:
            return ""
        target = thumbnail_path(item_id)
        try:
            await self._download(
                url, target, token=signature.access_token(), max_bytes=MAX_THUMBNAIL_BYTES
            )
        except DownloadError as exc:
            return f"the thumbnail could not be fetched: {exc}"
        self.library.store.update(item_id, thumbnail_path=str(target))
        return ""

    async def _add_transcript(self, item_id: int, media_url: str | None) -> str:
        """Download, extract audio, transcribe, and put the words on the item.

        Every gate is checked before the step it protects: no transcriber means
        the video is never downloaded at all, because there would be nothing to
        do with it.
        """
        if not media_url:
            return ""
        settings = self.settings

        missing = ffmpeg_missing()
        if missing:
            return missing
        if not self._can_transcribe():
            return unavailable_reason()

        video = media_path(item_id, ".mp4")
        try:
            await self._download(
                media_url,
                video,
                token=signature.access_token(),
                max_bytes=settings.max_video_mb * 1024 * 1024,
            )
        except DownloadError as exc:
            return f"the video could not be fetched, so there is no transcript: {exc}"

        audio: Path | None = None
        duration: float | None = None
        try:
            duration = await self._probe(video)
            if duration and duration > settings.max_duration_seconds:
                return (
                    f"this is {int(duration // 60)} minutes long, past the"
                    f" {settings.max_duration_seconds // 60}-minute limit for transcription"
                )
            audio = await self._extract_audio(video, media_path(item_id, ".audio"))
            result = await self._transcribe(audio)
        except MediaError as exc:
            return str(exc)
        except TranscriptionUnavailable as exc:
            return str(exc)
        except Exception as exc:
            log.warning("transcription failed for library item %s: %s", item_id, exc)
            return f"the transcription did not finish: {exc}"
        finally:
            # The audio is scratch either way; the video is kept only if asked
            # for. Twenty reels a day at fifteen megabytes is nine gigabytes a
            # year, and the transcript is the part that was worth having.
            if audio is not None:
                audio.unlink(missing_ok=True)
            if settings.keep_video:
                self.library.store.update(item_id, media_path=str(video))
            else:
                video.unlink(missing_ok=True)
            if duration is not None:
                self.library.store.update(item_id, duration_seconds=int(duration))

        if not result.text:
            return "the audio carried no speech, so there is no transcript"
        await self.library.replace_text(item_id, result.text, text_source="transcript")
        return ""

    async def _maybe_reply(
        self, sender_id: str | None, title: str, *, already: bool = False
    ) -> None:
        if not (self.settings.reply_on_save and sender_id):
            return
        message = f"Already saved: {title}" if already else f"Saved: {title}"
        try:
            await self.client.send_text(sender_id, message)
        except InstagramError as exc:
            # A confirmation that could not be sent is not a capture that failed.
            log.info("could not reply to %s: %s", sender_id, exc)


def _title_from(caption: str) -> str:
    """A title out of a caption: its first line, trimmed to something readable."""
    first = (caption or "").strip().splitlines()[0] if caption.strip() else ""
    first = first.strip()
    if len(first) <= 90:
        return first
    return first[:87].rsplit(" ", 1)[0] + "…"

