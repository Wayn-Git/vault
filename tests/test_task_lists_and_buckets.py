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


def test_my_day_travels_as_a_category(db):
    """To Do's own My Day is unreachable -- verified against the live account on
    2026-08-28, not inferred: `showInMyDay` and `isInMyDay` both 400 with "Could
    not find a property named ... on type 'microsoft.graph.todoTask'" on v1.0 and
    beta, the live beta $metadata lists twenty-one todoTask properties and none
    contains "day", there is no `myDay` well-known list, and the legacy
    /me/outlook/tasks surface has no such field either.

    `categories` does round-trip, so that is what carries it.

    Mutation check: drop the `in_my_day` branch from `_apply`.
    """
    from psok.sync.microsoft_todo import MY_DAY_CATEGORY, SOURCE, SyncReport, _apply

    repo = TaskRepository()
    item = {"id": "m-1", "title": "Ship", "status": "notStarted"}

    _apply(repo, SyncReport(), None, {**item, "categories": [MY_DAY_CATEGORY]})
    assert repo.by_external(SOURCE, "m-1")["my_day_on"] == _today(), "the tag puts it in My Day"

    _apply(repo, SyncReport(), None, {**item, "categories": []})
    assert repo.by_external(SOURCE, "m-1")["my_day_on"] is None, "untagging takes it out"


def test_a_pull_does_not_undo_a_sun_that_has_not_been_pushed_yet(db):
    """The push runs first and clears `dirty_at` when it lands. A row still
    dirty is one whose change never reached To Do -- so the tag being absent
    upstream says nothing yet, and clearing My Day on it would silently undo the
    button the user just pressed.

    Mutation check: drop the `pending` guard from `_apply`.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    repo = TaskRepository()
    item = {"id": "m-2", "title": "Ship", "status": "notStarted"}
    _apply(repo, SyncReport(), None, item)

    row = repo.by_external(SOURCE, "m-2")
    repo.update(row["id"], my_day_on=_today(), dirty_at=_today())

    _apply(repo, SyncReport(), None, {**item, "title": "Ship it", "categories": []})
    after = repo.by_external(SOURCE, "m-2")
    assert after["title"] == "Ship it", "the rest of the pull still applies"
    assert after["my_day_on"] == _today(), "an unpushed sun survives"


def test_pushing_my_day_keeps_the_other_tags(db):
    """Graph replaces the categories array rather than merging it, so sending
    just ["My Day"] would delete whatever else the user had tagged the task
    with.

    Mutation check: return only the My Day category from `_categories_for`.
    """
    from psok.sync.microsoft_todo import (
        MY_DAY_CATEGORY,
        SOURCE,
        SyncReport,
        _apply,
        _categories_for,
    )

    repo = TaskRepository()
    _apply(
        repo,
        SyncReport(),
        None,
        {"id": "m-3", "title": "Ship", "status": "notStarted", "categories": ["Work", "Urgent"]},
    )
    row = repo.by_external(SOURCE, "m-3")
    assert _categories_for(row) == ["Work", "Urgent"], "not in My Day, tags untouched"

    repo.update(row["id"], my_day_on=_today())
    assert _categories_for(repo.by_external(SOURCE, "m-3")) == [
        "Work",
        "Urgent",
        MY_DAY_CATEGORY,
    ]


def test_completion_time_comes_back_from_to_do(db):
    """To Do knew three tasks were finished today and PSOK had recorded the
    completion time of one: `_apply` never mapped `completedDateTime`, so
    "what did I get done today" could not be answered from local data.

    Mutation check: drop `completed_at` from `_apply`'s `fields`.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    repo = TaskRepository()
    item = {
        "id": "c-1",
        "title": "SIH PPT",
        "status": "completed",
        "completedDateTime": {"dateTime": "2026-08-28T00:00:00.0000000", "timeZone": "UTC"},
    }
    _apply(repo, SyncReport(), None, item)
    row = repo.by_external(SOURCE, "c-1")
    assert row["status"] == "done"
    assert str(row["completed_at"]).startswith("2026-08-28"), row["completed_at"]

    # Un-completing it upstream clears the time rather than stranding it.
    _apply(repo, SyncReport(), None, {"id": "c-1", "title": "SIH PPT", "status": "notStarted"})
    assert repo.by_external(SOURCE, "c-1")["completed_at"] is None


