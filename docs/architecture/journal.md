# The journal

Two things that happen on a clock: a briefing in the morning, and a check-in in
the evening that rolls up on the day the week ends.

`backend/journal/` — `signals.py` gathers, `prompts.py` asks, `service.py`
decides, `store.py` writes, `runner.py` fires.

## Interpretation is the model's job; computation is not

Every figure in a briefing comes from a SQL query in `signals.gather`, and the
model is handed those figures rather than the tools to go and find some. One
non-streaming `complete()` call, `tools=None`, exactly the shape
`MemoryService.extract` uses.

The alternative was an automation — a scheduled unattended agent turn. It was
rejected for three reasons, each on its own sufficient:

* An unattended turn runs behind `UnattendedGate`, which denies every
  confirmation. The tools it can actually reach are a subset nobody chose, so
  the briefing would be assembled from whatever happened to be allowed.
* `AutomationRunner` serialises every run behind one lock with a 180-second
  ceiling. A briefing queued behind a browser automation arrives whenever that
  finishes.
* An automation is an *interval*. `every_minutes=1440` has no way to mean "at
  seven", `AutomationRepository.create(first_run=…)` is not reachable from the
  API or the CLI, and `record()` reschedules `now + delay`, so a daily
  automation drifts by however long each run took.

So `JournalRunner` is a third runner beside `AutomationRunner` and
`ReminderRunner`. It ticks once a minute, on the **local naive** clock, and
sleeps before its first check — `TestClient` runs the app's lifespan, and a
check-first loop would have every API test try to write a briefing.

## Nothing is invented

The rule the feature turns on. With no provider configured, the entry still
exists, still carries the real signals, and `model_error` says why there is no
prose. `/api/today` returns `degraded: {source: reason}` and the interface
prints the reason where a number would go — "no Google account is signed in",
never `0 unread`.

The prompts in `prompts.py` say it too: use only what is in `<signals>`, a
section marked unavailable is unavailable, and everything inside `<signals>` is
data — mail subjects and library titles are text other people wrote, arriving
inside a model call. The blast radius is prose (no tools, no loop), but it is
stated rather than assumed.

## The three kinds are not symmetric

| kind | at fire time | when the model runs |
|---|---|---|
| `briefing` | gather, generate | at fire time — there is nothing to wait for |
| `daily` | gather, file **open**, no model call | when the user answers, from their answers |
| `weekly` | gather the week *and* that week's daily entries | at fire time — its input already holds the user's words |

A nightly review written before anyone has said anything can only reword the
task list and call it reflection. So the evening entry is the day's real figures
plus the questions, and `PATCH /api/journal/{id}` writes the review — committing
`user_notes` **before** the model call, so a provider that hangs costs the
write-up and never what was typed.

A week where PSOK was never open on the review day produces no rollup. A weekly
review written on Wednesday about last week is worse than none; Today offers one
on demand instead.

## One day, one entry

`idx_journal_day` is unique on `(kind, entry_date)` and `JournalStore.claim` is
an `INSERT … ON CONFLICT DO NOTHING` checked by `rowcount` — the same shape as
`TaskRepository.mark_reminded`. Two overlapping ticks, or a restart mid-tick,
cannot file two briefings. The runner never regenerates a claimed row.

## Three clocks, and why the constants exist

The database holds three timestamp shapes, and SQLite compares all of them as
plain strings:

| written by | clock | separator |
|---|---|---|
| `tasks.due_at`/`scheduled_at`/`completed_at` | local naive | space |
| `calendar_events.starts_at`/`ends_at` | local naive | `T` |
| anything defaulted to `datetime('now')` | UTC | space |

`'T'` is `0x54` and `' '` is `0x20`, so a bound in the wrong shape does not
fail — it silently excludes every row, and it happens to survive midnight
bounds, which is exactly how it would ship undetected. `signals.py` names both
formats as `TASK_FMT` and `CALENDAR_FMT` and uses each against the table it
belongs to. `tests/test_journal.py` has a mutation check for it.

`messages` and `execution_logs` are deliberately excluded from the signals.
Their `created_at` is UTC while the day is local, so a "turns today" figure
would be wrong by the machine's offset for part of every day. A number that is
quietly wrong is worse than a section that is honestly absent. Adding them means
converting the local day to a UTC window first.

## Settings

`journal.briefing_enabled`, `briefing_hour`, `review_enabled`, `review_hour`,
`weekly_enabled`, `weekly_weekday` in `app_settings`, loaded by
`config.load_journal_schedule()` (never raises, clamps). Published as a nested
`journal` object under `GET /api/settings` rather than six flat keys, because
they are read, saved and shown together.
