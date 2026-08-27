"""Lists, buckets, and the two-way half of the To Do sync.

Every test here has a mutation check named in its docstring: the change to the
source that makes it fail. A test that cannot fail protects nothing.
"""

from __future__ import annotations

import asyncio

import pytest

from psok.db.repositories import TaskListRepository, TaskRepository
from psok.tasks.service import TaskError, TaskService


def _service() -> TaskService:
    return TaskService()


# --------------------------------------------------------------------- lists


def test_a_task_is_filed_into_the_list_it_came_from(db):
    """The bug this whole feature turned on.

    `_apply` took the list a task belonged to and never referenced it, so every
    task in every list collapsed into one flat set.

    Both halves are checked, because they are separate code paths: a task seen
    for the first time is filed on create, and a task moved between lists in To
    Do is refiled on update.

    Mutation check: replace `local_list` with `None` in either the `create(...)`
    call or the `fields` dict in `_apply`, and one of these fails.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    lists = TaskListRepository()
    groceries = lists.create("Groceries", external_source=SOURCE, external_id="list-g")
    college = lists.create("College", external_source=SOURCE, external_id="list-c")

    repo = TaskRepository()
    item = {"id": "t-1", "title": "Milk", "status": "notStarted"}

    _apply(repo, SyncReport(), groceries, item)
    assert repo.by_external(SOURCE, "t-1")["list_id"] == groceries, "filed on create"

    # The user dragged it to another list on their phone.
    report = SyncReport()
    _apply(repo, report, college, dict(item))
    assert repo.by_external(SOURCE, "t-1")["list_id"] == college, "refiled on update"
    assert report.updated == 1


def test_lists_are_mirrored_renamed_and_retired(db):
    """A list gone from To Do is retired, not deleted -- the tasks still point at it.

    Mutation check: make `_sync_lists` delete instead of retire and the second
    assertion raises a foreign-key-shaped failure instead.
    """
    from psok.sync.microsoft_todo import SyncReport, _sync_lists

    lists = TaskListRepository()
    report = SyncReport()

    mapping = _sync_lists(
        lists,
        report,
        [
            {"id": "l-1", "displayName": "Tasks", "wellknownListName": "defaultList"},
            {"id": "l-2", "displayName": "Groceries"},
        ],
    )
    assert report.lists_created == 2
    assert lists.default()["name"] == "Tasks"

    # Renamed upstream, and the second list gone.
    _sync_lists(lists, SyncReport(), [{"id": "l-1", "displayName": "Inbox"}])
    assert lists.get(mapping["l-1"])["name"] == "Inbox"

    retired = lists.get(mapping["l-2"])
    assert retired is not None, "a retired list is kept; tasks still point at it"
    assert retired["retired_at"]
    assert mapping["l-2"] not in [row["id"] for row in lists.all()]


def test_a_local_list_is_adopted_not_duplicated(db):
    """Signing in must not give the user two lists with the same name.

    Mutation check: drop the orphan-adoption branch in `_sync_lists` and the
    count below becomes 2.
    """
    from psok.sync.microsoft_todo import SyncReport, _sync_lists

    lists = TaskListRepository()
    local = lists.create("Groceries")  # made before anything was signed in

    _sync_lists(lists, SyncReport(), [{"id": "l-9", "displayName": "Groceries"}])

    rows = [r for r in lists.all() if r["name"] == "Groceries"]
    assert len(rows) == 1
    assert rows[0]["id"] == local, "the same row, now carrying its Graph id"
    assert rows[0]["external_id"] == "l-9"


def test_a_list_name_resolves_loosely_but_never_ambiguously(db):
    """"groceries" finds "Groceries"; a prefix matching two lists finds neither.

    Mutation check: make `by_name` return `prefixed[0]` unconditionally and the
    final assertion fails.
    """
    lists = TaskListRepository()
    lists.create("Groceries")
    lists.create("College 2026")
    lists.create("College Admin")

    assert lists.by_name("Groceries")["name"] == "Groceries"
    assert lists.by_name("groceries")["name"] == "Groceries"
    assert lists.by_name("College 2")["name"] == "College 2026"
    assert lists.by_name("College") is None, "two candidates is not a match"


def test_naming_an_unknown_list_creates_it(db):
    """"add milk to groceries" works on a machine that has no Groceries yet."""
    written = asyncio.run(_service().create("Milk", list_name="Groceries"))

    assert written.list_ref.created
    assert written.list_ref.name == "Groceries"
    assert TaskRepository().get(written.task_id)["list_id"] == written.list_ref.id


def test_listing_into_a_named_list_refuses_when_asked_not_to_create(db):
    service = _service()
    with pytest.raises(TaskError, match="no list called"):
        asyncio.run(service.resolve_list("Nowhere", create=False))


# ------------------------------------------------------------------- buckets


def _seed(repo: TaskRepository) -> dict[str, int]:
    return {
        "overdue": repo.create("Overdue", due_at="2020-01-01 09:00:00"),
        "today": repo.create("Due today", due_at=f"{_today()} 17:00:00"),
        "someday": repo.create("No date at all"),
        "flagged": repo.create("Important, undated", important=True),
        "finished": repo.create("Finished", status="done"),
        "dropped": repo.create("Dropped", status="cancelled"),
    }


def _today() -> str:
    from datetime import datetime

    return datetime.now().date().isoformat()


def test_missed_is_computed_not_stored(db):
    """An overdue task appears in Missed with nothing having marked it.

    Mutation check: change `_MISSED` to compare against a stored flag and this
    fails, because nothing sets one.
    """
    repo = TaskRepository()
    seeded = _seed(repo)

    missed = [r["id"] for r in repo.bucket("missed")]
    assert seeded["overdue"] in missed
    assert seeded["today"] not in missed, "due today is not yet missed"
    assert seeded["someday"] not in missed


def test_important_ignores_dates(db):
    """The whole point of the bucket: flagged, with no deadline, still shows.

    Mutation check: add a `due_at IS NOT NULL` term to `_IMPORTANT`.
    """
    repo = TaskRepository()
    seeded = _seed(repo)
    assert [r["id"] for r in repo.bucket("important")] == [seeded["flagged"]]


def test_general_is_only_the_undated(db):
    repo = TaskRepository()
    seeded = _seed(repo)
    general = [r["id"] for r in repo.bucket("general")]
    assert seeded["someday"] in general
    assert seeded["flagged"] in general, "important is a flag, not a date"
    assert seeded["overdue"] not in general


def test_my_day_holds_what_was_put_there_and_what_is_due_today(db):
    repo = TaskRepository()
    seeded = _seed(repo)
    repo.update(seeded["someday"], my_day_on=_today())

    my_day = [r["id"] for r in repo.bucket("my_day")]
    assert seeded["someday"] in my_day
    assert seeded["today"] in my_day
    assert seeded["overdue"] not in my_day


def test_my_day_empties_itself_overnight(db):
    """A date, not a flag, so nothing has to run at midnight to clear it.

    Mutation check: store a boolean instead and yesterday's entry never leaves.
    """
    repo = TaskRepository()
    task_id = repo.create("Yesterday's plan")
    repo.update(task_id, my_day_on="2020-01-01")
    assert [r["id"] for r in repo.bucket("my_day")] == []


def test_completed_excludes_cancelled(db):
    """"Showing done" used to mean "showing everything you gave up on too"."""
    repo = TaskRepository()
    seeded = _seed(repo)
    completed = [r["id"] for r in repo.bucket("completed")]
    assert completed == [seeded["finished"]]


def test_counts_agree_with_the_rows_they_count(db):
    """A sidebar saying 5 over a list of 4 is worse than no count at all.

    Mutation check: give `counts` a different predicate from `_bucket_where`.
    """
    repo = TaskRepository()
    _seed(repo)
    counts = repo.counts()
    for name in ("my_day", "missed", "important", "general", "completed", "all"):
        assert counts[name] == len(repo.bucket(name)), name


def test_completing_a_task_stamps_when(db):
    repo = TaskRepository()
    task_id = repo.create("Ship it")
    repo.update(task_id, status="done")
    assert repo.get(task_id)["completed_at"]

    repo.update(task_id, status="todo")
    assert repo.get(task_id)["completed_at"] is None, "reopening clears it"


# ---------------------------------------------------------------------- push


def test_a_local_change_is_marked_for_the_next_push(db):
    """`dirty_at` is what the push half walks.

    Mutation check: drop the `dirty_at` assignment in `TaskService.update` and
    a task ticked in PSOK never reaches the phone -- which is the bug this
    whole direction exists to fix.
    """
    from psok.sync.microsoft_todo import SOURCE

    repo = TaskRepository()
    task_id = repo.create("Mirrored", external_source=SOURCE, external_id="x-1")

    asyncio.run(_service().update(task_id, status="done"))
    assert repo.get(task_id)["dirty_at"]
    assert [r["id"] for r in repo.dirty(SOURCE)] == [task_id]


def test_a_purely_local_task_is_not_marked_dirty_but_is_unsynced(db):
    """Nothing upstream to update; it needs creating instead.

    The two halves of the push are different calls, and confusing them sends
    an update for a task To Do has never heard of.
    """
    from psok.sync.microsoft_todo import SOURCE

    repo = TaskRepository()
    task_id = repo.create("Local only")

    asyncio.run(_service().update(task_id, title="Local only, renamed"))
    assert repo.get(task_id)["dirty_at"] is None
    assert repo.dirty(SOURCE) == []
    assert [r["id"] for r in repo.unsynced()] == [task_id]


def test_adopting_an_upstream_identity_clears_the_dirty_flag(db):
    repo = TaskRepository()
    task_id = repo.create("Stranded", dirty_at="2026-01-01 00:00:00")
    repo.adopt_external(task_id, source="microsoft-todo", external_id="new-1", external_etag="e")

    row = repo.get(task_id)
    assert row["external_id"] == "new-1"
    assert row["dirty_at"] is None


def test_the_pull_supersedes_a_local_edit_because_the_push_ran_first(db):
    """Push-then-pull is what removes the need for a merge algorithm.

    By the time the pull runs, upstream already holds the local change, so
    anything arriving is newer. Clearing `dirty_at` here is what stops a
    superseded edit being pushed again forever.

    Mutation check: drop `changed["dirty_at"] = None` in `_apply`.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    repo = TaskRepository()
    _apply(repo, SyncReport(), None, {"id": "p-1", "title": "Before", "status": "notStarted"})
    row = repo.by_external(SOURCE, "p-1")
    repo.update(row["id"], dirty_at="2026-01-01 00:00:00")

    _apply(repo, SyncReport(), None, {"id": "p-1", "title": "After", "status": "notStarted"})
    after = repo.by_external(SOURCE, "p-1")
    assert after["title"] == "After"
    assert after["dirty_at"] is None


