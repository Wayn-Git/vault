# ADR-0017: Conversation/Message Persistence Model

## Status

Accepted

## Context

Khoj stores an entire conversation transcript as a single JSON field on the conversation row, rewritten on every turn. PSOK needs conversation history for context assembly, token-budgeted truncation, and (eventually) cross-conversation search. See [data-model.md](../data-model.md).

## Decision

Store conversations as a `conversations` row plus normalized per-message rows in a `messages` table, with tool calls and tool results as JSON *columns* on those rows. Keep the tool audit trail in a separate `execution_logs` table rather than folding it into `messages`.

## Alternatives Considered

- **One JSON blob per conversation, as Khoj does.** Rejected: history is not queryable, truncation requires deserializing the whole blob, and write cost grows with conversation length because the entire transcript is rewritten each turn.
- **Fully normalizing tool calls and results into their own tables.** Rejected: their shape is provider-shaped and genuinely variable, so a rigid schema would fight the data for no query benefit — JSON columns on a real row give queryable message identity without over-modeling the payload.

## Trade-offs

Two tables instead of one, and message assembly requires a query rather than a single field read; both are trivially cheap in SQLite and buy incremental truncation via a `LIMIT`ed query.

## Consequences

Budgeted history assembly is a bounded query, not a full deserialization. Appending a turn is an insert. `execution_logs` can be pruned on its own retention policy without touching the user's conversation history, which is their data and is kept.
