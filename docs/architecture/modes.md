# Two modes, and a loop that says what it is doing

Built 2026-08-28. [turns.md](turns.md) is how a turn always resolves; this is
what a turn is *allowed* to do, and what it tells you while it does it.

## Plan mode was eight lines in one file

`Chat.jsx` prepended a sentence to the user's message —

> *"Plan first: list the steps you intend to take and what each one will touch,
> then stop and wait. Do not write files or run commands this turn."*

— and sent an ordinary turn. The backend had no reference to plan mode at all.
Three things followed:

1. **Nothing stopped a write.** The tool schemas, the permission gate and
   dispatch were byte-for-byte identical to a chat turn. The only thing between
   plan mode and a deleted file was the model choosing to obey prose.
2. **The sentence was persisted.** It was part of the user's message, so it
   went into the transcript and was replayed on every later iteration of that
   turn and every later turn in the conversation. A conversation asked for a
   plan once kept being asked for one forever.
3. **The result was prose.** An interface cannot offer "Approve" on a paragraph.

## The mode is a field

`TurnRequest.mode` — `chat` or `plan`, rejected with a 400 before the stream
opens if it is anything else, the same way an unknown provider is. `Director`
takes `mode`. The instruction goes on the **system prompt**, where it is not
persisted, and the transcript holds the user's message unedited.

## Read-only is enforced by the registry

`RiskLevel.LOW` already means "changes nothing, runs without asking" — the
permission gate has trusted that judgement since it shipped, and every mutating
builtin is MEDIUM or HIGH: `write_file`, `edit_file`, `delete_file`,
`run_shell_command`, the calendar and task writers, and the desktop tools that
open things at a real person.

So read-only is not a new axis that had to be invented. Two halves:

- `registry.schemas(read_only=True)` withholds every non-LOW tool.
- `ToolContext.read_only` makes `dispatch` refuse one named anyway — from an
  earlier turn, or invented.

The refusal is checked **before the permission gate**, deliberately: a plan turn
must not be able to raise a confirmation prompt either. An approval dialog for a
write the user has not agreed to yet is worse than the write being declined.

Gating on risk rather than on a list of tool names means a connector's tools are
covered on the day it is added, with no list to forget to update.

## The plan comes back as a tool call

`submit_plan` — offered only in plan mode, never registered in the shared
registry, and intercepted by the director rather than dispatched, because it
changes nothing and so there is nothing to dispatch.

The alternative is asking for a numbered list and parsing the answer, which
turns every model that writes `1)` instead of `1.` into a bug report. A tool
call is the structured channel this system already has. `parse_plan` still
salvages a sloppy call — a model that returns a bare string where an object was
asked for has told us the step, and dropping it over formatting wastes the turn.

The plan is emitted as a `plan` frame **and** persisted as the assistant's own
words. The frame is what the interface renders; the transcript is what the
*model* reads on the executing turn, and "approved" means nothing if the thing
approved is not in the history.

**Approval is an ordinary turn.** The UI sends `Approved. Carry out the plan.`
in `chat` mode. There is no special endpoint because there is nothing special
about it, except that the model has already said what it is going to do.

**Steps are editable before approving.** An edited plan travels *with* the
approval rather than relying on history: the model's original is already in the
transcript, so sending only "approved" after the user rewrote a step would
approve the plan they just changed. Discard is local — nothing ran, so there is
nothing to undo, and the plan stays in the transcript because the model said it.

## Progress through an approved plan

`step_started` / `step_done`, from the model's own `begin_step` calls.

The alternative was inferring the current step from which tools were called,
which is inventing a progress bar — and an invented one is worse than none. So
the executing turn is offered `begin_step` (only when it is carrying one out; a
tool with nothing to describe is one models call anyway), and its system prompt
asks for a call as each step begins. It changes nothing, so like `submit_plan`
it is answered by the director rather than dispatched.

Two properties that keep it honest:

- **A step closes when the next one opens**, or when the turn ends. A model that
  starts a step and never mentions it again leaves it open rather than the
  interface claiming it finished.
- **A model that ignores the tool produces no step events**, and the card simply
  shows no progress. Nothing is guessed to fill the gap.

Decided with the user: **explicit toggle, no classifier, no auto-escalation.**
Chat mode stays a single fast pass and pays nothing — no plan tool in its
schemas, no instruction on its prompt.

## `status` frames

A closed vocabulary, `director.STATUSES`:

`retrieving · recalling · thinking · planning · generating · tool · connector ·
retrying · switching · completed · cancelled · failed`