def test_importance_survives_the_round_trip(db):
    """To Do has one axis where PSOK has two; high importance is the user's flag."""
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply, _task_arguments

    repo = TaskRepository()
    _apply(
        repo,
        SyncReport(),
        None,
        {"id": "i-1", "title": "Taxes", "status": "notStarted", "importance": "high"},
    )
    row = repo.by_external(SOURCE, "i-1")
    assert row["important"] == 1
    assert row["priority"] == "high"

    assert _task_arguments(important=True)["importance"] == "high"
    assert _task_arguments(important=False, priority="low")["importance"] == "low"
    assert "importance" not in _task_arguments()


def test_a_cancelled_task_is_completed_upstream(db):
    """To Do has no cancelled. Leaving it open means it never leaves the phone."""
    from psok.sync.microsoft_todo import _task_arguments

    assert _task_arguments(status="cancelled")["status"] == "completed"
    assert _task_arguments(status="in_progress")["status"] == "inProgress"


def test_a_t_separated_timestamp_is_normalised(db):
    """Mixed separators make a same-day reminder silently never fire.

    `'2026-08-27T09:00:00' <= '2026-08-27 11:30:00'` is false, because SQLite
    compares these as strings and `T` (0x54) sorts above a space (0x20). The
    reminder scan therefore skips the row on every tick until the date rolls
    over and the day digits decide the comparison instead.

    Mutation check: stop calling `_normalise_task_timestamps` from `migrate`,
    or drop a column from `_TASK_TIME_COLUMNS`, and the matching assertion
    fails. The rewrite is deliberately applied to every column of a matched
    row rather than only the `T` ones -- the separator is at position 11 in
    both forms, so it reproduces a correct value exactly, which the second
    assertion pins.
    """
    from psok.db.connection import _normalise_task_timestamps

    repo = TaskRepository()
    task_id = repo.create("Mixed")
    # One column in each form, which is exactly what the two old writers left.
    db.execute(
        "UPDATE tasks SET due_at = '2026-08-27T09:00:00',"
        " reminder_at = '2026-08-27 11:30:00' WHERE id = ?",
        (task_id,),
    )
    db.commit()

    _normalise_task_timestamps(db)

    row = repo.get(task_id)
    assert row["due_at"] == "2026-08-27 09:00:00"
    assert row["reminder_at"] == "2026-08-27 11:30:00", "an untouched column stays exact"
    assert row["scheduled_at"] is None, "NULL survives"


