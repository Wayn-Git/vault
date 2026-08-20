"""Vector and keyword indexes, both inside the same SQLite database (ADR-0003).

`sqlite-vec` supplies similarity search and FTS5 supplies a real inverted index.
Khoj calls vector-search-plus-ILIKE "hybrid", which oversells it: ILIKE is a
substring scan with no ranking and no term statistics. Exact-term recall -- a
function name, an error code, an unusual proper noun -- is precisely where dense
vectors are weakest, so the keyword index is the other half, not a refinement.
"""

from __future__ import annotations

import logging
import sqlite3
import struct

log = logging.getLogger(__name__)

# Whether the sqlite_vec package can be imported at all: a process-wide fact.
# Whether it is loaded into a given connection is per-connection and probed,
# never cached by id() -- CPython reuses id() for sequential connections, so an
# id-keyed cache hands a fresh connection a dead one's flag.
_package_available: bool | None = None


def serialize(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _is_loaded(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT vec_version()").fetchone()
        return True
    except sqlite3.OperationalError:
        return False


def load_extension(conn: sqlite3.Connection) -> bool:
    """Ensure sqlite-vec is loaded into this connection."""
    global _package_available

    if _is_loaded(conn):
        return True
    if _package_available is False:
        return False

    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _package_available = True
        return _is_loaded(conn)
    except Exception as exc:
        if _package_available is None:
            log.warning("sqlite-vec unavailable, semantic search disabled: %s", exc)
            _package_available = False
        return False


def vector_available(conn: sqlite3.Connection) -> bool:
    return load_extension(conn)


def ensure_indexes(conn: sqlite3.Connection, dimensions: int) -> None:
    """Create the FTS5 and vec0 tables. Dimensions are fixed at creation time."""
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
        " content, heading_path, content_rowid UNINDEXED, tokenize='porter unicode61')"
    )
    if not load_extension(conn):
        return

    existing = conn.execute(
        "SELECT value FROM app_settings WHERE key = 'embedding_dimensions'"
    ).fetchone()
    if existing and int(existing["value"]) != dimensions:
        # Vectors from different models are not comparable, so a dimension change
        # means the whole index has to be rebuilt rather than silently mixed.
        log.warning(
            "embedding dimensions changed from %s to %s; dropping the vector index",
            existing["value"],
            dimensions,
        )
        conn.execute("DROP TABLE IF EXISTS chunk_vectors")

    try:
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0("
            f" chunk_id INTEGER PRIMARY KEY, embedding float[{dimensions}])"
        )
    except sqlite3.OperationalError as exc:
        # Keyword indexing must survive a vector-index failure. Losing semantic
        # search degrades results; losing the FTS index loses the document.
        log.warning("could not create the vector index, keyword search only: %s", exc)
        conn.commit()
        return

    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES ('embedding_dimensions', ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
        (str(dimensions),),
    )
    conn.commit()


def record_embedding_model(conn: sqlite3.Connection, provider: str, model: str) -> None:
    """Remember which model built the index.

    Queries must be embedded by the same model that embedded the documents;
    vectors from different models occupy different spaces and comparing them
    silently returns nonsense rather than failing.
    """
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES ('embedding_model', ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
        (f"{provider}:{model}",),
    )
    conn.commit()


def indexed_embedding_model(conn: sqlite3.Connection) -> tuple[str, str] | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'embedding_model'").fetchone()
    if not row or ":" not in row["value"]:
        return None
    provider, _, model = row["value"].partition(":")
    return provider, model


def index_chunk(
    conn: sqlite3.Connection,
    chunk_id: int,
    content: str,
    heading_path: str | None,
    embedding: list[float] | None,
) -> None:
    conn.execute(
        "INSERT INTO chunks_fts (content, heading_path, content_rowid) VALUES (?, ?, ?)",
        (content, heading_path or "", chunk_id),
    )
    if embedding and load_extension(conn):
        conn.execute(
            "INSERT OR REPLACE INTO chunk_vectors (chunk_id, embedding) VALUES (?, ?)",
            (chunk_id, serialize(embedding)),
        )


def remove_chunks(conn: sqlite3.Connection, chunk_ids: list[int]) -> None:
    if not chunk_ids:
        return
    placeholders = ",".join("?" * len(chunk_ids))
    conn.execute(f"DELETE FROM chunks_fts WHERE content_rowid IN ({placeholders})", chunk_ids)
    if load_extension(conn):
        conn.execute(f"DELETE FROM chunk_vectors WHERE chunk_id IN ({placeholders})", chunk_ids)


def search_vectors(
    conn: sqlite3.Connection, embedding: list[float], limit: int
) -> list[tuple[int, float]]:
    if not load_extension(conn):
        return []
    try:
        rows = conn.execute(
            "SELECT chunk_id, distance FROM chunk_vectors"
            " WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (serialize(embedding), limit),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        log.warning("vector search failed: %s", exc)
        return []
    return [(r["chunk_id"], r["distance"]) for r in rows]


def search_keywords(conn: sqlite3.Connection, query: str, limit: int) -> list[tuple[int, float]]:
    """BM25-ranked keyword search. FTS5 returns lower scores for better matches."""
    sanitized = _sanitize_fts_query(query)
    if not sanitized:
        return []
    try:
        rows = conn.execute(
            "SELECT content_rowid, bm25(chunks_fts) AS score FROM chunks_fts"
            " WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?",
            (sanitized, limit),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        log.warning("keyword search failed for %r: %s", query, exc)
        return []
    return [(r["content_rowid"], r["score"]) for r in rows]


def _sanitize_fts_query(query: str) -> str:
    """Turn free text into a safe FTS5 query.

    User text reaches this directly, and FTS5's operators would otherwise raise
    syntax errors on ordinary punctuation.
    """
    # Single characters are kept: "C", "R" and "Go" are real search terms in a
    # personal knowledge base, and dropping them made them unfindable.
    tokens = [t for t in "".join(c if c.isalnum() else " " for c in query).split() if t]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


def reciprocal_rank_fusion(
    rankings: list[list[tuple[int, float]]], *, k: int = 60
) -> list[tuple[int, float]]:
    """Merge ranked lists by rank rather than score.

    Cosine distances and BM25 scores are on unrelated scales, so blending the raw
    numbers would let whichever scale happens to be larger dominate. RRF only
    uses position, which is what makes the two comparable at all.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for position, (chunk_id, _) in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + position + 1)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
