# ADR-0004: Storage Architecture (Multi-Store Split)

## Status

Proposed

## Context

The brief explicitly warns against assuming all data belongs in one store. Khoj puts everything in one Postgres instance including discarding original document bytes; the opposite extreme of many specialized engines adds operational burden a single-user system does not need. See [data-model.md](../data-model.md) for the full per-data-type table.

## Decision

Split PSOK's data across exactly three mechanisms, each chosen because the other two are actively wrong for that specific data type: SQLite for everything relational, searchable, and transactional (app state, tasks, calendar, conversations as normalized messages, document index, chunk embeddings, memories, integration metadata, audit logs); the local filesystem for the user's original documents, treated as source of truth rather than discarded after text extraction; the OS keychain for every credential, with only a reference stored in SQLite.

## Alternatives Considered

- **One store for everything (Khoj's model).** Rejected: forces documents into the database as extracted text only (losing re-derivability), and forces secrets into the same store as application data (a real security downgrade even encrypted at rest).
- **A store per data type (relational DB, document store, secret manager, vector DB, cache) from day one.** Rejected: more operational surface than three mechanisms justify at this scale; most of these data types share SQLite's transactional and relational needs and gain nothing from separation.

## Trade-offs

Keeping documents on the filesystem means the index can drift from disk state without deliberate synchronization (addressed by a filesystem watcher, explicit re-scan, and tool-triggered invalidation — see [data-model.md](../data-model.md#filesystem-and-index-consistency)). Keychain-based credential storage depends on the OS keychain being available and correctly configured, which is a reasonable assumption on desktop platforms.

## Consequences

Each mechanism has a single, defensible reason to exist, documented per data type. No data type's placement is a default — it is a decision recordable in the table this ADR points to.
