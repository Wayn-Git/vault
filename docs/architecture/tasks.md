# Tasks

The task store is a mirror of Microsoft To Do when an account is signed in, and
a standalone list when none is. Both directions sync. This file records the
decisions that are surprising, and the one line that caused most of the work.

## The line

`psok/sync/microsoft_todo.py` used to declare

```python
def _apply(repository, report, task_list: dict, item: dict) -> None:
```

and never reference `task_list` again. PSOK read the user's To Do lists, counted
them into the sync report, passed each one down — and dropped it. Every task
collapsed into one flat set, every task PSOK created went to whichever list
Graph flags `defaultList`, and `create_task` had no list parameter at all, so
"add milk to groceries" could not work even in principle.

Everything below follows from fixing that.

## Buckets are queries, never state

My Day, Missed, Important and General are `WHERE` clauses in `TaskRepository`,
not columns. Missed in particular:

```sql
status IN ('todo','in_progress') AND due_at IS NOT NULL AND due_at < date('now')
```

A stored `missed` flag would need a job to set it, a rule to unset it, and a
migration for rows predating both — and would be wrong for exactly as long as
that job was not running. A query is right at the moment it is asked.

The counts and the rows come from the same predicate, used twice
(`_bucket_where`). A rail saying `Missed 5` above a list of four is not a state
this can reach.

## My Day rides on a category, because To Do's own is not in its API

Verified against the live account on 2026-08-28, four independent ways, none of
them from the documentation:

- `$select=showInMyDay` and `$select=isInMyDay` both fail on **v1.0 and beta**
  with `Could not find a property named ... on type 'microsoft.graph.todoTask'`.
- The live `beta/$metadata` defines twenty-one properties on `todoTask` and
  **not one contains "day"**.
- There is no `myDay` well-known list — the account returns `defaultList`,
  `flaggedEmails` and `none`.
- The legacy `/me/outlook/tasks` surface is still alive on this account and has
  no such field either; every MAPI extended-property probe came back empty.

**Settled by controlled comparison on 2026-08-28.** The user named the five
tasks that were in their My Day at that moment; comparing those five against the
other 52 across both APIs and every field found **no field present only on My Day
tasks, and no field whose values separate the two groups.** The only fields
unique to the non-My-Day group were `completedDateTime`, `dueDateTime` and
`recurrence` — ordinary task properties. My Day lives in To Do's client, not its
API, and no amount of work on this side reaches it.

**So the carrier changed rather than the feature being dropped.** `categories`
does round-trip — readable on the pull, writable on create and update — so the
sun toggle writes a `My Day` tag on the task. Proven both directions against the
real account: pressing the sun put `categories: ['My Day']` on the task read
straight back from Graph, and tagging it in To Do set `my_day_on` on the next
sync. Removing it follows in both directions.

It is a tag *beside* To Do's My Day, not the same list, and the page says
exactly that rather than implying they are one thing.

Two properties this has to hold, both of which cost a real bug if dropped:

- **The push merges, it does not replace.** Graph's `categories` write is
  all-or-nothing, so sending `["My Day"]` would delete every other tag the user
  had. `external_categories` stores what the last pull saw so the push can add
  to it.
- **A pull never clears My Day off a row whose push has not landed.** The push
  runs first and clears `dirty_at` on success; a row still dirty is one whose
  change never reached To Do, and clearing it there would silently undo the
  button the user just pressed.

`my_day_on` is a **date**, not a flag, so the bucket is still a local-calendar
idea; a tag that is still upstream refreshes it to today on each pull.

## What is in My Day

Four things, and the last one is easy to forget:

- put there by hand (the sun, or the `My Day` tag in To Do),
- scheduled for today,
- due today,
- **finished today.**

That last clause exists because My Day showing only what is *left* makes it empty
by the evening of a day you actually got things done — which reads as the page
being broken rather than as the work being over. It is kept as its own clause
because everything else in My Day is an open task and this deliberately is not.

`completed_at` is what makes it possible, and the sync did not import it until
2026-08-28: To Do knew three tasks had been finished that day and PSOK had
recorded the completion time of one, so "what did I get done today" could not be
answered from local data at all. `_apply` now maps `completedDateTime`.

My Day is still the one bucket nothing else fills on its own, which has a
consequence worth stating: **it starts empty until someone chooses.** It was briefly the
default landing view, and on a machine with nothing due today that is an empty
room — which reads as a broken page, not an empty one. So every row carries the
toggle, the empty state offers the overdue list as somewhere to start, and the
view lands on My Day only when My Day has something in it.