def test_my_day_shows_what_was_finished_today(db):
    """My Day showing only what is left makes it empty by the evening of a day
    you actually got things done, which reads as the page being broken rather
    than as the work being over.

    Mutation check: drop the `_DONE_TODAY` clause from `_bucket_where`.
    """
    repo = TaskRepository()
    done_today = repo.create("Vault project")
    repo.update(done_today, status="done")

    old = repo.create("Finished last week")
    repo.update(old, status="done", completed_at="2026-08-01 09:00:00")

    repo.create("Still open, no date")

    titles = [r["title"] for r in repo.bucket("my_day")]
    assert "Vault project" in titles, "today's completions belong to today"
    assert "Finished last week" not in titles
    assert "Still open, no date" not in titles, "an undated open task is not today's business"

    # The rail count and the rows come from the same predicate, so they agree.
    assert repo.counts()["my_day"] == len(titles)


def test_my_day_puts_what_is_done_at_the_bottom(db):
    """My Day mixes open work with what was finished today, and the two are not
    peers: the open ones are the list, the done ones are the record. Sorted
    together, a task still to do sat underneath three already crossed off.

    Mutation check: use `_ORDER` for the my_day bucket.
    """
    repo = TaskRepository()
    finished = repo.create("Vault project")
    repo.update(finished, status="done")
    repo.create("Assignment 2", my_day_on=_today())
    starred = repo.create("Urgent thing", my_day_on=_today())
    repo.update(starred, important=True)

    rows = repo.bucket("my_day")
    statuses = [r["status"] == "done" for r in rows]
    assert statuses == sorted(statuses), "every open task comes before every done one"
    assert rows[0]["title"] == "Urgent thing", "important still leads the open ones"
    assert rows[-1]["title"] == "Vault project"


def test_a_hashtag_in_the_title_puts_it_in_my_day(db):
    """To Do's own onboarding says "Add #hashtags to a task's title to
    categorise", and the title is the one field that syncs verbatim and cannot
    be taken away. It is the gesture that works from a phone.

    Mutation check: drop `tagged_by_hashtag` from `in_my_day`.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    repo = TaskRepository()
    item = {"id": "h-1", "title": "Revision #myday", "status": "notStarted"}
    _apply(repo, SyncReport(), None, item)
    row = repo.by_external(SOURCE, "h-1")
    assert row["my_day_on"] == _today()
    assert row["title"] == "Revision #myday", (
        "the marker stays in the title: stripping it would let the next push"
        " send the stripped title back and silently untag it in To Do"
    )

    _apply(repo, SyncReport(), None, {"id": "h-1", "title": "Revision", "status": "notStarted"})
    assert repo.by_external(SOURCE, "h-1")["my_day_on"] is None, "removing the tag takes it out"


def test_a_list_called_my_day_counts_as_my_day(db):
    """The version that needs no per-task gesture. To Do puts a task in exactly
    one list, so this moves it out of wherever it lived -- unlike To Do's own My
    Day, which is an overlay. Offered because some people work that way.

    Mutation check: drop the `list_name` clause from `in_my_day`.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    repo = TaskRepository()
    item = {"id": "l-1", "title": "Groceries run", "status": "notStarted"}
    _apply(repo, SyncReport(), None, item, list_name="My Day")
    assert repo.by_external(SOURCE, "l-1")["my_day_on"] == _today()

    _apply(repo, SyncReport(), None, {**item, "id": "l-2"}, list_name="Groceries")
    assert repo.by_external(SOURCE, "l-2")["my_day_on"] is None


# ------------------------------------------------------- the local calendar
#
# Every timestamp in this schema is naive *local* time -- `_now()` is
# `datetime.now()`, `my_day_on` is `datetime.now().date()`. SQLite's `date('now')`
# is UTC. Comparing one against the other is wrong by the machine's offset for
# part of every day, and the part it is wrong for is the small hours, which is
# exactly when someone tidying up tomorrow's list finds the page has stopped
# working.


