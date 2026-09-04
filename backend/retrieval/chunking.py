"""Splitting documents into retrievable chunks.

Heading paths are prepended to each chunk because a personal knowledge base is
mostly markdown notes, where a chunk lifted out of its section loses the context
that makes it findable -- "Tuesday" means nothing without "## Standup notes".
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

DEFAULT_CHUNK_TOKENS = 400
DEFAULT_OVERLAP_TOKENS = 40
CHARS_PER_TOKEN = 4

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# Split points in descending order of preference.
_SEPARATORS = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]


@dataclass
class Chunk:
    index: int
    content: str
    heading_path: str | None
    token_count: int

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _split_oversized(text: str, limit_chars: int) -> list[str]:
    """Break text that exceeds the limit at the best available separator."""
    if len(text) <= limit_chars:
        return [text]

    for separator in _SEPARATORS:
        if separator not in text:
            continue
        parts, current = [], ""
        for piece in text.split(separator):
            candidate = f"{current}{separator}{piece}" if current else piece
            if len(candidate) > limit_chars and current:
                parts.append(current)
                current = piece
            else:
                current = candidate
        if current:
            parts.append(current)
        if len(parts) > 1:
            # A part may still be too long; recurse on the remaining separators.
            out: list[str] = []
            for part in parts:
                out.extend(
                    _split_oversized(part, limit_chars) if len(part) > limit_chars else [part]
                )
            return out

    # No separator helped -- a single unbroken run, so cut it.
    return [text[i : i + limit_chars] for i in range(0, len(text), limit_chars)]


def chunk_markdown(
    text: str,
    *,
    max_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Split on heading structure first, then size, keeping the heading path.

    Overlap carries a little tail context into the next chunk so a fact split
    across a boundary is still retrievable from either side.
    """
    limit_chars = max_tokens * CHARS_PER_TOKEN
    overlap_chars = min(overlap_tokens * CHARS_PER_TOKEN, limit_chars // 2)

    sections: list[tuple[str | None, str]] = []
    heading_stack: list[tuple[int, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            path = " > ".join(title for _, title in heading_stack) or None
            sections.append((path, body))
        buffer.clear()

    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, match.group(2).strip()))
        else:
            buffer.append(line)
    flush()

    if not sections:
        stripped = text.strip()
        if not stripped:
            return []
        sections = [(None, stripped)]

    chunks: list[Chunk] = []
    for heading_path, body in sections:
        prefix = f"{heading_path}\n\n" if heading_path else ""
        budget = max(limit_chars - len(prefix), limit_chars // 2)

        pieces = _split_oversized(body, budget)
        for position, piece in enumerate(pieces):
            if position and overlap_chars:
                tail = pieces[position - 1][-overlap_chars:]
                piece = f"{tail}\n{piece}"
            content = f"{prefix}{piece}".strip()
            chunks.append(
                Chunk(
                    index=len(chunks),
                    content=content,
                    heading_path=heading_path,
                    token_count=estimate_tokens(content),
                )
            )
    return chunks


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