Every one of these already happened inside the loop and none of it was visible.
The composer said "Thinking" from the moment a turn opened until the first token
arrived, whether the three seconds went on the vault search, a cold connector, a
provider retry, or the model. Now it says which — and for `tool` and `connector`
it says what.

Closed on purpose: an interface can style a known set, and a state added on the
server without deciding what to call it shows up as its raw name rather than
silently reading as something else.

## The turn-cost line

`2 steps · 1 tool · 57ms`, from the `done` frame's `steps` / `tools` /
`duration_ms`.

`execution_logs.duration_ms` has held the per-tool half since logging shipped
and nothing has ever read it. Attached to `done` rather than left in a table,
because "why did that take two minutes" is asked immediately or not at all.
Rendered quietly — interesting the first time a turn feels slow, noise every
other time.

## Unknown frames are no longer silent

`Chat.jsx`'s reducer ended in `default: break`, so a frame added on the server
vanished without trace — which is how you spend an afternoon wondering why the
backend's new event "does not arrive". It arrives. It is now logged.

## Verified

- 18 tests in `tests/test_modes_and_status.py`; 503 in the suite; `ruff` clean;
  frontend lint and build clean.
- End to end against a real HTTP provider and a real file on disk, the same
  request in both modes, with the model trying to write in **both**:
  - **chat** — one pass, `write_file` ran, the file is on disk, `done` carried
    `2 steps · 1 tools · 57ms`;
  - **plan** — a two-step plan came back, **nothing was written**, and the
    schemas offered 12 tools with `write_file` and `run_shell_command` absent;
  - a `write_file` dispatched with `read_only=True` was refused with *"changes
    things, and this turn is planning rather than acting"* — **by the registry**,
    which is the verification this phase was specified with — while
    `list_files` still ran.
- Step reporting: two `begin_step` calls produced `step_started` 1, 2 and
  `step_done` 1, 2 — the first closing when the second opened, the second at
  the end of the turn. A step started and never mentioned again still closed
  exactly once, at the turn's end, rather than mid-turn on a guess.
- A test now fails if any name in `STATUSES` is never emitted, which is how
  `generating` was found sitting there as a reserved slot.

## Not built, on purpose

- **`syncing` as a turn state.** The spec's status list named it, but nothing
  inside a turn syncs — the Microsoft To Do mirror runs on its own fifteen-minute
  loop and on `POST /api/tasks/sync`, neither of which is a turn. It is a
  *connector* state and lives in [connectors.md](connectors.md). A name in
  `STATUSES` that nothing emits would be a reserved slot, and a test now fails if
  one appears.
- **Adding or reordering plan steps.** Titles are editable; the shape is not.
  Adding a step the model never proposed is writing a plan rather than approving
  one, and it would arrive with no detail and no tools.
- **A classifier that picks the mode.** khoj's `aget_data_sources_and_output_format`
  is the router deliberately not built here: it costs a round trip on every
  message, and the toggle is one click.


## A third mode, and a fourth thing the model can say (2026-08-29)

`reasoning` joined `chat` and `plan`. It is not plan mode with a bigger model:
plan mode withholds mutating tools and hands back something to approve, and
reasoning mode does neither — it runs the ordinary loop on the `heavy` tier
(`psok/config.py`), which is the model the user chose to wait for.

**Tiers are not the fallback chain.** `psok/runtime/chain.py` answers "this
provider is down, who else"; a tier answers "how hard is this work". Reading
them as one thing would make a quota trip look like a decision the model made,
and an escalation look like an outage.

**The escalation protocol** is the third of its kind, after `submit_plan` and
`begin_step`, and it works the same way: a tool the director offers, never
registers, and answers itself. The fast model calls `escalate(reason)`; the turn
ends with an `escalation` frame; nothing has run. The interface names both
models and offers Escalate or Answer anyway, and **both re-send the same
message** — in `reasoning` mode or in `chat`. There is no resume endpoint,
because there is nothing to resume, and no "do not ask again" flag, because the
escalation is persisted as the assistant's own words and the director reads the
transcript. That survives a reload; a flag in the browser would not.

Rejected on the way here, both already rejected once in this document for
chat-versus-plan: a **classifier**, which costs a round trip on every message to
answer a question most messages do not raise, and a **heuristic** on message
length or file mentions, which guesses silently. The model is the only party
that knows it is out of its depth. The cost of that choice is the one
`begin_step` was accepted with: a model that never calls it produces no
escalations, rather than wrong ones.

Withheld when no `heavy` tier resolves — an offer PSOK cannot honour is worse
than no offer — and withheld on a turn whose transcript already carries an
escalation request, or "Answer anyway" would ask the same question forever.

