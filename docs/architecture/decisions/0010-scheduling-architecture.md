# ADR-0010: Scheduling Architecture

## Status

Proposed

## Context

PSOK must turn requests like "finish my ML assignment tomorrow" into actual persisted schedule data, without relying on the model to perform date arithmetic or conflict resolution, both of which language models perform unreliably. See [scheduling.md](../scheduling.md).

## Decision

Split responsibility: the model extracts intent and structured-but-fuzzy fields (title, a date hint, an optional duration and priority) via ordinary tool calls; a dedicated deterministic SchedulingEngine performs all date resolution and conflict detection. The model never computes or persists a timestamp itself. Ambiguity or conflicts are returned as structured data through the loop for the model to act on, never silently guessed by a tool.

## Alternatives Considered

- **Let the model compute dates directly and pass a resolved timestamp as a tool argument.** Rejected: language models are unreliable at exact date arithmetic, especially relative to the current date and the user's timezone, and an incorrect timestamp silently persisted is a worse failure than a tool that asks for clarification.
- **A full constraint-solver auto-scheduler in v1.** Rejected as premature scope: nothing in the brief's examples requires multi-task optimization, and a greedy free-slot scan is sufficient for the stated use cases.

## Trade-offs

Structured round-tripping through the loop for ambiguous cases costs an extra model turn compared to a tool that guesses; accepted because an incorrect silent guess in scheduling data is a worse user experience than one extra confirmation exchange.

## Consequences

Scheduling correctness does not depend on model date-arithmetic reliability. `tasks.due_at` and `tasks.scheduled_at` are modeled as distinct fields (see [data-model.md](../data-model.md)) because the split responsibility model depends on being able to represent "due" and "planned work time" as different facts.
