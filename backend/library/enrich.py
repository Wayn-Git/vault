"""Saying what a saved thing is about -- from what it actually says.

This is the half that makes a library worth having rather than a list of links:
a summary, a handful of tags, and the concrete things the text names that you
could go and find again -- a restaurant, a grinder, a book, a recipe.

**It runs on text that exists, or it does not run.** A direct-message share
carries a video and a title and no caption; asking a model what such a reel is
"about" would be inventing from a filename, and the invention would be
indistinguishable from the real thing on the page. So the guard is structural --
`text_source == 'none'` and short text both return before any client is touched,
and a test asserts the model is never called -- rather than an instruction in a
prompt that a later edit could soften.

Everything written here is stored twice, and neither place would do alone. The
columns are what the interface renders without parsing markdown. The item's own
markdown file is what the indexer reads (ADR-0004), which is what puts the
summary and the tags into search -- so "that video about coffee grind" finds a
reel whose transcript never says the phrase.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime

from backend.runtime import availability
from backend.runtime.failures import FailureKind
from backend.runtime.registry import default_chain, resolve

log = logging.getLogger(__name__)

#: Below this a "summary" is a restatement of the title. A one-line caption is
#: not something to be summarised.
MIN_ENRICHABLE_CHARS = 400
MAX_ENRICH_CHARS = 24_000
ENRICH_TIMEOUT = 90.0
#: Nobody is waiting on this, so it walks further than a turn would. The journal's
#: reasoning, unchanged.
BACKGROUND_FALLBACK_LINKS = 4

MAX_TAGS = 8
MAX_RESOURCES = 12
RESOURCE_TYPES = ("place", "product", "book", "tool", "recipe", "person", "link", "other")

#: Text sources that are somebody's actual words. Anything else cannot be
#: enriched, by definition.
REAL_TEXT_SOURCES = ("caption", "transcript", "page", "notes")

PROMPT = """\
You are describing one thing the user saved, using only the text below.

Reply with JSON and nothing else:

{"summary": "...", "tags": ["..."], "resources": [{"type": "...", "name": "...",
 "detail": "...", "url": "..."}]}

