"""Indexing the user's vault.

Content-hash incremental indexing is Khoj's pattern and the reason continuous
sync is practical: hash each chunk, diff against what is stored for that
document, embed only what changed, delete what disappeared. Re-scanning an
unchanged vault costs a file read and a hash comparison, not an embedding bill.

Original files stay on disk as the source of truth; this builds an index that
points at them (ADR-0004).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from backend.db.connection import get_connection
from backend.retrieval import store
from backend.retrieval.chunking import chunk_markdown, file_hash
from backend.retrieval.embeddings import Embedder, EmbeddingError

log = logging.getLogger(__name__)

TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".org",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".sh",
    ".sql",
    ".html",
    ".css",
}
SKIP_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    "target",
}
MAX_FILE_BYTES = 2_000_000


@dataclass
class IndexReport:
    scanned: int = 0
    indexed: int = 0
    unchanged: int = 0
    removed: int = 0
    chunks_added: int = 0
    chunks_deleted: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{self.scanned} files scanned",
            f"{self.indexed} indexed",
            f"{self.unchanged} unchanged",
        ]
        if self.removed:
            parts.append(f"{self.removed} removed")
        parts.append(f"{self.chunks_added} chunks embedded")
        if self.chunks_deleted:
            parts.append(f"{self.chunks_deleted} chunks dropped")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return ", ".join(parts)


def discover(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(
            part in SKIP_DIRECTORIES or part.startswith(".")
            for part in path.relative_to(root).parts[:-1]
        ):
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        found.append(path)
    return sorted(found)


class Indexer:
    def __init__(self, embedder: Embedder | None = None, conn=None):
        self.embedder = embedder or Embedder()
        self.conn = conn or get_connection()

    async def index_vault(self, root: Path, *, prune: bool = True) -> IndexReport:
        root = Path(root).expanduser().resolve()
        report = IndexReport()
        if not root.is_dir():
            report.errors.append(f"not a directory: {root}")
            return report

        files = discover(root)
        report.scanned = len(files)

        for path in files:
            try:
                await self.index_file(path, report)
            except EmbeddingError:
                raise  # a broken embedder affects every file; fail loudly once
            except Exception as exc:
                report.errors.append(f"{path}: {exc}")

        if prune:
            report.removed = self._prune_missing(root, {str(p) for p in files}, report)
        return report

    async def index_file(self, path: Path, report: IndexReport | None = None) -> int:
        """Index one file. Returns the number of chunks embedded (0 if unchanged)."""
        report = report or IndexReport()
        path = Path(path).expanduser().resolve()

        raw = path.read_bytes()
        digest = file_hash(raw)
        stat = path.stat()

        existing = self.conn.execute(
            "SELECT id, content_hash, stale FROM documents WHERE path = ?", (str(path),)
        ).fetchone()

        if existing and existing["content_hash"] == digest and not existing["stale"]:
            report.unchanged += 1
            return 0

        text = raw.decode("utf-8", errors="replace")
        chunks = chunk_markdown(text)
        if not chunks:
            report.unchanged += 1
            return 0

        if existing:
            document_id = existing["id"]
            self.conn.execute(
                "UPDATE documents SET content_hash = ?, size_bytes = ?, mtime = ?,"
                " indexed_at = datetime('now'), stale = 0 WHERE id = ?",
                (digest, stat.st_size, stat.st_mtime, document_id),
            )
        else:
            cursor = self.conn.execute(
                "INSERT INTO documents (path, content_hash, file_type, size_bytes, mtime,"
                " title, source, indexed_at) VALUES (?, ?, ?, ?, ?, ?, 'vault', datetime('now'))",
                (
                    str(path),
                    digest,
                    path.suffix.lstrip("."),
                    stat.st_size,
                    stat.st_mtime,
                    path.stem,
                ),
            )
            document_id = cursor.lastrowid

        # Diff by chunk hash so an edit to one paragraph re-embeds one chunk.
        stored = {
            row["content_hash"]: row["id"]
            for row in self.conn.execute(
                "SELECT id, content_hash FROM document_chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
        }
        incoming = {chunk.content_hash: chunk for chunk in chunks}

        obsolete = [cid for h, cid in stored.items() if h not in incoming]
        if obsolete:
            store.remove_chunks(self.conn, obsolete)
            placeholders = ",".join("?" * len(obsolete))
            self.conn.execute(f"DELETE FROM document_chunks WHERE id IN ({placeholders})", obsolete)
            report.chunks_deleted += len(obsolete)

        new_chunks = [chunk for h, chunk in incoming.items() if h not in stored]
        if new_chunks:
            vectors = await self.embedder.embed([c.content for c in new_chunks])
            if vectors and len(vectors) != len(new_chunks):
                # Pairing by position is only valid if the counts match; a short
                # response would silently attach each vector to the wrong chunk.
                raise EmbeddingError(
                    f"embedder returned {len(vectors)} vectors for {len(new_chunks)} chunks"
                )
            if vectors:
                store.ensure_indexes(self.conn, len(vectors[0]))
                store.record_embedding_model(self.conn, self.embedder.provider, self.embedder.model)

            for chunk, vector in zip(new_chunks, vectors or [None] * len(new_chunks), strict=False):
                cursor = self.conn.execute(
                    "INSERT INTO document_chunks (document_id, chunk_index, heading_path,"
                    " content, content_hash, token_count) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        document_id,
                        chunk.index,
                        chunk.heading_path,
                        chunk.content,
                        chunk.content_hash,
                        chunk.token_count,
                    ),
                )
                store.index_chunk(
                    self.conn, cursor.lastrowid, chunk.content, chunk.heading_path, vector
                )
            report.chunks_added += len(new_chunks)

        self.conn.commit()
        report.indexed += 1
        return len(new_chunks)

    def _prune_missing(self, root: Path, present: set[str], report: IndexReport) -> int:
        rows = self.conn.execute(
            "SELECT id, path FROM documents WHERE path LIKE ?", (f"{root}%",)
        ).fetchall()
        removed = 0
        for row in rows:
            if row["path"] in present or Path(row["path"]).exists():
                continue
            chunk_ids = [
                r["id"]
                for r in self.conn.execute(
                    "SELECT id FROM document_chunks WHERE document_id = ?", (row["id"],)
                ).fetchall()
            ]
            store.remove_chunks(self.conn, chunk_ids)
            self.conn.execute("DELETE FROM documents WHERE id = ?", (row["id"],))
            report.chunks_deleted += len(chunk_ids)
            removed += 1
        self.conn.commit()
        return removed

    def mark_stale(self, path: str | Path) -> None:
        """Flag a document for re-indexing.

        PSOK's own write_file and edit_file tools call this, so a file the agent
        changed mid-conversation does not wait on a filesystem watcher.
        """
        self.conn.execute(
            "UPDATE documents SET stale = 1 WHERE path = ?",
            (str(Path(path).expanduser().resolve()),),
        )
        self.conn.commit()

    def stats(self) -> dict[str, int]:
        documents = self.conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
        chunks = self.conn.execute("SELECT COUNT(*) AS n FROM document_chunks").fetchone()["n"]
        return {"documents": documents, "chunks": chunks}