def test_a_decorated_list_name_is_matched_by_the_word_alone(db):
    """Real To Do lists are called "🛒 Groceries"; nobody types the emoji.

    Found live: asking for "groceries" matched nothing, created a second list
    called "groceries", and split the user's shopping across two places -- one
    of which never reached their phone.

    Mutation check: drop the leading-symbol strip in `_fold_list_name` and the
    first assertion returns None.
    """
    lists = TaskListRepository()
    shopping = lists.create("🛒 Groceries", external_source="microsoft-todo", external_id="l-1")
    lists.create("📚 College", external_source="microsoft-todo", external_id="l-2")

    assert lists.by_name("groceries")["id"] == shopping
    assert lists.by_name("Groceries")["id"] == shopping
    assert lists.by_name("🛒 Groceries")["id"] == shopping
    assert lists.by_name("college")["name"] == "📚 College"


def test_folding_does_not_make_two_lists_one(db):
    """Stripping decoration must not turn a refusal into a wrong guess."""
    lists = TaskListRepository()
    lists.create("🛒 Groceries")
    lists.create("Groceries")

    assert lists.by_name("Groceries")["name"] == "Groceries", "an exact name still wins"
    assert lists.by_name("groceries") is None, "two candidates once folded is not a match"


def test_a_local_only_list_is_healed_when_an_account_appears(db, monkeypatch):
    """Otherwise the list quietly empties itself on the next pull.

    A task filed into a list with no `external_id` is created upstream in the
    *default* list, so the pull refiles it there and the user's chosen list
    loses it.

    Mutation check: make `resolve_list` return the row directly instead of
    going through `_adopt`, and `external_id` below stays None.
    """
    lists = TaskListRepository()
    local = lists.create("Groceries")  # made while nothing was signed in

    async def fake_upstream(name):
        return "graph-new", "created in Microsoft To Do"

    monkeypatch.setattr(TaskService, "_create_list_upstream", staticmethod(fake_upstream))

    ref = asyncio.run(_service().resolve_list("groceries"))
    assert ref.id == local, "the same list, not a second one"
    assert ref.external_id == "graph-new"
    assert lists.get(local)["external_id"] == "graph-new"


