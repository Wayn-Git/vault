# Automations

**Status: beta.** Shipped deliberately incomplete, and marked as such everywhere
it appears. What follows is what it does, and — more usefully — the two
decisions that were made rather than deferred, because both are surprising and
both are the reason this is small.

## What it is

A prompt, an interval, and a record of what happened. An automation runs as an
ordinary turn, in a conversation of its own, through the same agent loop as
anything typed into the composer. There is no second execution path: "run now"
uses the scheduler's path exactly, because a test run behind a different gate or
a different director would tell you nothing about whether the scheduled one will
work.

`automations` holds `next_run_at` rather than deriving it. "When does this run"
is then one read, and does not depend on the evaluator and the interface
agreeing about arithmetic.

## Decision 1: who decides it is time

**This process, while `psok serve` is running.** A background task wakes every
thirty seconds, reads the due rows off an index, and runs them one at a time.

The alternative — a cron-like daemon independent of the API — keeps automations
running when nothing is up to serve them, and the question that settles it is
what such a daemon does with a turn that needs a permission answer at 3am. It
cannot ask anyone. So it either hangs, or it decides on the user's behalf, and
both are worse than not running.

Tying automations to the server makes the rule "automations run while PSOK is
open", which fits in a sentence, is true, and is printed on the page.

Runs are rescheduled from *now*, not from the time they were due. A server that
was off for a day comes back and runs an hourly automation once, not twenty-four
times.

One at a time, and with a five-minute ceiling per run: three automations coming
due in the same minute and all reaching for the shell are three unattended turns
competing over one machine, and a hung one must not wedge the runner for the
rest of the session.

Below five minutes an "automation" is a busy loop wearing a schedule — 1440
model calls a day by accident — so the interval floor is five minutes and the
ceiling is thirty days.

## Decision 2: what the permission gate does with nobody watching

**It denies, and says what it denied.**

Standing approvals are evaluated before the gate's callback is ever reached, so
an automation can do anything the user has deliberately marked "don't ask
again", and every low-risk tool. Anything else is refused.

The refusal is a *denial*, not an exception. The first version raised, which
read correctly and was wrong: the agent loop turns any exception into a failed
turn, so a scheduled run that wanted one thing it could not have reported
nothing but a stack-trace-shaped string and did none of the rest of its work.
This was found by running one, not by reading it. A denial is something the loop
already handles — the model is told the call was refused and carries on — and
the refused operation keys are collected so the run can name them afterwards.

A run that refused anything records `blocked` rather than `ok`, even if the turn
otherwise finished, and its summary names the operations:

> needs permission for `write_file`, `run_shell_command:write-only`. Approve
> each once from a conversation with "don't ask again" and this will run
> unattended.

That is the intended workflow: approve the specific operation, once, deliberately
— not a flag that exempts scheduled work from the gate, which is the same thing
as not having one.

The gate an automation runs behind is its own. `ToolRegistry.with_confirmation`
returns a view sharing the same tool dict — by reference, so a connector that
reconnects mid-session stays reachable — with a different `ConfirmationService`.
Swapping the callback on the shared registry would change the rules for every
interactive turn running at that moment.

## What this is not, and must not be claimed to be

- **No cron expressions.** An interval, from a fixed list.
- **No trigger other than the clock.** Not "when a file changes", not "when mail
  arrives".
- **No retries.** A failed run reschedules normally; it does not back off or
  try again sooner.
- **Nothing that can answer a permission prompt.** See above. If that changes,
  it needs its own design, not a flag.

## Endpoints

| Need | Endpoint |
|---|---|
| List (with `beta: true`) | `GET /api/automations` |
| Create | `POST /api/automations` |
| Enable, pause, retime, reword | `PATCH /api/automations/{id}` |
| Delete | `DELETE /api/automations/{id}` |
| Run one now, on the scheduler's path | `POST /api/automations/{id}/run` |

Deleting an automation keeps the conversations it wrote: the transcript of what
it did outlives the rule that produced it.
