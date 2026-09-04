"""Tools over the library.

These handlers translate arguments in and phrase results out; they hold no logic
of their own -- `backend/library/service.py` owns it, and the HTTP routes, the
share endpoint and these tools all go through it.

`search_documents` already finds library material, because it is the same index.
`search_library` exists because "what have I read about X" is a different
question from "what is in my notes about X", and answering it with the item --
title, author, when you read it -- rather than a passage under `~/.psok` is what
makes the answer usable.
"""

from __future__ import annotations

from typing import Any

from backend.library.service import LibraryError, LibraryService, describe
from backend.library.store import KINDS
from backend.tools.base import RiskLevel, Tool, ToolContext, ToolResult


def _service() -> LibraryService:
    return LibraryService()


async def log_library_item(args: dict[str, Any], _: ToolContext) -> ToolResult:
    url = (args.get("url") or "").strip()
    try:
        if url:
            captured = await _service().capture_url(
                url,
                kind=args.get("kind"),
                consumed_on=args.get("consumed_on"),
                notes=args.get("notes"),
                title=args.get("title"),
            )
        else:
            captured = await _service().log_manual(
                title=args.get("title") or "",
                kind=args.get("kind") or "note",
                text=args.get("text"),
                author=args.get("author"),
                notes=args.get("notes"),
                consumed_on=args.get("consumed_on"),
                rating=args.get("rating"),
            )
    except LibraryError as exc:
        return ToolResult.error(str(exc))

    if captured.already_logged:
        return ToolResult.ok(f"Already in the library: {describe(captured.item)}")
    return ToolResult.ok(f"Logged: {describe(captured.item)}")


async def search_library(args: dict[str, Any], _: ToolContext) -> ToolResult:
    query = (args.get("query") or "").strip()
    limit = max(1, min(int(args.get("limit") or 8), 30))
    service = _service()

    if not query:
        items = service.recent(kind=args.get("kind"), limit=limit)
        if not items:
            return ToolResult.ok("The library is empty.")
        return ToolResult.ok("\n".join(describe(item) for item in items))

    try:
        results = await service.search(query, limit=limit)
    except Exception as exc:  # a broken index must not look like an empty one
        return ToolResult.error(f"the library index could not be searched: {exc}")

    if not results:
        counts = service.counts()
        if not counts:
            return ToolResult.ok("The library is empty, so there is nothing to search yet.")
        return ToolResult.ok(
            f"Nothing in the library matched {query!r}."
            " Items logged without captured text are findable by title only."
        )
    return ToolResult.ok(
        "\n\n".join(f"{describe(item)}\n{item['excerpt']}" for item in results)
    )


def tools() -> list[Tool]:
    return [
        Tool(
            name="log_library_item",
            description=(
                "Log something the user read, watched or listened to. Give a url to"
                " capture the page's text, or a title for a book or a talk with no"
                " url. Use when the user says they have read or watched something,"
                " or asks to save a link."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The address, if there is one"},
                    "title": {
                        "type": "string",
                        "description": "Required when there is no url; otherwise taken from"
                        " the page",
                    },
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "author": {"type": "string"},
                    "notes": {
                        "type": "string",
                        "description": "The user's own thoughts about it, in their words",
                    },
                    "text": {
                        "type": "string",
                        "description": "The body, when there is no url to fetch it from",
                    },
                    "consumed_on": {
                        "type": "string",
                        "description": "YYYY-MM-DD. Defaults to today. Do not compute this"
                        " yourself unless the user gave an exact date.",
                    },
                    "rating": {"type": "integer", "description": "1 to 5, the user's own"},
                },
            },
            handler=log_library_item,
            # It writes a row and a file, and fetches a URL the user named.
            risk=RiskLevel.MEDIUM,
        ),
        Tool(
            name="search_library",
            description=(
                "Search what the user has read, watched and listened to, by meaning"
                " and by keyword. Answers 'what do I know about X' and 'what was that"
                " article about Y'. With no query, lists the most recent items."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for"},
                    "kind": {
                        "type": "string",
                        "enum": list(KINDS),
                        "description": "Only used when listing without a query",
                    },
                    "limit": {"type": "integer", "description": "Maximum items (default 8)"},
                },
            },
            handler=search_library,
            risk=RiskLevel.LOW,
        ),
    ]
