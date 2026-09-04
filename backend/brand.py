"""The user's own voice, and how PSOK writes in it.

A brand kit is only worth storing if it changes something. So this is not a
settings page that remembers a palette: `prompt_block` is injected into the
system prompt on every turn, and `GET /api/brand` returns that exact text
alongside the fields, so what the model is told is visible rather than implied.

Two rules keep it from becoming noise:

**An empty or switched-off profile injects nothing.** Not an empty block, not a
skeleton of blank headings -- nothing. A `<brand>` carrying "voice:" and no
voice costs context on every turn and tells the model the user has none.

**It is scoped to writing done in the user's name.** Posts, copy, captions,
newsletters. Not answers PSOK gives the user directly, which should stay plain,
and not a topic to raise unprompted. The block says so in its first line,
because a model given a voice with no scope will use it to answer questions.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass

from backend.db.connection import get_connection

log = logging.getLogger(__name__)

#: Longest value kept per field. A voice note is a paragraph; anything past this
#: is a document that belongs in the vault, and it would be paid for every turn.
MAX_FIELD_CHARS = 1200
MAX_LIST_ITEMS = 12
MAX_ITEM_CHARS = 160

TEXT_FIELDS = ("name", "mission", "audience", "voice")
LIST_FIELDS = ("values", "do", "dont")
OBJECT_FIELDS = ("palette", "fonts")

_COLUMN_FOR = {"values": "values_list", "do": "do_list", "dont": "dont_list"}


@dataclass(frozen=True)
class Brand:
    enabled: bool = True
    name: str = ""
    mission: str = ""
    audience: str = ""
    voice: str = ""
    values: tuple[str, ...] = ()
    do: tuple[str, ...] = ()
    dont: tuple[str, ...] = ()
    #: [{"name": "ink", "hex": "#0a0a0b"}, ...]
    palette: tuple[dict[str, str], ...] = ()
    #: [{"role": "display", "family": "Space Grotesk"}, ...]
    fonts: tuple[dict[str, str], ...] = ()
    updated_at: str | None = None

    def is_empty(self) -> bool:
        """True when there is nothing here worth telling a model."""
        return not any(
            (self.name, self.mission, self.audience, self.voice)
            + (self.values, self.do, self.dont, self.palette, self.fonts)
        )

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "name": self.name,
            "mission": self.mission,
            "audience": self.audience,
            "voice": self.voice,
            "values": list(self.values),
            "do": list(self.do),
            "dont": list(self.dont),
            "palette": [dict(p) for p in self.palette],
            "fonts": [dict(f) for f in self.fonts],
            "updated_at": self.updated_at,
        }


def _text(value: object) -> str:
    return str(value or "").strip()[:MAX_FIELD_CHARS]


def _items(value: object) -> tuple[str, ...]:
    """A list of short strings, from a list or from one line per item."""
    if isinstance(value, str):
        raw = [part for part in value.replace("\r", "").split("\n")]
    elif isinstance(value, (list, tuple)):
        raw = [str(part) for part in value]
    else:
        return ()
    cleaned = [part.strip()[:MAX_ITEM_CHARS] for part in raw]
    return tuple(part for part in cleaned if part)[:MAX_LIST_ITEMS]


def _objects(value: object, keys: tuple[str, str]) -> tuple[dict[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[dict[str, str]] = []
    for entry in value[:MAX_LIST_ITEMS]:
        if not isinstance(entry, dict):
            continue
        first = _text(entry.get(keys[0]))[:MAX_ITEM_CHARS]
        second = _text(entry.get(keys[1]))[:MAX_ITEM_CHARS]
        if first or second:
            out.append({keys[0]: first, keys[1]: second})
    return tuple(out)


def _json_list(raw: object) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw if isinstance(raw, str) else "[]")
    except (ValueError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def from_payload(payload: dict) -> Brand:
    """A Brand from whatever the interface or a tool sent, clamped and cleaned."""
    return Brand(
        enabled=bool(payload.get("enabled", True)),
        name=_text(payload.get("name")),
        mission=_text(payload.get("mission")),
        audience=_text(payload.get("audience")),
        voice=_text(payload.get("voice")),
        values=_items(payload.get("values")),
        do=_items(payload.get("do")),
        dont=_items(payload.get("dont")),
        palette=_objects(payload.get("palette"), ("name", "hex")),
        fonts=_objects(payload.get("fonts"), ("role", "family")),
    )


def load(conn: sqlite3.Connection | None = None) -> Brand:
    """The stored profile, or an empty one. Never raises: a prompt must build."""
    try:
        conn = conn or get_connection()
        row = conn.execute("SELECT * FROM brand_profile WHERE id = 1").fetchone()
    except sqlite3.Error as exc:
        log.warning("brand profile unavailable: %s", exc)
        return Brand()
    if row is None:
        return Brand()
    return Brand(
        enabled=bool(row["enabled"]),
        name=row["name"] or "",
        mission=row["mission"] or "",
        audience=row["audience"] or "",
        voice=row["voice"] or "",
        values=tuple(str(v) for v in _json_list(row["values_list"])),
        do=tuple(str(v) for v in _json_list(row["do_list"])),
        dont=tuple(str(v) for v in _json_list(row["dont_list"])),
        palette=_objects(_json_list(row["palette"]), ("name", "hex")),
        fonts=_objects(_json_list(row["fonts"]), ("role", "family")),
        updated_at=row["updated_at"],
    )


def save(brand: Brand, conn: sqlite3.Connection | None = None) -> Brand:
    """Write the one row. Returns what was stored, read back."""
    conn = conn or get_connection()
    conn.execute(
        "INSERT INTO brand_profile (id, enabled, name, mission, audience, voice,"
        " values_list, do_list, dont_list, palette, fonts, updated_at)"
        " VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))"
        " ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled, name = excluded.name,"
        " mission = excluded.mission, audience = excluded.audience, voice = excluded.voice,"
        " values_list = excluded.values_list, do_list = excluded.do_list,"
        " dont_list = excluded.dont_list, palette = excluded.palette,"
        " fonts = excluded.fonts, updated_at = datetime('now')",
        (
            int(brand.enabled),
            brand.name,
            brand.mission,
            brand.audience,
            brand.voice,
            json.dumps(list(brand.values)),
            json.dumps(list(brand.do)),
            json.dumps(list(brand.dont)),
            json.dumps([dict(p) for p in brand.palette]),
            json.dumps([dict(f) for f in brand.fonts]),
        ),
    )
    conn.commit()
    return load(conn)


_SCOPE = (
    "When you write something in the user's own voice -- a post, an email, copy,"
    " a caption, a newsletter, a page -- write it like this. It does not apply to"
    " answers you give them directly, and it is not a subject to raise unless"
    " they do."
)


def prompt_block(brand: Brand | None = None) -> str:
    """The <brand> block, or "" when there is nothing to say."""
    brand = load() if brand is None else brand
    if not brand.enabled or brand.is_empty():
        return ""

    lines = [f"  {_SCOPE}"]
    for label, value in (
        ("name", brand.name),
        ("audience", brand.audience),
        ("mission", brand.mission),
        ("voice", brand.voice),
    ):
        if value:
            lines.append(f"  {label}: {value}")
    for label, values in (("values", brand.values), ("always", brand.do), ("never", brand.dont)):
        if values:
            lines.append(f"  {label}: {'; '.join(values)}")
    if brand.palette:
        rendered = "; ".join(
            " ".join(part for part in (p.get("name"), p.get("hex")) if part) for p in brand.palette
        )
        lines.append(f"  palette: {rendered}")
    if brand.fonts:
        rendered = "; ".join(
            " ".join(part for part in (f.get("role"), f.get("family")) if part) for f in brand.fonts
        )
        lines.append(f"  fonts: {rendered}")

    return "<brand>\n" + "\n".join(lines) + "\n</brand>"
