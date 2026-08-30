"""Document search tools.

Retrieval is available two ways deliberately: context is pre-fetched into the
prompt for the opening question, and this tool lets the model re-query mid-turn
once it knows what it actually needs -- which the first automatic fetch cannot
predict.
"""

from __future__ import annotations

from typing import Any

from backend.retrieval.search import SearchService
from backend.tools.base import RiskLevel, Tool, ToolContext, ToolResult


async def search_documents(args: dict[str, Any], _: ToolContext) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult.error("search_documents needs a query")

    service = SearchService()
    hits = await service.search(
        query,
        limit=int(args.get("limit") or 6),
        path_glob=args.get("path_filter"),
    )
    if not hits:
        stats = _stats()
        if stats["chunks"] == 0:
            return ToolResult.ok(
                "No documents are indexed yet. The user can index a folder with"
                " `psok index <path>`."
            )
        return ToolResult.ok(f"No matches for {query!r} across {stats['chunks']} indexed chunks.")

    blocks = [f"[{hit.label}]\n{hit.content}" for hit in hits]
    return ToolResult.ok("\n\n---\n\n".join(blocks))


def _stats() -> dict[str, int]:
    from backend.retrieval.indexer import Indexer

    return Indexer().stats()


async def index_status(_: dict[str, Any], __: ToolContext) -> ToolResult:
    stats = _stats()
    if not stats["documents"]:
        return ToolResult.ok("Nothing is indexed. Index a folder with `psok index <path>`.")
    return ToolResult.ok(
        f"{stats['documents']} documents indexed, {stats['chunks']} searchable chunks."
    )


def tools() -> list[Tool]:
    return [
        Tool(
            name="search_documents",
            description=(
                "Search the user's indexed notes and documents. Combines semantic and"
                " keyword matching, so both paraphrases and exact terms work. Use this"
                " whenever a question might be answered by something the user has written."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "limit": {"type": "integer", "description": "Maximum passages (default 6)"},
                    "path_filter": {
                        "type": "string",
                        "description": "Only match documents whose path contains this",
                    },
                },
                "required": ["query"],
            },
            handler=search_documents,
            risk=RiskLevel.LOW,
        ),
        Tool(
            name="index_status",
            description="Report how many documents and chunks are currently indexed.",
            parameters={"type": "object", "properties": {}},
            handler=index_status,
            risk=RiskLevel.LOW,
        ),
    ]