Rules:
- Everything you write must be supported by the text you were given. You cannot \
see a video and you are not being asked to. You are describing words that were \
actually said or written.
- summary: two to four sentences on what this is about, in plain language. No \
preamble, no "this video discusses".
- tags: three to eight lowercase topic words. Nouns, not sentences. Only topics \
the text is actually about.
- resources: concrete things the text names that the user could go and find -- a \
place, a product, a book, a tool, a recipe, a person, a link. `type` is one of \
place|product|book|tool|recipe|person|link|other. `detail` is what the text said \
about it, in ten words or fewer. `url` only when the text contains one.
- An empty list is the right answer when the text names nothing. Padding a list \
with things that were not mentioned is the main failure mode here.
- If the text is too thin to say anything true about, reply \
{"summary": null, "tags": [], "resources": []}."""


@dataclass(frozen=True)
class Enrichment:
    summary: str | None = None
    tags: tuple[str, ...] = ()
    resources: tuple[dict, ...] = ()
    #: Why there is nothing, when there is nothing. Never prose, always a reason.
    note: str | None = None
    provider: str | None = None
    model: str | None = None

    @property
    def empty(self) -> bool:
        return not (self.summary or self.tags or self.resources)


def _clean_tag(value: object) -> str | None:
    tag = re.sub(r"\s+", " ", str(value or "")).strip().lower()[:40]
    return tag or None


def _clean_resource(entry: object) -> dict | None:
    if not isinstance(entry, dict):
        return None
    name = str(entry.get("name") or "").strip()[:120]
    if not name:
        return None
    kind = str(entry.get("type") or "other").strip().lower()
    url = str(entry.get("url") or "").strip()
    return {
        "type": kind if kind in RESOURCE_TYPES else "other",
        "name": name,
        "detail": str(entry.get("detail") or "").strip()[:200],
        # A model asked for a url when the text has none will happily invent a
        # plausible one; anything that is not plainly a link is dropped.
        "url": url if url.startswith(("http://", "https://")) else "",
    }


def parse_enrichment(text: str) -> Enrichment | None:
    """Read the model's reply, keeping only what is the right shape.

    Built like `memory/service.py:parse_diff`: a model that wanders off the
    format costs the tags, never the item.
    """
    body = (text or "").strip()
    if not body:
        return None
    if body.startswith("```"):
        body = re.sub(r"^```[a-z]*\s*", "", body)
        body = re.sub(r"\s*```$", "", body)
    if not body.startswith("{"):
        start, end = body.find("{"), body.rfind("}")
        if start == -1 or end <= start:
            return None
        body = body[start : end + 1]

    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    summary = data.get("summary")
    summary = str(summary).strip() if isinstance(summary, str) and summary.strip() else None

    tags = []
    for value in data.get("tags") or []:
        tag = _clean_tag(value)
        if tag and tag not in tags:
            tags.append(tag)

    resources = []
    for entry in data.get("resources") or []:
        cleaned = _clean_resource(entry)
        if cleaned:
            resources.append(cleaned)

    return Enrichment(
        summary=summary,
        tags=tuple(tags[:MAX_TAGS]),
        resources=tuple(resources[:MAX_RESOURCES]),
    )


def _refusal(text: str, text_source: str | None) -> str | None:
    """The reason not to ask a model, when there is one."""
    if (text_source or "none") not in REAL_TEXT_SOURCES:
        return (
            "there is no text for this one. A direct-message share carries the video"
            " and a title, and no caption -- nothing was summarised because there"
            " would have been nothing to summarise from."
        )
    if len(text.strip()) < MIN_ENRICHABLE_CHARS:
        return (
            "the text is a line or two, which is already the whole of it. Summarising"
            " it would just be repeating it."
        )
    return None


async def enrich_text(
    text: str, *, title: str, kind: str = "video", text_source: str = "none", client=None
) -> Enrichment:
    """Summary, tags and resources for some text -- or a stated reason there are none."""
    refusal = _refusal(text, text_source)
    if refusal:
        # Returns before any client is resolved. This is the guard, and it is
        # structural on purpose: a prompt can be edited, a return cannot.
        return Enrichment(note=refusal)

    body = text.strip()[:MAX_ENRICH_CHARS]
    if len(text.strip()) > MAX_ENRICH_CHARS:
        body += "\n…(cut off)"
    messages = [
        {"role": "system", "content": PROMPT},
        {
            "role": "user",
            # The source is named because a whisper transcript has no reliable
            # punctuation and the model should know it is reading speech.
            "content": (
                f"<title>{title}</title>\n<kind>{kind}</kind>\n"
                f"<source>{text_source}</source>\n<text>\n{body}\n</text>"
            ),
        },
    ]

    if client is not None:
        return await _ask(client, messages, None, None)

    links = default_chain(limit=BACKGROUND_FALLBACK_LINKS)
    if not links:
        return Enrichment(
            note="no model is configured, so there is no summary. The text above is"
            " what was actually said."
        )

    last: Enrichment | None = None
    for link in links:
        try:
            model = resolve(link.provider, link.model)
        except Exception as exc:
            last = Enrichment(note=f"{link.provider} could not be resolved: {exc}")
            continue
        result = await _ask(model.client, messages, link.provider, link.model)
        if not result.empty:
            availability.record_success(link.provider)
            return result
        last = result

    tried = ", ".join(str(link) for link in links)
    reason = last.note if last and last.note else "nothing came back"
    return Enrichment(note=f"none of the configured providers answered ({tried}). {reason}")


async def _ask(client, messages: list[dict], provider: str | None, model: str | None) -> Enrichment:
    try:
        response = await asyncio.wait_for(
            client.complete(messages, tools=None), timeout=ENRICH_TIMEOUT
        )
    except TimeoutError:
        late = f"{provider or 'the model'} did not answer within {ENRICH_TIMEOUT:.0f}s"
        if provider:
            availability.record_failure(provider, FailureKind.RETRYABLE, late)
        return Enrichment(note=late)
    except Exception as exc:
        log.warning("enrichment failed on %s: %s", provider or "the model", exc)
        if provider:
            availability.record_failure(
                provider, getattr(exc, "kind", FailureKind.RETRYABLE), str(exc)
            )
        return Enrichment(note=f"{provider or 'the model'} could not be reached: {exc}")

    parsed = parse_enrichment(response.text or "")
    if parsed is None:
        return Enrichment(
            note="the model did not answer in the expected format", provider=provider, model=model
        )
    return Enrichment(
        summary=parsed.summary,
        tags=parsed.tags,
        resources=parsed.resources,
        provider=provider,
        model=model,
    )


def render_markdown(
    *,
    title: str,
    body: str,
    body_heading: str = "Text",
    enrichment: Enrichment | None = None,
    capture_note: str | None = None,
) -> str:
    """The item's file: what the model wrote, then what was actually said.

    The `## {body_heading}` heading and the provenance footer are the honesty
    rule expressed in the artefact rather than only in a database column -- a
    reader can always tell which words are the source's and which are not.
    """
    out = [f"# {title}", ""]
    enrichment = enrichment or Enrichment()

    if enrichment.summary:
        out += [enrichment.summary, ""]
    if enrichment.tags:
        out += [f"Tags: {', '.join(enrichment.tags)}", ""]
    if enrichment.resources:
        out.append("## Mentioned")
        for item in enrichment.resources:
            line = f"- {item['type']} — {item['name']}"
            if item.get("detail"):
                line += f": {item['detail']}"
            if item.get("url"):
                line += f" ({item['url']})"
            out.append(line)
        out.append("")

    if body.strip():
        out += [f"## {body_heading}", "", body.strip(), ""]
    elif capture_note:
        out += [f"_{capture_note}_", ""]

    if enrichment.summary or enrichment.tags or enrichment.resources:
        source = enrichment.model or "a model"
        provider = f"{enrichment.provider}:{source}" if enrichment.provider else source
        out += [
            "---",
            f"_Summary, tags and the list above were written by {provider} from the"
            f" {body_heading.lower()}. The {body_heading.lower()} is what was said._",
        ]
    elif enrichment.note:
        out += ["---", f"_{enrichment.note}_"]

    return "\n".join(out).rstrip() + "\n"


#: The headings `render_markdown` writes a body under. Knowing them is what lets
#: the source text be read back out of a file that has already been enriched --
#: without it, re-enriching would summarise the previous summary.
BODY_HEADINGS = ("Transcript", "Caption", "Text", "Notes")

_HEADING = re.compile(rf"^## ({'|'.join(BODY_HEADINGS)})\s*$", re.MULTILINE)


def body_of(markdown: str) -> tuple[str, str]:
    """The source text out of an item's file, and which heading it sat under.

    `render_markdown` is the only writer of these files, so this is a parse of a
    format we control rather than a guess at someone else's.
    """
    text = markdown or ""
    match = _HEADING.search(text)
    if match:
        body = text[match.end() :]
        # Everything up to the provenance rule, which is the last thing written.
        cut = body.rfind("\n---\n")
        if cut != -1:
            body = body[:cut]
        return body.strip(), match.group(1)

    # Never enriched: the file is a title and then the text.
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip(), "Text"


def stamp() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")