def _shifted_now(hours: int):
    """`datetime.now()` moved, so a test can stand in another part of the day."""
    from datetime import datetime, timedelta

    real = datetime.now

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return real(tz) + timedelta(hours=hours)

    return Clock


def test_buckets_use_the_local_date_not_utc(db, monkeypatch):
    """A task put in My Day at half past midnight is in My Day.

    `date('now')` is UTC. On a machine east of Greenwich the local date runs
    ahead of it for the first hours of every day, so a row stamped with the
    local date matched nothing -- My Day read empty, the sun did nothing, and
    Missed forgot yesterday's deadlines. West of Greenwich the same mismatch
    lands in the evening.

    Mutation check: put `date('now')` back in any of the bucket predicates.
    """
    from datetime import datetime, timedelta

    from psok.db import repositories

    # Wherever this actually runs, look at the clock from a point where the
    # local date and the UTC date disagree.
    offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    hours = 23 if offset.total_seconds() >= 0 else -23
    monkeypatch.setattr(repositories, "datetime", _shifted_now(hours))

    local_today = repositories._today()
    utc_today = db.execute("select date('now')").fetchone()[0]
    assert local_today != utc_today, "the shift has to actually straddle midnight"

    repo = TaskRepository()
    sunned = repo.create("Picked for today", my_day_on=local_today)
    due = repo.create("Due today", due_at=f"{local_today} 17:00:00")
    late = repo.create("Was due yesterday", due_at=f"{utc_today} 09:00:00")

    my_day = [r["id"] for r in repo.bucket("my_day")]
    assert sunned in my_day, "the sun has to work at every hour of the day"
    assert due in my_day

    done = repo.create("Finished today")
    repo.update(done, status="done")
    assert done in [r["id"] for r in repo.bucket("my_day")], "done today is still today"

    assert late in [r["id"] for r in repo.bucket("missed")]
    counts = repo.counts()
    for name in ("my_day", "missed", "important", "general", "completed", "all"):
        assert counts[name] == len(repo.bucket(name)), name


# ------------------------------------------------- My Day survives the sync


@pytest.mark.asyncio
async def test_a_task_created_for_today_stays_in_my_day_after_a_sync(db, monkeypatch):
    """The sun on the composer wrote `my_day_on` locally and told To Do
    nothing, so the first pull saw no tag, decided the user had taken it out,
    and cleared it. Fifteen minutes after making a task for today it silently
    left today.

    Mutation check: stop passing `add_to_my_day` through `TaskService.create`.
    """
    from psok.mcp import live
    from psok.sync.microsoft_todo import MY_DAY_CATEGORY, SOURCE, SyncReport, _apply

    sent = {}

    class Connected:
        connected = True

        async def call(self, tool_name, arguments):
            import json as _json

            sent[tool_name] = arguments
            body = (
                {"value": [{"id": "L1", "wellknownListName": "defaultList"}]}
                if tool_name == "list_task_lists"
                else {"id": "T1", "lastModifiedDateTime": "2026-08-28T10:00:00Z"}
            )
            text = type("T", (), {"type": "text", "text": _json.dumps(body)})()
            return type("R", (), {"content": [text]})()

    monkeypatch.setattr(live, "connection", lambda name: Connected())

    written = await _service().create("Finish the report", add_to_my_day=True)
    assert MY_DAY_CATEGORY in sent["create_task"].get("categories", []), (
        "To Do has to be told, or the next pull undoes it"
    )

    repo = TaskRepository()
    assert repo.get(written.task_id)["my_day_on"] == _today()

    # The pull, echoing back what the create sent.
    _apply(
        repo,
        SyncReport(),
        None,
        {
            "id": "T1",
            "title": "Finish the report",
            "status": "notStarted",
            "categories": [MY_DAY_CATEGORY],
        },
    )
    assert repo.by_external(SOURCE, "T1")["my_day_on"] == _today(), "still today"


