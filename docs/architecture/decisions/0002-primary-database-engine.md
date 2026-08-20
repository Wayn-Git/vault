# ADR-0002: Primary Database Engine

## Status

Proposed

## Context

PSOK is a single-user, local-first application with no operations team. Khoj's architecture (researched in [khoj.md](../../research/khoj.md)) uses a client-server PostgreSQL instance with pgvector for everything. See [data-model.md](../data-model.md).

## Decision

Use embedded SQLite (WAL mode) as the primary database, not a client-server database. One file, no service to run, backup is a file copy.

## Alternatives Considered

- **PostgreSQL, as Khoj uses.** Rejected: requires a running database service, a port, credentials, and an operations story that a single-user local application should not need before its first message.
- **A polyglot mix of engines from the start (a relational DB plus a separate vector DB plus a document store).** Rejected as premature: adds operational surface (multiple processes, multiple backups, cross-engine consistency) with no evidence PSOK's scale requires it.

## Trade-offs

SQLite has weaker concurrent-write characteristics than a client-server database; addressed via WAL mode and small transactions in background workers (see [data-model.md](../data-model.md#consistency-and-concurrency)). SQLite is not the right choice if PSOK ever becomes a multi-user hosted service — that would be a distinct deployment mode requiring its own decision, not a reason to complicate the local-first default now.

## Consequences

Zero-configuration startup. Trivial backup and portability (copy one file). A documented escape hatch exists if scale ever demands otherwise, but is not built until needed.
