# ADR-0003: Vector Storage

## Status

Proposed

## Context

Retrieval needs similarity search over document-chunk and memory embeddings. Khoj uses pgvector inside its single Postgres instance. PSOK uses SQLite as its primary engine (ADR-0002). See [data-model.md](../data-model.md).

## Decision

Store embeddings in the same SQLite database using the `sqlite-vec` extension, in tables logically separate from but physically alongside relational chunk/memory metadata. Document a scaling escape hatch — a dedicated embedded vector engine such as LanceDB — for use only if a user's corpus exceeds roughly one to five million vectors, and confine any such migration to the retrieval repository layer.

## Alternatives Considered

- **A separate hosted or embedded vector database from day one (Qdrant, Chroma, LanceDB).** Rejected as premature: adds a second engine and a cross-engine join between chunk metadata and embeddings for a scale PSOK's personal-use case does not reach.
- **No vector search, keyword-only retrieval.** Rejected: semantic search over personal notes and documents is core to the product's value.

## Trade-offs

`sqlite-vec` is less mature and has a smaller ecosystem than dedicated vector databases; acceptable given PSOK's expected corpus size. The escape hatch is real but unbuilt — it is a documented path, not a fallback that has been implemented and tested.

## Consequences

Embeddings and their relational metadata (chunk text, document reference, content hash) live in one transactional store, so retrieval queries never need a cross-database join. Retrieval code is written against a repository interface, not raw `sqlite-vec` calls, so the escape hatch remains low-cost if it is ever exercised.