def test_yesterdays_tag_does_not_keep_a_task_in_todays_my_day(db):
    """My Day is a day's worth of choosing, and the local stamp expires at
    midnight on purpose. The category upstream does not expire -- nothing takes
    it off -- so every pull read a tag PSOK itself had written weeks ago and
    stamped it today again. My Day stopped emptying and grew without bound.

    The tag is stale, so it is cleared here and the row is marked dirty for the
    push to take it off upstream too.

    Mutation check: drop the staleness check from `_apply`'s My Day branch.
    """
    from psok.sync.microsoft_todo import MY_DAY_CATEGORY, SOURCE, SyncReport, _apply

    repo = TaskRepository()
    item = {
        "id": "y-1",
        "title": "Yesterday's plan",
        "status": "notStarted",
        "categories": [MY_DAY_CATEGORY],
    }
    _apply(repo, SyncReport(), None, item)
    row = repo.by_external(SOURCE, "y-1")
    assert row["my_day_on"] == _today()

    # A day passes. The stamp goes stale; the tag upstream does not.
    repo.update(row["id"], my_day_on="2020-01-01", dirty_at=None)
    _apply(repo, SyncReport(), None, item)

    after = repo.by_external(SOURCE, "y-1")
    assert after["my_day_on"] is None, "a stale tag does not put it back in today"
    assert after["dirty_at"], "and the push is told to take the tag off upstream"


def test_a_hashtag_keeps_a_task_in_my_day_every_day(db):
    """Unlike the category, a hashtag is in the title the user is looking at,
    and a list they keep is a place they chose. Those are standing choices and
    expiring them would fight the user; only the tag PSOK writes expires.

    Mutation check: expire the hashtag the same way the category expires.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    repo = TaskRepository()
    item = {"id": "h-9", "title": "Gym #myday", "status": "notStarted"}
    _apply(repo, SyncReport(), None, item)
    row = repo.by_external(SOURCE, "h-9")
    repo.update(row["id"], my_day_on="2020-01-01")

    _apply(repo, SyncReport(), None, item)
    assert repo.by_external(SOURCE, "h-9")["my_day_on"] == _today()


def test_a_completion_time_is_not_dragged_into_the_previous_day(db):
    """To Do stamps `completedDateTime` as the completion *date* at midnight
    UTC. Reading it as an instant and converting it to local time moves it
    backwards by the machine's offset, so anywhere west of Greenwich a task
    ticked off this morning came back stamped yesterday -- and dropped out of
    "what I finished today" on the sync that followed the tick.

    Mutation check: send `completedDateTime` through the ordinary `_timestamp`.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    repo = TaskRepository()
    _apply(
        repo,
        SyncReport(),
        None,
        {
            "id": "z-1",
            "title": "SIH PPT",
            "status": "completed",
            "completedDateTime": {"dateTime": f"{_today()}T00:00:00.0000000", "timeZone": "UTC"},
        },
    )
    row = repo.by_external(SOURCE, "z-1")
    assert str(row["completed_at"]).startswith(_today()), row["completed_at"]
    assert row["id"] in [r["id"] for r in repo.bucket("my_day")], "finished today is today"


def test_a_pull_keeps_the_time_of_day_psok_already_recorded(db):
    """PSOK knows the minute the box was ticked; To Do only knows the date. The
    pull used to overwrite the first with the second, so every completion time
    collapsed to midnight and "what did I do this morning" lost its answer.

    Mutation check: take `completedDateTime` unconditionally in `_apply`.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    repo = TaskRepository()
    _apply(repo, SyncReport(), None, {"id": "z-2", "title": "Ship", "status": "notStarted"})
    row = repo.by_external(SOURCE, "z-2")
    repo.update(row["id"], status="done", completed_at=f"{_today()} 09:41:00")

    _apply(
        repo,
        SyncReport(),
        None,
        {
            "id": "z-2",
            "title": "Ship",
            "status": "completed",
            "completedDateTime": {"dateTime": f"{_today()}T00:00:00.0000000", "timeZone": "UTC"},
        },
    )
    assert repo.by_external(SOURCE, "z-2")["completed_at"] == f"{_today()} 09:41:00"
