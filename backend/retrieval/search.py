"""Hybrid search over the indexed vault."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from backend.db.connection import get_connection
from backend.retrieval import store
from backend.retrieval.embeddings import Embedder

log = logging.getLogger(__name__)

CANDIDATES_PER_INDEX = 30


@dataclass
class SearchHit:
    chunk_id: int
    content: str
    path: str
    heading_path: str | None
    score: float

    @property
    def label(self) -> str:
        name = Path(self.path).name
        return f"{name} > {self.heading_path}" if self.heading_path else name


class SearchService:
    def __init__(self, embedder: Embedder | None = None, conn=None):
        self.conn = conn or get_connection()
        self.embedder = embedder or self._embedder_matching_index()

    def _embedder_matching_index(self) -> Embedder:
        """Query with the model that built the index, not a global default.

        Embedding a query with a different model than the documents produces
        vectors in an unrelated space, which returns plausible-looking nonsense
        rather than an error.
        """
        recorded = store.indexed_embedding_model(self.conn)
        if recorded is None:
            return Embedder()
        provider, model = recorded
        return Embedder(provider, model)

    async def search(
        self,
        query: str,
        *,
        limit: int = 8,
        path_glob: str | None = None,
        semantic: bool = True,
    ) -> list[SearchHit]:
        """Vector and keyword search fused by reciprocal rank.

        Either index alone is a weak default: dense vectors miss exact terms, and
        keyword search misses paraphrase. Fusing ranks covers both.
        """
        if not query.strip():
            return []

        rankings: list[list[tuple[int, float]]] = []

        keyword_hits = store.search_keywords(self.conn, query, CANDIDATES_PER_INDEX)
        if keyword_hits:
            rankings.append(keyword_hits)

        if semantic and store.vector_available(self.conn):
            try:
                vector = await self.embedder.embed_one(query)
                vector_hits = store.search_vectors(self.conn, vector, CANDIDATES_PER_INDEX)
                if vector_hits:
                    rankings.append(vector_hits)
            except Exception as exc:
                # Keyword results are still useful, so degrade rather than fail.
                log.warning("semantic search unavailable, using keywords only: %s", exc)

        if not rankings:
            return []

        fused = store.reciprocal_rank_fusion(rankings)
        return self._hydrate([cid for cid, _ in fused], dict(fused), limit, path_glob)

    def _hydrate(
        self,
        chunk_ids: list[int],
        scores: dict[int, float],
        limit: int,
        path_glob: str | None,
    ) -> list[SearchHit]:
        if not chunk_ids:
            return []
        # Fetch more than needed so a path filter still returns a full page.
        window = chunk_ids[: limit * 4]
        placeholders = ",".join("?" * len(window))
        sql = (
            "SELECT c.id, c.content, c.heading_path, d.path FROM document_chunks c"
            f" JOIN documents d ON d.id = c.document_id WHERE c.id IN ({placeholders})"
        )
        params: list = list(window)
        if path_glob:
            sql += " AND d.path GLOB ?"
            params.append(path_glob if "*" in path_glob else f"*{path_glob}*")

        rows = self.conn.execute(sql, params).fetchall()
        hits = [
            SearchHit(
                chunk_id=row["id"],
                content=row["content"],
                path=row["path"],
                heading_path=row["heading_path"],
                score=scores.get(row["id"], 0.0),
            )
            for row in rows
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    async def context_for(self, query: str, *, budget_chars: int = 6000) -> str:
        """Assemble retrieved context for the system prompt, within a budget."""
        hits = await self.search(query, limit=6)
        if not hits:
            return ""

        blocks: list[str] = []
        used = 0
        for hit in hits:
            block = f"[{hit.label}]\n{hit.content}"
            if used + len(block) > budget_chars:
                break
            blocks.append(block)
            used += len(block)
        return "\n\n".join(blocks)
