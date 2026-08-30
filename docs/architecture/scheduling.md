# Scheduling

## The principle

The model interprets; a deterministic engine computes. The model extracts intent, entities, and constraints from natural language — what the task is, roughly when it's due, how it relates to other things. It never performs date arithmetic or conflict resolution itself. Both are delegated to the **Scheduling Engine**, invoked only through tool calls, exactly like every other capability in the system.

This split exists because natural-language date resolution has a correctness bar that model generation does not reliably clear — "tomorrow" depends on the system clock and the user's timezone, not on the model's training data, and getting it wrong by being plausible-sounding is worse than refusing to guess.

## Walking the brief's example

*"Organize my tasks for tomorrow."* And the more specific case: *"Finish my ML assignment tomorrow."*

1. The agent loop recognizes a scheduling-shaped request from the user's message — no special-casing here beyond ordinary tool selection; the model has `create_task` and `find_free_slot` available and reasons about which to call.
2. The model calls `create_task` with **structured, still-fuzzy arguments**: `{title: "Finish ML assignment", due_date_hint: "tomorrow", duration_estimate_minutes: null, priority: null}`. The model's job stopped at extracting these fields — it did not compute a timestamp.
3. **The tool implementation**, not the model, resolves `"tomorrow"` against the system clock and the user's configured timezone using deterministic parsing built on `python-dateutil` — never LLM arithmetic.
4. The tool checks `calendar_events` for conflicts around the resolved date.
5. **If there is no conflict**, it writes a resolved `tasks` row and returns success.
6. **If there is a conflict**, it does not silently pick a time. It returns a structured description of the conflict back through the loop, and the model — now holding real information rather than a guess — can ask the user which slot they'd prefer, or propose an alternative by calling `find_free_slot` next.

This round-trip-through-the-loop behaviour, rather than a tool silently guessing when it hits ambiguity, is the same pattern used everywhere else a tool can fail or need clarification: the tool returns a result the model can act on, and the loop continues.

## The Scheduling Engine's scope

A dedicated module, not spread across tool implementations, owning:

- **Relative-date resolution** — "tomorrow," "next Tuesday," "in two weeks," resolved against the system clock and the user's timezone.
- **Conflict detection** — checking a candidate time window against existing `calendar_events` for overlap.
- **`find_free_slot`** — a simple greedy scan across the calendar for an open window matching a requested duration. v1 scope only.

**Deliberately not built:** recurring tasks, and a constraint-solver that auto-schedules multiple tasks against each other, balancing priorities and durations across a week. That is a meaningfully harder problem than a greedy free-slot scan, and nothing in the brief's examples requires it. It is a stretch-phase item, not a v1 requirement — building it now would be solving a problem PSOK does not yet have evidence anyone needs solved.

## Data model

See [data-model.md](data-model.md) for the full schema. The detail that matters here: `tasks.due_at` (the deadline) and `tasks.scheduled_at` (when the user actually intends to do the work) are **separate columns**. "Due tomorrow" and "I'll work on it at 2pm today" are different facts about a task, and collapsing them into one timestamp would make conflict detection and free-slot search impossible to reason about correctly — a task can be due without having a scheduled work time yet, and vice versa.

`tasks.calendar_event_id` links a task to a calendar event once the task has been materialized onto the calendar (which may not happen for every task — a task can exist with no calendar presence at all).

There is no recurrence support, and no column reserving a place for it. An earlier version of this file claimed `tasks.recurrence_rule` existed; it never did — `git log -S` finds no commit that added it. Corrected 2026-08-27.

`tasks.reminder_at` and `tasks.reminded_at` are a different thing from either. A reminder is one timestamp and one notification, not a schedule: `backend/reminders.py` scans `COALESCE(reminder_at, due_at)` every thirty seconds while `psok serve` runs, claims `reminded_at` with a conditional update, and then notifies — in that order, so a machine with no notification daemon misses one reminder rather than repeating it forever. It fires while PSOK is open, the same rule automations state, and for the same reason.

Both columns are local naive time, like every other timestamp the engine resolves. That is load-bearing and not obvious: SQLite compares these as strings, so a UTC clock on one side of the comparison delivers every reminder late by the machine's offset.

## How the loop interacts with scheduling

The agent loop never touches `tasks` or `calendar_events` directly. It reaches the Scheduling Engine exclusively through tools — `create_task`, `update_task`, `list_upcoming`, `find_free_slot` — which means scheduling gets the same treatment as every other capability rather than being a special-cased subsystem the loop has bespoke knowledge of:

- The same **permission gate** applies. Creating or moving a task or calendar event is a medium-risk write per the risk table in [security.md](security.md), and confirms by default.
- The same **result normalization and audit logging** applies. A `create_task` call, successful or not, produces a standard result envelope and an `execution_logs` row like any other tool call.
- The same **error-as-data pattern** applies. An ambiguous date, a conflict, comes back as a structured, informative failure the model can act on — never a silent guess and never an unhandled exception.

Scheduling is a capability the agent reaches through the Tool Registry, exactly like document search or an MCP tool. Nothing in the Director's loop code knows that scheduling exists as a distinct thing.
