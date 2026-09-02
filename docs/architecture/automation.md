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

One at a time, and with a three-minute ceiling per run (`RUN_TIMEOUT_SECONDS =
180`): three automations coming due in the same minute and all reaching for the
shell are three unattended turns competing over one machine, and a hung one must
not wedge the runner for the rest of the session. Because the runner is serial,
that ceiling is also how long one stuck automation can delay everything queued
behind it, which is why it came down from five minutes. An unattended turn is
allowed twenty iterations (`AUTOMATION_MAX_ITERATIONS`), more than an
interactive one because a browser task spends one per tool call and nobody is
there to say "carry on" — and no more than fits inside the timeout.

The runner wakes every ten seconds (`TICK_SECONDS`) and the interval floor is
one minute (`MIN_MINUTES`); the ceiling is thirty days. Both were looser — a
thirty-second tick under a five-minute floor — and together they meant the
tightest automation PSOK would accept actually fired somewhere between five and
six minutes from now. A minute is still six ticks, so an interval is honoured
rather than approximated, and the tick no longer costs a third of the shortest
period. Below the tick an "automation" would be a busy loop wearing a schedule.

"Run now" ignores all of this. The floor governs how often PSOK starts a run by
itself; a person pressing the button has already decided. It still queues behind
a run in flight, so two unattended turns never share the machine.

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
- **No retry within a run.** A run that fails does not try again sooner; it
  only reschedules later than usual (below).
- **Nothing that can answer a permission prompt.** See above. If that changes,
  it needs its own design, not a flag.

## Tool scope

An automation can be pointed at a saved capability profile
(`backend/capabilities.py`), the same connector on/off snapshot a person saves
from Skills & connectors. When it is, `run_once` applies that profile to the
run's own conversation directly — not through `POST
/api/capabilities/profiles/{name}/apply`, which also connects and disconnects
servers live on the shared MCP manager. A scheduled run must never do that to a
connector another conversation is using, so it only writes the conversation's
own `capability_state` rows, exactly what the Director already reads per turn.

This exists because the tool list is not free: one real setup measured 29,620
tokens across 132 tools, and a provider with a 128-tool cap starts dropping
tools once the catalogue passes it. An automation that only ever needs Gmail
does not need GitHub, Spotify, LinkedIn, and a browser in the same schema list
— narrowing it is what keeps the model from second-guessing the right tool as
the catalogue grows. No profile set means every enabled connector, same as
before this existed. A profile that is deleted after an automation is pointed
at it fails that run loudly, naming the missing profile, rather than silently
running unscoped — a bigger surprise than not running.

## Backing off a broken automation

A run that ends `error` no longer reschedules on the plain interval: each
consecutive failure doubles the wait (capped at the existing thirty-day
ceiling), and one `ok` run resets it to nothing. A `blocked` run — the gate
correctly refusing something it was never approved for — does neither: it is
not progress, but it is not a failure to retry past either, and backing it off
would read as PSOK giving up on approval rather than waiting for it.

This does not make a run retry, or make a flaky provider more reliable. It
means an automation stuck failing every fifteen minutes settles into failing
every few hours instead, so a bad prompt or a dead connector does not keep
spending turns — and, on a provider that is down, keep re-announcing the same
failure — until someone reads the record.

**Provider fallback is a configuration fact, not something this code decides.**
`backend/runtime/chain.py` builds a fallback chain only from providers that
actually have a key; with one provider configured, the chain is length one and
a 5xx there has nowhere to hand off to. An automation created with no explicit
provider now picks the same one a plain chat turn would — the `default:` tier
in `providers.yaml` when one is named, rather than whichever provider happens
to sort first — but that only routes an automation to *a* provider correctly;
it does not give it somewhere to fall back to. The fallback chain still gets
longer only when a second provider actually has a key.

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
