"""Turning a delivery into a library item.

Every dependency is injected, so nothing here reaches Instagram, a CDN, ffmpeg or
a transcription API. What is being tested is the decision layer: which route
yields what, what happens when each slow step fails, and -- the one that matters
most -- that a reel with no words is never described as if it had some.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.config import allow_sender, save_instagram
from backend.instagram.service import IngestService
from backend.instagram.store import InstagramEventStore
from backend.instagram.webhook import Inbound
from backend.library.service import LibraryService
from backend.library.store import LibraryStore
from backend.media.download import DownloadError
from backend.retrieval.indexer import Indexer
from backend.runtime.transcribe import Transcript, TranscriptionUnavailable

CAPTION = (
    "Pour over ratios that actually matter. Grind size dominates brew ratio below 1:16. "
    "I use a Comandante C40 and a Hario V60 02. Start at 1:15 and adjust the grind. "
) * 4
SPEECH = (
    "so the thing nobody tells you about pour over is that grind size matters more than "
    "the ratio i use a comandante c40 and start at one to fifteen and adjust the grind "
) * 5


class FakeEmbedder:
    provider, model = "ollama", "nomic-embed-text"

    async def embed(self, texts):
        return [[1.0, 0.2, 0.5] for _ in texts]

    async def embed_one(self, text):
        return [1.0, 0.2, 0.5]


class FakeClient:
    """Graph, without Graph."""

    def __init__(self, media=None):
        self.media = media or {}
        self.sent: list[tuple[str, str]] = []

    async def mentioned_media(self, ig_user_id, media_id):
        return {"mentioned_media": self.media}

    async def send_text(self, recipient_id, text):
        self.sent.append((recipient_id, text))
        return {}


class NeverCalled:
    """A model that fails the test if anything asks it anything."""

    async def complete(self, *args, **kwargs):
        raise AssertionError("nothing may be summarised from text that does not exist")


def enrichment_saying(summary: str):
    class Client:
        async def complete(self, messages, tools=None, params=None):
            from backend.runtime.types import ModelResponse

            return ModelResponse(
                text=json.dumps(
                    {"summary": summary, "tags": ["coffee"], "resources": []}
                )
            )

    return Client()


@pytest.fixture
def ready(db):
    save_instagram({"enabled": True, "owner_ig_id": "17841400000000000"})
    allow_sender("555")


def service(*, client=None, transcriber=None, downloader=None, library=None):
    async def no_download(url, destination, **kwargs):
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b"video-bytes")
        return destination

    async def fake_extract(source, destination, **kwargs):
        target = Path(str(destination)).with_suffix(".ogg")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"audio-bytes")
        return target

    async def fake_probe(path, **kwargs):
        return 42.0

    return IngestService(
        library=library or LibraryService(indexer=Indexer(embedder=FakeEmbedder())),
        client=client or FakeClient(),
        store=InstagramEventStore(),
        transcriber=transcriber,
        downloader=downloader or no_download,
        extractor=fake_extract,
        prober=fake_probe,
    )


def queue(route: str, payload: dict, *, sender: str = "555") -> object:
    store = InstagramEventStore()
    store.enqueue(Inbound(f"key:{route}:{id(payload)}", route, sender, None, payload))
    return store.claim_next()


DM_PAYLOAD = {
    "sender": {"id": "555"},
    "message": {
        "mid": "m_abc",
        "attachments": [
            {
                "type": "ig_reel",
                "payload": {
                    "title": "pour over ratios",
                    "url": "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=1",
                    "video_id": "9",
                },
            }
        ],
    },
}


async def test_a_mention_saves_the_permalink_and_the_caption(ready):
    """The route worth using. A mention yields both of the things a direct
    message does not, which is the whole reason both are supported.

    Mutation check: read the caption from the webhook payload instead of Graph.
    """
    client = FakeClient(
        {
            "caption": CAPTION,
            "permalink": "https://www.instagram.com/reel/ABC123/",
            "media_type": "VIDEO",
            "username": "somebody",
        }
    )
    svc = service(client=client)
    save_instagram({"enrich": False})

    status = await svc.process(queue("mention", {"media_id": "178954", "comment_id": "c1"}))

    item = LibraryStore().list()[0]
    assert status == "done"
    assert item["url"] == "https://www.instagram.com/reel/ABC123/"
    assert item["text_source"] == "caption"
    assert item["source_ref"] == "instagram:media:178954"
    assert "Comandante" in Path(item["text_path"]).read_text()


async def test_a_direct_message_reel_has_no_link_and_says_so(ready):
    """A lookaside asset is an expiring file, not an address anyone can follow.
    Putting it in `url` would show the user a dead link as though it worked.

    Mutation check: store the lookaside URL as the item's url.
    """
    save_instagram({"enrich": False})
    status = await service().process(queue("dm_reel", DM_PAYLOAD))

    item = LibraryStore().list()[0]
    assert status == "done"
    assert item["url"] is None
    assert item["source_ref"] == "instagram:reel:9"
    assert "no caption" in item["capture_note"]


async def test_a_reel_with_no_words_is_never_summarised(ready):
    """The governing test.

    A direct-message share carries a video and a title. Asking a model what it is
    "about" would be inventing from a filename, and the invention would sit on
    the page looking exactly like a real summary. The guard is structural, so
    this asserts the model is not merely ignored but never called at all.

    Mutation check: drop the text_source check from enrich._refusal.
    """
    svc = service(
        transcriber=_raises(TranscriptionUnavailable("no provider here transcribes audio"))
    )
    await svc.process(queue("dm_reel", DM_PAYLOAD))

    item = LibraryStore().list()[0]
    await LibraryService(indexer=Indexer(embedder=FakeEmbedder())).enrich(
        item["id"], client=NeverCalled()
    )

    saved = LibraryStore().get(item["id"])
    assert saved["summary"] is None
    assert saved["text_source"] == "none"
    assert "nothing to summarise from" in saved["enrichment_note"]


async def test_a_transcript_gives_the_reel_something_to_search_on(ready):
    """The whole point of transcribing: without it a direct-message reel is
    findable by its title and nothing else."""
    save_instagram({"enrich": False})
    svc = service(transcriber=_returns(Transcript(SPEECH, "groq", "whisper-large-v3-turbo")))

    await svc.process(queue("dm_reel", DM_PAYLOAD))

    item = LibraryStore().list()[0]
    assert item["text_source"] == "transcript"
    assert "grind size" in Path(item["text_path"]).read_text()

    library = LibraryService(indexer=Indexer(embedder=FakeEmbedder()))
    assert [hit["title"] for hit in await library.search("grind size")] == [item["title"]]


async def test_a_transcript_can_then_be_summarised(ready):
    """Once there are words, the summary is describing something real."""
    save_instagram({"enrich": False})
    svc = service(transcriber=_returns(Transcript(SPEECH, "groq", "whisper-large-v3-turbo")))
    await svc.process(queue("dm_reel", DM_PAYLOAD))

    item = LibraryStore().list()[0]
    library = LibraryService(indexer=Indexer(embedder=FakeEmbedder()))
    enriched = await library.enrich(
        item["id"], client=enrichment_saying("A reel about pour-over grind size.")
    )

    assert enriched["summary"] == "A reel about pour-over grind size."
    assert enriched["tags"] == ["coffee"]
    body = Path(enriched["text_path"]).read_text()
    assert "## Transcript" in body, "a reader can tell which words were actually said"
    assert "written by" in body, "and which were not"


async def test_an_expired_asset_still_logs_the_reel(ready):
    """The lookaside URL is gone within days. Losing the video must not lose the
    fact that the reel was saved.

    Mutation check: raise out of _add_transcript instead of returning a note.
    """
    save_instagram({"enrich": False})

    async def gone(url, destination, **kwargs):
        raise DownloadError("Instagram returned HTTP 403 for this file")

    # A transcriber has to exist for the download to be attempted at all -- with
    # nothing able to use the video, PSOK does not fetch it in the first place.
    svc = service(downloader=gone, transcriber=_returns(Transcript(SPEECH, "groq", "whisper")))
    status = await svc.process(queue("dm_reel", DM_PAYLOAD))

    item = LibraryStore().list()[0]
    assert status == "done"
    assert "403" in item["capture_note"]


async def test_a_sender_who_is_not_allowed_saves_nothing(ready):
    """Anyone can message a public professional account.

    Mutation check: default the allowlist to everyone.
    """
    event = queue("dm_reel", DM_PAYLOAD, sender="999")
    status = await service().process(event)

    assert status == "ignored"
    assert LibraryStore().list() == []
    assert "not on the allowlist" in InstagramEventStore().get(event["id"])["note"]


async def test_an_unsupported_delivery_saves_nothing_and_says_why(ready):
    """Meta passes some shares through carrying nothing recoverable. An item
    invented from that would be an item about nothing."""
    event = queue("unsupported", {"sender": {"id": "555"}, "message": {"mid": "m_x"}})
    status = await service().process(event)

    assert status == "ignored"
    assert LibraryStore().list() == []
    assert "Comment-mention" in InstagramEventStore().get(event["id"])["note"]


async def test_the_same_reel_twice_is_one_item(ready):
    """Two different deliveries of one reel -- a retry that outlived the delivery
    key, or the user sending it again."""
    save_instagram({"enrich": False})
    svc = service()
    await svc.process(queue("dm_reel", DM_PAYLOAD))
    second = queue("dm_reel", dict(DM_PAYLOAD))
    status = await svc.process(second)

    assert status == "done"
    assert len(LibraryStore().list()) == 1
    assert InstagramEventStore().get(second["id"])["note"] == "already in the library"


async def test_the_video_is_discarded_but_the_transcript_is_kept(ready):
    """Twenty reels a day at fifteen megabytes is nine gigabytes a year, and the
    words are the part worth keeping."""
    save_instagram({"enrich": False, "keep_video": False})
    svc = service(transcriber=_returns(Transcript(SPEECH, "groq", "whisper")))
    await svc.process(queue("dm_reel", DM_PAYLOAD))

    item = LibraryStore().list()[0]
    assert item["media_path"] is None
    assert item["duration_seconds"] is None or item["duration_seconds"] >= 0
    assert "grind size" in Path(item["text_path"]).read_text()


async def test_removing_an_item_takes_its_media_with_it(ready):
    """An orphaned mp4 under ~/.psok/library/media with no row pointing at it is
    one nothing will ever clean up.

    Mutation check: unlink only text_path in LibraryService.remove.
    """
    save_instagram({"enrich": False, "keep_video": True})
    svc = service(transcriber=_returns(Transcript(SPEECH, "groq", "whisper")))
    await svc.process(queue("dm_reel", DM_PAYLOAD))

    item = LibraryStore().list()[0]
    video = Path(item["media_path"])
    assert video.exists()

    assert svc.library.remove(item["id"]) is True
    assert not video.exists()
    assert not Path(item["text_path"]).exists()


async def test_a_confirmation_is_only_sent_when_it_was_asked_for(ready):
    """Replying is a write to a social account, so it is opted into."""
    save_instagram({"enrich": False, "reply_on_save": False})
    client = FakeClient()
    await service(client=client).process(queue("dm_reel", DM_PAYLOAD))
    assert client.sent == []

    save_instagram({"reply_on_save": True})
    await service(client=client).process(queue("dm_reel", dict(DM_PAYLOAD)))
    assert client.sent and client.sent[0][0] == "555"


def _returns(value):
    async def call(path, **kwargs):
        return value

    return call


def _raises(error):
    async def call(path, **kwargs):
        raise error

    return call
