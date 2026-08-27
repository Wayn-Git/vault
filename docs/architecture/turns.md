# A turn that always resolves

Fourteen places were found where a turn could end with the interface stuck or
blank. They fall into three groups, and the fixes are recorded here because each
one looked like a different bug from the outside.

## The model that was never there

`Chat.jsx` sent the literal string `default` as the model whenever
`/api/health` had not answered yet. It reached the provider verbatim; NVIDIA
replies `404 page not found`. Five conversations in the real database carried
it, every turn in them failed forever, and nothing in the interface offered a
way to correct one.

Three changes, because any one alone leaves a hole:

- The composer no longer invents a name. An empty field is sent empty.
- `_validate_model` fills in the provider's declared `default_model` for an
  empty or placeholder value, and refuses with a 400 when the provider declares
  none. A rejected send beats a dead conversation.
- `_repair_placeholder_models` repoints the rows that predate the refusal, on
  migrate. Nobody should have to find the `⋯` menu to undo a bug.

The frontend also stopped naming a preferred provider. `FALLBACK_PROVIDER =
'nvidia'` made every other provider a second-class citizen of the composer's own
defaulting.

## Silence is not an answer

Three guarantees, at three layers:

**The loop always says how it ended.** `Director.run` caught `Exception`, which
does not include `CancelledError` — raised on a server shutdown, a reload, or
Starlette dropping the task. A generator that raises out of an already-open SSE
response ends a 200 body with no terminal frame, which a browser cannot tell
from a truncated download.

**The endpoint checks.** If the loop returns without a terminal frame, the SSE
generator sends one saying so rather than closing the body and leaving the
reader to guess.

**The reader gives up eventually.** `reader.read()` has no timeout, so a loop
wedged on a dead socket left `turnState` at `running` forever: composer
disabled, conversation switching refused, and Stop disabled too once pressed.
A page reload was the only exit. A watchdog reset by *every* frame — not just
text, since a tool call can take minutes and say nothing — fires after three
minutes of complete silence. And a clean close with no terminal frame now
pushes a note instead of letting the turn evaporate.

## Stop that stops

The cancel event was read in exactly three places, and none of them covered the
model call. Pressing Stop during a round trip did nothing until it returned:
with `timeout=120.0` and `MAX_RETRIES = 3`, up to about eight minutes.
`_delay_for` honours an arbitrary `Retry-After`, so a `429; Retry-After: 300`
made Stop unresponsive for five minutes on its own.

- `_race_cancel` races any awaitable against the stop request and **cancels** the
  loser, which propagates into httpx and aborts the request rather than
  abandoning a response that keeps arriving.
- `_stream_until_cancelled` races every `__anext__`, not just the gaps between
  chunks — the wait before the first byte is the long one, and the one a
  per-chunk check cannot see.
- `MCPConnection._serve` carries the caller's cancellation through to
  `session.call_tool`. Abandoning the waiter is not abandoning the work, and
  because that queue is serial, an abandoned call blocked the *next* call to
  that connector for its full timeout — a stall in the following turn with
  nothing to explain it.
- `run_shell_command` kills its subprocess on cancellation. It used to leave it
  running with its pipes unread, still doing whatever the model asked, after the
  turn that asked was over.
- `_active_turns` is registered **before** the director is built. Building it can
  start connectors, and during that window `POST …/turn/stop` answered 404 — the
  one case where Stop genuinely could not work.

Measured against the real provider: stream ends about a second after the
request, with a `guard` frame.

## Streaming honesty

- **Reasoning is not an answer.** The empty-stream fallback required text,
  reasoning *and* tool calls to all be empty. A thinking model that spent its
  budget in `reasoning_content` and stopped skipped the fallback, burned both
  continuations, and ended the turn on an empty bubble.
- **Malformed frames are counted.** They were dropped silently, so a provider
  emitting subtly broken JSON produced a blank answer with no diagnostic.
- **Anthropic can fail over an open 200 too.** It had no `error`-frame branch at
  all, so an `overloaded_error` mid-stream matched nothing and was discarded.
- **A partial answer is persisted.** Only `[model error] …` was written, so text
  the user could read on screen vanished on reload.
- **A full stream replay is logged.** `started == False` replays the whole
  request; unlogged, a turn could cost four times the tokens and wall clock with
  no trace.
