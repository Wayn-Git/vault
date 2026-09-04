"""Saying what a saved thing is about.

The rule under all of this: a summary describes text that exists. Two of these
tests assert that a model is *never called* rather than called and ignored,
because the guard is meant to be structural -- a prompt can be softened by a
later edit, a return cannot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.library.enrich import (
    MIN_ENRICHABLE_CHARS,
    Enrichment,
    body_of,
    enrich_text,
    parse_enrichment,
    render_markdown,
)
from backend.library.service import LibraryService
from backend.library.store import LibraryStore
from backend.retrieval.indexer import Indexer

TRANSCRIPT = (
    "so the thing nobody tells you about pour over is that grind size matters more than "
    "the ratio i use a comandante c40 and a hario v60 start at one to fifteen "
) * 5


class NeverCalled:
    async def complete(self, *args, **kwargs):
        raise AssertionError("nothing may be summarised from text that does not exist")


class Answers:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    async def complete(self, messages, tools=None, params=None):
        from backend.runtime.types import ModelResponse

        self.calls += 1
        return ModelResponse(text=self.text)


class FakeEmbedder:
    provider, model = "ollama", "nomic-embed-text"

    async def embed(self, texts):
        return [[1.0, 0.3, 0.7] for _ in texts]

    async def embed_one(self, text):
        return [1.0, 0.3, 0.7]


GOOD = json.dumps(
    {
        "summary": "A reel about pour-over coffee, arguing grind size matters more than ratio.",
        "tags": ["coffee", "pour over", "grind size"],
        "resources": [
            {"type": "product", "name": "Comandante C40", "detail": "the grinder used"},
            {"type": "place", "name": "Small Street Espresso", "detail": "in Bristol"},
        ],
    }
)


async def test_text_that_does_not_exist_is_never_sent_to_a_model(db):
    """The governing guard.

    Mutation check: drop the text_source check from `_refusal`.
    """
    result = await enrich_text("", title="a reel", text_source="none", client=NeverCalled())

    assert result.summary is None
    assert "nothing to summarise from" in result.note


async def test_a_line_of_caption_is_left_alone(db):
    """Summarising a sentence produces the sentence again, at the cost of a
    model call and a paragraph that reads like insight."""
    result = await enrich_text(
        "nice coffee", title="a reel", text_source="caption", client=NeverCalled()
    )
    assert result.summary is None
    assert len("nice coffee") < MIN_ENRICHABLE_CHARS


async def test_real_words_are_summarised_tagged_and_mined(db):
    answers = Answers(GOOD)
    result = await enrich_text(
        TRANSCRIPT, title="pour over", text_source="transcript", client=answers
    )

    assert answers.calls == 1
    assert result.summary.startswith("A reel about pour-over")
    assert result.tags == ("coffee", "pour over", "grind size")
    assert [r["name"] for r in result.resources] == ["Comandante C40", "Small Street Espresso"]


async def test_a_reply_in_the_wrong_shape_costs_the_tags_and_not_the_item(db):
    """A model that wanders off the format is a model that answered badly, not a
    capture that failed."""
    result = await enrich_text(
        TRANSCRIPT, title="pour over", text_source="transcript", client=Answers("sorry, what?")
    )
    assert result.summary is None
    assert "expected format" in result.note


def test_an_invented_url_is_dropped(db):
    """Asked for a url when the text has none, a model will supply a plausible
    one. Anything that is not plainly a link goes."""
    parsed = parse_enrichment(
        json.dumps(
            {
                "summary": "x",
                "tags": ["a"],
                "resources": [
                    {"type": "place", "name": "A cafe", "url": "probably somewhere in Bristol"},
                    {"type": "link", "name": "B", "url": "https://example.com/x"},
                ],
            }
        )
    )
    assert [r["url"] for r in parsed.resources] == ["", "https://example.com/x"]


def test_an_unknown_resource_type_becomes_other(db):
    parsed = parse_enrichment(
        json.dumps({"summary": None, "tags": [], "resources": [{"type": "vibe", "name": "N"}]})
    )
    assert parsed.resources[0]["type"] == "other"


def test_a_fenced_reply_is_still_read(db):
    parsed = parse_enrichment(f"```json\n{GOOD}\n```")
    assert parsed and parsed.tags[0] == "coffee"


def test_the_file_says_which_words_were_written_and_which_were_said(db):
    """The honesty rule in the artefact rather than only in a column."""
    body = render_markdown(
        title="pour over",
        body=TRANSCRIPT,
        body_heading="Transcript",
        enrichment=Enrichment(
            summary="A reel about grind size.",
            tags=("coffee",),
            resources=({"type": "product", "name": "C40", "detail": "a grinder", "url": ""},),
            provider="groq",
            model="a-model",
        ),
    )
    assert "## Transcript" in body
    assert "written by groq:a-model" in body
    assert body.index("A reel about grind size.") < body.index("## Transcript")


def test_the_source_text_can_be_read_back_out_of_an_enriched_file(db):
    """Without this, re-enriching would summarise the previous summary.

    Mutation check: return the whole file from `body_of`.
    """
    rendered = render_markdown(
        title="pour over",
        body=TRANSCRIPT,
        body_heading="Transcript",
        enrichment=Enrichment(summary="A summary that must not be summarised.", tags=("x",)),
    )
    recovered, heading = body_of(rendered)

    assert heading == "Transcript"
    assert "A summary that must not be summarised." not in recovered
    assert recovered.startswith("so the thing nobody tells you")


async def test_the_summary_and_tags_end_up_in_the_index(db):
    """What makes "that video about coffee" find a reel whose transcript never
    says the word.

    Mutation check: store the enrichment in columns only.
    """
    library = LibraryService(indexer=Indexer(embedder=FakeEmbedder()))
    captured = await library.capture_media(title="pour over", source_ref="instagram:reel:1")
    await library.replace_text(captured.item["id"], TRANSCRIPT, text_source="transcript")

    await library.enrich(captured.item["id"], client=Answers(GOOD))

    found = await library.search("Small Street Espresso")
    assert [item["title"] for item in found] == ["pour over"]


async def test_re_enriching_does_not_leave_the_item_indexed_twice(db):
    """Chunks dropped and rewritten, not appended -- or one reel comes back as
    two hits.

    Mutation check: skip `_drop_chunks` in `replace_text`.
    """
    from backend.db.connection import get_connection

    library = LibraryService(indexer=Indexer(embedder=FakeEmbedder()))
    captured = await library.capture_media(title="pour over", source_ref="instagram:reel:2")
    await library.replace_text(captured.item["id"], TRANSCRIPT, text_source="transcript")

    await library.enrich(captured.item["id"], client=Answers(GOOD))
    first = get_connection().execute("SELECT count(*) FROM document_chunks").fetchone()[0]
    await library.enrich(captured.item["id"], client=Answers(GOOD))
    second = get_connection().execute("SELECT count(*) FROM document_chunks").fetchone()[0]

    assert first == second and first > 0
    body = Path(LibraryStore().get(captured.item["id"])["text_path"]).read_text()
    assert body.count("## Transcript") == 1


async def test_with_no_model_configured_the_words_survive_and_the_reason_is_given(db):
    """No provider means no summary -- and the transcript is still the item."""
    library = LibraryService(indexer=Indexer(embedder=FakeEmbedder()))
    captured = await library.capture_media(title="pour over", source_ref="instagram:reel:3")
    await library.replace_text(captured.item["id"], TRANSCRIPT, text_source="transcript")

    enriched = await library.enrich(captured.item["id"])

    assert enriched["summary"] is None
    assert enriched["enrichment_note"]
    assert "grind size" in Path(enriched["text_path"]).read_text()


@pytest.mark.parametrize("value", ["", "not json at all", "{", "[]"])
def test_a_reply_that_is_not_an_object_is_no_enrichment(db, value):
    assert parse_enrichment(value) is None