## Important is not priority

`important` is the user's flag; `priority` is To Do's `importance` and is what
the model guesses. They are separate columns because an important task with no
deadline and no priority is a normal thing, and because a model should not be
able to promote something into the user's Important list.

Going out, To Do has one axis where PSOK has two: `important` wins, and
`priority` only speaks when the user has not flagged the task.

## Push, then pull

A local edit sets `dirty_at` and returns. It is **not** written through inline:
a checkbox must not wait on a network round trip, and an edit must not be lost
to a failed one.

The sync then pushes every dirty row before pulling anything. That order is what
removes the need for a merge algorithm — by the time the pull runs, upstream
already holds the local change, so "last write wins" and "the local change wins"
are the same outcome. `_apply` clears `dirty_at` on update for the same reason.

A push that fails leaves the row dirty and is retried next tick. One unwritable
task must never stop every other task from syncing.

## Creating upstream is at-least-once

Graph offers no idempotency key, and the Graph call can succeed while the local
`adopt_external` fails — a crash, a rolled-back write. The next tick then
creates a second copy in the user's real account. This was observed, not
theorised: two duplicate tasks appeared during testing.

So the push looks before it leaps: one listing per target list, only when there
is something to create, and a title that already exists upstream is **adopted**
rather than created again. The match is popped as it is used, so two local rows
with one title cannot both claim the same upstream task.

## List names are folded, not matched literally

Real To Do lists are called `🛒 Groceries` and `📚 College`. Nobody types the
emoji. `_fold_list_name` strips leading symbols and case before matching, so
"groceries" finds the list — without it, asking for "groceries" created a
*second* list by that name and split the user's shopping across two places, one
of which never reached their phone.

Matching is exact, then folded, then a unique folded prefix. Two candidates
after folding is **not** a match: putting a task in one of two plausible lists
is worse than asking.

## A local list is healed, not left behind

A list created while nothing was signed in has no `external_id`. A task filed
into it goes upstream to the *default* list, so the next pull refiles that task
into the default list and the user's chosen list quietly empties itself.

`TaskService._adopt` gives such a list an upstream identity the first time it is
used with an account connected, and `_sync_lists` adopts a local list by name
rather than creating a duplicate beside it.

## Deletion stays one-way

A task that vanishes upstream is `cancelled`, never deleted, and so is a list.
An outage and an emptied account produce the same empty response and only one of
them is recoverable. `sync` raises before `_retire_missing` when the list
listing came back empty, so an outage cannot cancel everything.

PSOK's own delete is also a cancel: a mirrored row deleted locally comes
straight back on the next pull, so deleting one is a lie that lasts fifteen
minutes.

## One service, three callers

`psok/tasks/service.py` owns hint resolution, conflict checking, list
resolution, the local write and the upstream mirror. The agent's tools, the HTTP
API and the sync are thin adapters over it.

There used to be three implementations, and the drift was visible from outside:
the browser composer could express less than the API, which could express less
than the tool, and none of them could name a list.

## Timestamps

Local naive, compared as strings by SQLite, everywhere. Two writers once
disagreed about the separator — the sync used a space and the API path used
`datetime.isoformat()`, which uses `T`. Sorting survives that, which is why it
went unnoticed; the reminder scan does not, because `T` is `0x54` and a space is
`0x20`:

```
'2026-08-27T09:00:00' <= '2026-08-27 11:30:00'   -- false
```

A reminder written in the `T` form was skipped on every tick until the date
rolled over. `_normalise_task_timestamps` fixes existing rows on migrate; the
single write path keeps new ones consistent.

## Pagination

`list_task_lists` and `list_tasks` both take `cursor` / `maxResults` and return
one page. Reading only the first silently truncated any list past the page size
— and a truncated pull is indistinguishable from tasks having been deleted,
which `_retire_missing` would then cancel. `_paged` is therefore not an
optimisation; it is what stops a large list cancelling itself.

## Deliberately not built

- **Recurrence.** Graph's `recurrence` is never requested, and no column
  reserves a place for one.
- **Steps / subtasks.** The connector exposes `checklistItems`; nothing reads
  them yet.
- **Hard delete.** See above.
- **Using To Do's own My Day list.** No field for it exists in Graph; four
  routes were checked live. The `My Day` category is the round-trip that does
  work. See above.