def test_a_task_already_upstream_is_adopted_not_created_twice(db):
    """Creating upstream is at-least-once, so the push must look before it leaps.

    Found live: the Graph create succeeded and the local adopt was lost, and the
    next tick made a second copy of the same task in the real account.

    Mutation check: delete the `existing`/`match` adopt branch in `_push` and
    `created` below becomes 1 instead of 0.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _push

    lists = TaskListRepository()
    list_id = lists.create("Tasks", external_source=SOURCE, external_id="l-1", is_default=True)
    repo = TaskRepository()
    task_id = repo.create("Buy stamps", list_id=list_id)

    created: list[dict] = []

    class _Connection:
        async def call(self, tool, arguments):
            if tool == "list_tasks":
                return _text('{"tasks": [{"id": "up-1", "title": "Buy stamps"}]}')
            created.append(arguments)
            return _text('{"id": "up-2"}')

    asyncio.run(_push(_Connection(), repo, lists, SyncReport()))

    assert created == [], "it was already there; creating again duplicates it"
    assert repo.get(task_id)["external_id"] == "up-1"


def test_two_local_rows_with_one_title_do_not_adopt_the_same_task(db):
    """Popping the match is what stops both rows claiming one upstream id."""
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _push

    lists = TaskListRepository()
    list_id = lists.create("Tasks", external_source=SOURCE, external_id="l-1", is_default=True)
    repo = TaskRepository()
    first = repo.create("Milk", list_id=list_id)
    second = repo.create("Milk", list_id=list_id)

    class _Connection:
        async def call(self, tool, arguments):
            if tool == "list_tasks":
                return _text('{"tasks": [{"id": "up-1", "title": "Milk"}]}')
            return _text('{"id": "up-new"}')

    asyncio.run(_push(_Connection(), repo, lists, SyncReport()))

    ids = {repo.get(first)["external_id"], repo.get(second)["external_id"]}
    assert ids == {"up-1", "up-new"}, "one adopts, the other is created"


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


def _text(payload: str):
    class _Result:
        content = [_Block(payload)]
        is_error = False

    return _Result()


# ------------------------------------------------ starting connectors safely


def test_connect_all_refuses_to_start_a_sign_in_nobody_is_watching(db, monkeypatch):
    """An unauthorised connector must be reported, never waited on.

    Measured before this: seven working connectors come up in about eight
    seconds, while two switched-on-but-unauthorised ones each blocked the queue
    for `auth_timeout_seconds` (300s) on a browser nobody had opened. A
    scheduled run's whole 300s budget went there before it reached a model, and
    a Tasks sync did the same.

    Mutation check: default `connect_all`'s `interactive` back to True and the
    unauthorised server is attempted instead of skipped.
    """
    from psok.mcp.config import ServerConfig, Transport, add_server
    from psok.mcp.manager import MCPManager
    from psok.tools.registry import ToolRegistry

    add_server(ServerConfig(name="needs-auth", transport=Transport.STREAMABLE_HTTP,
                            url="https://example.invalid/mcp", oauth=True))
    add_server(ServerConfig(name="plain", transport=Transport.STDIO, command="true"))

    from psok.capabilities import CapabilityService, Kind
    caps = CapabilityService()
    caps.set_enabled(Kind.CONNECTOR, "needs-auth", True)
    caps.set_enabled(Kind.CONNECTOR, "plain", True)

    attempted: list[str] = []

    class _Manager(MCPManager):
        async def connect_server(self, config, *, interactive=True):
            if not interactive and self.needs_sign_in(config):
                return await super().connect_server(config, interactive=interactive)
            attempted.append(config.name)
            return 1

    results = asyncio.run(_Manager(ToolRegistry()).connect_all())

    assert "needs-auth" not in attempted, "starting it would open a browser"
    assert "plain" in attempted
    assert "signed in" in str(results["needs-auth"]), results["needs-auth"]


def test_a_signed_in_connector_is_not_skipped(db, monkeypatch):
    """The guard is "would this open a browser", not "is this an OAuth server"."""
    from psok.mcp.config import ServerConfig, Transport
    from psok.mcp.manager import MCPManager
    from psok.tools.registry import ToolRegistry

    config = ServerConfig(name="github", transport=Transport.STREAMABLE_HTTP,
                          url="https://example.invalid/mcp", oauth=True)
    manager = MCPManager(ToolRegistry())
    assert manager.needs_sign_in(config) is True

    from psok.mcp.oauth import token_ref
    from psok.secrets import set_secret
    set_secret(token_ref("github"), '{"access_token": "x", "token_type": "bearer"}')
    assert manager.needs_sign_in(config) is False


def test_a_stale_token_does_not_buy_a_five_minute_wait(db):
    """A stored token is not proof the connect will not need a person.

    Measured: `vercel` had a token, so the "has it signed in?" guard let it
    through; the token was rejected, the SDK went straight back into a full
    authorization, and the connect sat on the loopback callback for the whole
    `auth_timeout_seconds` -- 300s, holding the one port every other sign-in
    needs. `connect_all` went from 3.9s to over two minutes on that alone.

    So the refusal lives where the browser would have opened, not at the
    decision to try.

    Mutation check: drop either `interactive` guard in `build_auth_provider`
    and the corresponding handler waits instead of raising.
    """
    from psok.mcp.config import ServerConfig, Transport
    from psok.mcp.oauth import SignInRequired, build_auth_provider

    config = ServerConfig(
        name="vercel", transport=Transport.STREAMABLE_HTTP,
        url="https://example.invalid/mcp", oauth=True,
    )
    provider = build_auth_provider(config, open_browser=False, interactive=False)

    with pytest.raises(SignInRequired):
        asyncio.run(provider.context.redirect_handler("https://example.invalid/authorize"))
    with pytest.raises(SignInRequired):
        asyncio.run(provider.context.callback_handler())


# ------------------------------------------------- conversations that answer


def test_a_placeholder_model_is_never_stored(db):
    """`'default'` reached the provider verbatim and 404'd, forever.

    Five conversations in the real database carried it, and nothing in the
    interface could correct one.

    Mutation check: return `name` unconditionally from `_validate_model`.
    """
    from fastapi import HTTPException

    from psok.api.main import _validate_model

    with pytest.raises(HTTPException):
        _validate_model("nope-not-a-provider", "x")

    # With a provider that declares a default, the placeholder is filled in.
    from psok.config import load_providers

    provider = next(
        (n for n, c in load_providers().items() if c.default_model), None
    )
    if provider:
        declared = load_providers()[provider].default_model
        assert _validate_model(provider, "default") == declared
        assert _validate_model(provider, "  ") == declared
        assert _validate_model(provider, "some-real-model") == "some-real-model"


def test_conversations_stored_with_a_placeholder_are_repaired(db):
    """Rows that predate the refusal are pointed at a real model on migrate."""
    from psok.config import load_providers
    from psok.db.connection import _repair_placeholder_models
    from psok.db.repositories import ConversationRepository

    provider = next((n for n, c in load_providers().items() if c.default_model), None)
    if provider is None:
        pytest.skip("no provider declares a default_model in this environment")

    repo = ConversationRepository()
    broken = repo.create(provider, "default", "dead on arrival")
    healthy = repo.create(provider, "a-real-model", "fine")

    _repair_placeholder_models(db)

    assert repo.get(broken)["model"] == load_providers()[provider].default_model
    assert repo.get(healthy)["model"] == "a-real-model", "an untouched row stays exact"


def test_my_day_is_a_choice_and_can_be_unmade(db):
    """Nothing fills My Day on its own, so putting a task in and taking it out
    has to work from any row -- not only from an overdue one.

    Mutation check: drop `my_day_on` from `TaskRepository.update`'s allowlist.
    """
    repo = TaskRepository()
    task_id = repo.create("Read the paper")
    assert repo.bucket("my_day") == []

    asyncio.run(_service().update(task_id, add_to_my_day=True))
    assert [r["id"] for r in repo.bucket("my_day")] == [task_id]

    asyncio.run(_service().update(task_id, add_to_my_day=False))
    assert repo.bucket("my_day") == []


def test_my_day_does_not_claim_to_sync(db):
    """Graph exposes no My Day field -- verified against a real account, whose
    task keys are id/title/status/importance/isReminderOn/createdDateTime/
    dueDateTime/body/categories/@odata.etag/hasAttachments/lastModifiedDateTime.

    So a pull must never clear or set it, or the bucket would empty itself
    every fifteen minutes with no explanation.

    Mutation check: add `"my_day_on": None` to `_apply`'s `fields`.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    repo = TaskRepository()
    _apply(repo, SyncReport(), None, {"id": "m-1", "title": "Ship", "status": "notStarted"})
    row = repo.by_external(SOURCE, "m-1")
    repo.update(row["id"], my_day_on=_today())

    _apply(repo, SyncReport(), None, {"id": "m-1", "title": "Ship it", "status": "notStarted"})
    after = repo.by_external(SOURCE, "m-1")
    assert after["title"] == "Ship it"
    assert after["my_day_on"] == _today(), "a pull must not empty My Day"
