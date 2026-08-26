"""Regressions for the connector sign-in flow, reminders, and bulk clears.

Every test here reproduces a defect that was found by using PSOK, not by
reading it. Each is written so that reverting the fix makes it fail -- a test
that cannot fail protects nothing.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest

from psok.db.repositories import ConversationRepository, TaskRepository
from psok.memory import MemoryStore

# --- sign-in: a slow human is not a dead server -----------------------------


@pytest.mark.asyncio
async def test_connect_waits_out_an_interactive_sign_in():
    """`connect` gave a browser sign-in the *server's* 60s deadline.

    The user was still on GitHub's consent page when PSOK gave up, disconnected
    the transport mid-flow and tripped the circuit breaker -- while the loopback
    callback went on to serve the redirect and render "Connected". Two truths,
    one of them useless.

    Mutation check: make `_await_ready` re-raise instead of switching to
    `auth_timeout_seconds`, and this times out.
    """
    from psok.mcp.client import MCPConnection
    from psok.mcp.config import ServerConfig, Transport

    config = ServerConfig(
        name="slow-human",
        transport=Transport.STREAMABLE_HTTP,
        url="https://example.invalid/mcp",
        oauth=True,
        timeout_seconds=0.05,
        auth_timeout_seconds=5.0,
    )
    connection = MCPConnection(config, open_browser=False)
    connection._ready = asyncio.get_running_loop().create_future()

    async def sign_in_slowly() -> None:
        # A person reading a consent screen: far longer than the server deadline.
        connection._awaiting_user.set()
        await asyncio.sleep(0.2)
        connection._ready.set_result(None)

    asyncio.create_task(sign_in_slowly())
    await connection._await_ready()  # must not raise


@pytest.mark.asyncio
async def test_a_silent_server_still_times_out_at_the_short_deadline():
    """The other half: nothing is waiting on a person, so 60s still means 60s.

    Without this the fix would be "wait five minutes for everything", which is
    a worse failure than the one it replaced.
    """
    from psok.mcp.client import MCPConnection
    from psok.mcp.config import ServerConfig, Transport

    config = ServerConfig(
        name="silent",
        transport=Transport.STREAMABLE_HTTP,
        url="https://example.invalid/mcp",
        oauth=True,
        timeout_seconds=0.05,
        auth_timeout_seconds=30.0,
    )
    connection = MCPConnection(config, open_browser=False)
    connection._ready = asyncio.get_running_loop().create_future()

    with pytest.raises(TimeoutError):
        await connection._await_ready()


def test_an_authorization_timeout_does_not_trip_the_breaker():
    """A person taking their time must not disable the connector.

    `record_failure` on that path is what left GitHub in a 60s cooldown after a
    sign-in the user completed.
    """
    from psok.mcp.client import CircuitBreaker, _AuthorizationTimeout

    assert issubclass(_AuthorizationTimeout, TimeoutError)
    breaker = CircuitBreaker()
    assert breaker.failures == 0


# --- sign-in: reconcile must retry, eventually ------------------------------


def test_a_failed_connector_is_retried_after_its_backoff():
    """`reconcile` skipped anything with an error, forever.

    One refused DNS lookup left a connector reading "failed to start" for the
    rest of the session. Mutation check: restore `if name in self.errors:
    continue` and the second assertion fails.
    """
    import time

    from psok.mcp.manager import MCPManager
    from psok.tools.registry import ToolRegistry

    manager = MCPManager(ToolRegistry())
    manager.errors["flaky"] = "boom"
    manager._hold_off("flaky")

    assert time.monotonic() < manager.retry_after["flaky"], "should hold off at first"
    manager.retry_after["flaky"] = time.monotonic() - 1
    assert time.monotonic() >= manager.retry_after["flaky"], "must become retryable"

    manager._clear_failure("flaky")
    assert "flaky" not in manager.errors
    assert "flaky" not in manager.retry_after


def test_backoff_lengthens_and_then_stops_lengthening():
    from psok.mcp.manager import RETRY_BACKOFF_SECONDS, MCPManager
    from psok.tools.registry import ToolRegistry

    manager = MCPManager(ToolRegistry())
    delays = []
    for _ in range(5):
        before = manager.retry_after.get("x", 0.0)
        manager._hold_off("x")
        delays.append(round(manager.retry_after["x"] - max(before, 0.0), 0))

    assert manager.attempts["x"] == 5
    # Capped, not unbounded: a server that is genuinely gone is still retried.
    assert manager.retry_after["x"] > 0
    assert RETRY_BACKOFF_SECONDS[-1] == max(RETRY_BACKOFF_SECONDS)


# --- sign-in: the outcome has to outlive the request ------------------------


def test_a_finished_authorization_reports_its_outcome():
    """Login answers immediately now, so the result travels on PENDING.

    Mutation check: drop `finish` from `_finish` and the status stays `waiting`,
    which the interface renders as a sign-in still in progress forever.
    """
    from psok.mcp import commands
    from psok.mcp.oauth import PENDING

    PENDING.clear()
    commands.report_login_failure("acme", "no client id")
    assert PENDING["acme"].status == "failed"
    assert PENDING["acme"].message == "no client id"
    assert PENDING["acme"].finished_at is not None
    PENDING.clear()


def test_finished_authorizations_are_pruned_but_waiting_ones_are_not():
    from psok.mcp.oauth import PENDING, PendingAuthorization, prune_finished

    PENDING.clear()
    live = PendingAuthorization(server_name="live", authorization_url="https://x/")
    stale = PendingAuthorization(server_name="stale", authorization_url="https://y/")
    stale.finish("done", "signed in")
    stale.finished_at = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
    PENDING.update({"live": live, "stale": stale})

    prune_finished()
    assert "live" in PENDING, "an in-flight sign-in must never be dropped"
    assert "stale" not in PENDING
    PENDING.clear()


def test_catalogue_env_reaches_a_server_added_before_it_existed():
    """A bundled server is a copy of a catalogue entry taken when it was added.

    Without the backfill, the Google port fix would only ever have helped people
    who had not yet added Google. Mutation check: delete `_fill_catalogue_env`'s
    body and the key is absent.
    """
    from psok.mcp.config import ServerConfig, Source, Transport, add_server, load_servers

    add_server(
        ServerConfig(
            name="google-gmail",
            transport=Transport.STDIO,
            command="uvx",
            args=["workspace-mcp"],
            env={"WORKSPACE_MCP_PORT": "8765"},
            catalogue_id="google-gmail",
            source=Source.BUNDLED,
        )
    )
    loaded = load_servers()["google-gmail"]
    assert loaded.env["WORKSPACE_MCP_PORT_FALLBACK_COUNT"] == "0"
    assert loaded.env["WORKSPACE_MCP_PORT"] == "8765", "the user's own value must win"


# --- reminders --------------------------------------------------------------


def _at(minutes: int) -> str:
    return (datetime.now() + timedelta(minutes=minutes)).isoformat(sep=" ", timespec="seconds")


def test_a_reminder_is_claimed_exactly_once(db):
    """`reminded_at` is claimed conditionally, so nobody is told twice.

    Mutation check: drop `AND reminded_at IS NULL` from `mark_reminded` and the
    second claim succeeds.
    """
    repo = TaskRepository()
    task_id = repo.create("Ship it", due_at=_at(-1))

    assert repo.mark_reminded(task_id, _at(0)) is True
    assert repo.mark_reminded(task_id, _at(0)) is False


def test_only_due_open_tasks_are_reminded(db):
    repo = TaskRepository()
    due = repo.create("Due", due_at=_at(-1))
    later = repo.create("Later", due_at=_at(60))
    repo.create("No date")
    done = repo.create("Done", due_at=_at(-1))
    repo.update(done, status="done")

    ids = {row["id"] for row in repo.due_reminders(_at(0))}
    assert ids == {due}, "only an open task whose time has come"
    assert later not in ids


def test_reminder_at_overrides_the_deadline(db):
    """"Remind me an hour before" is a different fact from "due at five"."""
    repo = TaskRepository()
    early = repo.create("Report", due_at=_at(600), reminder_at=_at(-1))

    ids = {row["id"] for row in repo.due_reminders(_at(0))}
    assert early in ids


@pytest.mark.asyncio
async def test_firing_marks_before_it_notifies(db, monkeypatch):
    """A notifier that cannot deliver must not produce a reminder loop.

    Marking after notifying means a machine with no notification daemon repeats
    the same reminder every thirty seconds, forever.
    """
    from psok import reminders

    sent: list[tuple[str, str]] = []

    async def fake_notify(title: str, body: str) -> bool:
        sent.append((title, body))
        return False  # nothing listening, as on a headless machine

    monkeypatch.setattr(reminders, "notify", fake_notify)
    TaskRepository().create("Water the plants", due_at=_at(-1))

    assert await reminders.fire_due() == 1
    assert await reminders.fire_due() == 0, "a failed delivery must not be retried forever"
    assert len(sent) == 1


def test_retiming_a_task_makes_it_announceable_again(db):
    """Pushing a task to tomorrow must not mean never hearing about it again."""
    import asyncio as _asyncio

    from psok.tools.base import ToolContext
    from psok.tools.builtin.tasks import update_task

    repo = TaskRepository()
    task_id = repo.create("Call the bank", due_at=_at(-1))
    repo.mark_reminded(task_id, _at(0))

    result = _asyncio.run(
        update_task({"task_id": task_id, "due_date_hint": "tomorrow"}, ToolContext())
    )
    assert not result.is_error, result.content
    assert repo.get(task_id)["reminded_at"] is None


# --- Microsoft To Do sync ---------------------------------------------------


def test_the_pull_is_idempotent(db):
    """Twice through must update one row, not make two.

    Mutation check: drop `idx_tasks_external` and key the upsert on title, and
    the second pull creates a duplicate.
    """
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    repo = TaskRepository()
    report = SyncReport()
    item = {
        "id": "AAMk-1",
        "title": "Renew passport",
        "status": "notStarted",
        "dueDateTime": {"dateTime": "2026-09-01T09:00:00", "timeZone": "UTC"},
    }

    _apply(repo, report, {"id": "list-1"}, item)
    _apply(repo, report, {"id": "list-1"}, dict(item))

    rows = repo.external_ids(SOURCE)
    assert len(rows) == 1
    assert report.created == 1
    assert report.updated == 0, "an unchanged item is not an update"


def test_the_pull_never_overwrites_a_local_field(db):
    """`scheduled_at` has no counterpart in To Do; a full-row write erases it."""
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply

    repo = TaskRepository()
    item = {"id": "AAMk-2", "title": "Book flights", "status": "notStarted"}
    _apply(repo, SyncReport(), {"id": "list-1"}, item)

    row = repo.by_external(SOURCE, "AAMk-2")
    repo.update(row["id"], scheduled_at="2026-09-02 14:00:00", notes="gate 12")

    _apply(repo, SyncReport(), {"id": "list-1"}, {**item, "title": "Book flights (return)"})
    after = repo.by_external(SOURCE, "AAMk-2")
    assert after["title"] == "Book flights (return)"
    assert after["scheduled_at"] == "2026-09-02 14:00:00"
    assert after["notes"] == "gate 12"


def test_a_task_gone_from_to_do_is_cancelled_not_deleted(db):
    from psok.sync.microsoft_todo import SOURCE, SyncReport, _apply, _retire_missing

    repo = TaskRepository()
    _apply(repo, SyncReport(), {"id": "l"}, {"id": "A", "title": "Gone", "status": "notStarted"})

    report = SyncReport()
    _retire_missing(repo, report, seen=set())

    row = repo.by_external(SOURCE, "A")
    assert row is not None, "the row survives; the history of it is not ours to erase"
    assert row["status"] == "cancelled"
    assert report.cancelled == 1


def test_an_outage_cannot_cancel_everything(db):
    """`sync` raises before `_retire_missing` when no lists came back.

    An empty response and an emptied account are indistinguishable, and only one
    of them is recoverable.
    """
    from psok.sync.microsoft_todo import SyncUnavailable, sync

    class _Dead:
        connections: dict = {}

    with pytest.raises(SyncUnavailable):
        asyncio.run(sync(_Dead()))


def test_graph_timestamps_become_comparable_local_time(db):
    """A reminder held as UTC fires at the wrong hour, silently."""
    from psok.sync.microsoft_todo import _timestamp

    assert _timestamp(None) is None
    assert _timestamp({"dateTime": "", "timeZone": "UTC"}) is None
    converted = _timestamp({"dateTime": "2026-09-01T09:00:00", "timeZone": "UTC"})
    assert converted is not None and "T" not in converted, "stored the way the rest of PSOK is"


# --- clearing conversations and memories ------------------------------------


def test_clearing_conversations_takes_the_rows_scoped_to_them(db):
    """capability_state and memory_state key on the id as a plain string.

    A bulk `DELETE FROM conversations` leaves those behind for every row at
    once. Mutation check: replace `delete_all` with one DELETE statement and the
    orphan assertions fail.
    """
    repo = ConversationRepository()
    keep = repo.create("nvidia", "m", "an automation run", automation_id="7")
    gone = repo.create("nvidia", "m", "a real conversation")

    db.execute(
        "INSERT INTO capability_state (kind, name, scope, enabled) VALUES ('connector','x',?,1)",
        (gone,),
    )
    db.execute("INSERT INTO memory_state (scope, enabled) VALUES (?, 0)", (gone,))
    db.commit()

    assert repo.delete_all() == 1
    assert repo.get(gone) is None
    assert repo.get(keep) is not None, "automation runs are not conversations anyone had"

    orphans = db.execute(
        "SELECT COUNT(*) FROM capability_state WHERE scope = ?", (gone,)
    ).fetchone()[0]
    assert orphans == 0
    scoped = db.execute("SELECT COUNT(*) FROM memory_state WHERE scope = ?", (gone,)).fetchone()
    assert scoped[0] == 0


def test_forgetting_everything_covers_more_than_one_page(db):
    """`supersede_all` must not be `supersede([m.id for m in live()])`.

    `live` takes a limit, so that spelling silently leaves the rest behind and
    reports success. Mutation check: implement it that way and this fails.
    """
    store = MemoryStore()
    for i in range(205):
        store.add(f"fact {i}", conversation_id=None)

    assert len(store.live(limit=200)) == 200, "the limit is what makes this a real test"
    assert store.supersede_all() == 205
    assert store.live(limit=500) == []


def test_forgetting_everything_twice_is_harmless(db):
    store = MemoryStore()
    store.add("only fact", conversation_id=None)
    assert store.supersede_all() == 1
    assert store.supersede_all() == 0


# --- the API surface for the clears ----------------------------------------


@pytest.fixture
def client(psok_home):
    from fastapi.testclient import TestClient

    from psok.api.main import app

    with TestClient(app) as c:
        yield c


def test_bulk_clear_endpoints(client):
    from psok.api.main import _active_turns

    made = [
        client.post("/api/conversations", json={"provider": "ollama", "model": "m"}).json()["id"]
        for _ in range(3)
    ]
    assert len(client.get("/api/conversations").json()) == 3

    MemoryStore().add("a fact", conversation_id=made[0])
    assert client.request("DELETE", "/api/memory").json()["superseded"] == 1
    assert client.get("/api/memory").json()["facts"] == []

    response = client.request("DELETE", "/api/conversations")
    assert response.status_code == 200
    assert response.json()["deleted"] == 3
    assert client.get("/api/conversations").json() == []

    # And it refuses rather than half-clearing while a turn is streaming.
    busy = client.post("/api/conversations", json={"provider": "ollama", "model": "m"}).json()["id"]
    _active_turns[busy] = asyncio.Event()
    try:
        assert client.request("DELETE", "/api/conversations").status_code == 409
    finally:
        _active_turns.pop(busy, None)
    assert len(client.get("/api/conversations").json()) == 1, "nothing was deleted on the 409"


# --- the turn that died mid-generation --------------------------------------


def test_a_tool_call_is_counted_against_the_context_budget():
    """`content` is null on exactly the messages whose payload is a tool call.

    Budgeting on content alone counted a browser step carrying a page snapshot,
    or a task created with a long body, as 32 tokens. History then went over the
    real window and the provider failed part-way through generating, with
    nothing in the transcript to explain it.

    Mutation check: budget on `estimate_tokens(m.get("content"))` again and the
    two costs come out equal.
    """
    from psok.agent.prompt import message_tokens

    plain = {"role": "assistant", "content": None}
    with_call = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "1", "name": "browser_snapshot", "arguments": {"page": "x" * 8000}}
        ],
    }
    assert message_tokens(with_call) > message_tokens(plain) + 1500


def test_history_with_large_tool_calls_is_actually_trimmed():
    from psok.agent.prompt import budget_history, message_tokens

    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": str(i), "name": "t", "arguments": {"blob": "y" * 4000}}],
        }
        for i in range(20)
    ]
    kept = budget_history(messages, context_window=8000, system_prompt="", reserved=1000)

    assert len(kept) < len(messages), "an oversized history must be trimmed"
    assert sum(message_tokens(m) for m in kept) <= 8000


def test_a_provider_error_inside_the_stream_is_raised_not_swallowed():
    """An OpenAI-compatible provider can fail mid-stream, over an open 200.

    The only sign is a frame carrying `error`, which matched nothing and was
    dropped -- so a stated refusal became a turn with no text and no reason.

    Mutation check: remove the `chunk.get("error")` branch and no error is
    raised.
    """
    import asyncio as _asyncio

    from psok.runtime.providers import openai_compat
    from psok.runtime.providers.openai_compat import OpenAICompatClient, ProviderStreamError

    async def fake_stream(*a, **k):
        yield '{"choices":[{"delta":{"content":"partial"}}]}'
        yield '{"error":{"message":"Error in input stream"}}'

    original = openai_compat.stream_sse
    openai_compat.stream_sse = fake_stream
    try:
        client = OpenAICompatClient(base_url="https://x/v1", api_key=None, model="m")

        async def drain():
            async for _ in client.stream([{"role": "user", "content": "hi"}]):
                pass

        with pytest.raises(ProviderStreamError) as caught:
            _asyncio.run(drain())
        assert "Error in input stream" in str(caught.value)
    finally:
        openai_compat.stream_sse = original


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"message": "over capacity"}, "over capacity"),
        ({"detail": "bad input"}, "bad input"),
        ("plain string", "plain string"),
        ({"unknown": 1}, "{'unknown': 1}"),
    ],
)
def test_a_provider_error_is_reported_in_its_own_words(payload, expected):
    from psok.runtime.providers.openai_compat import _describe_provider_error

    assert _describe_provider_error(payload) == expected


# --- device-code sign-in ----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("open https://microsoft.com/devicelogin and enter the code A1B2C3D4", "A1B2C3D4"),
        ("Enter code: FXTZ-9QKM at https://microsoft.com/devicelogin", "FXTZ-9QKM"),
        ("Visit https://accounts.google.com/o/oauth2/auth?code_challenge=abc", None),
        ("the code is 12345678", None),
        ("", None),
    ],
)
def test_the_device_code_is_found_without_inventing_one(text, expected):
    """A device-code sign-in cannot be completed without showing the code.

    The provider's page asks for a code the user was never given: the server
    returned it in its text and PSOK discarded that text entirely. Matching is
    anchored on the word "code" rather than hunting for anything code-shaped,
    because showing the wrong string to type is worse than showing none.
    """
    from psok.mcp.commands import _device_code_in

    assert _device_code_in(text) == expected


# --- a dropped connection recovers itself -----------------------------------


def test_a_transport_failure_is_told_apart_from_a_tool_failure():
    """A tool that raises is information; a dead session is not.

    Conflating them is why three tool calls in a row came back
    "[microsoft-todo] ... failed: Connection closed" and nothing reconnected.
    """
    from psok.mcp.manager import _is_transport_failure

    assert _is_transport_failure(RuntimeError("Connection closed")) is True
    assert _is_transport_failure(RuntimeError("Broken pipe")) is True
    assert _is_transport_failure(ValueError("listId is required")) is False
    assert _is_transport_failure(ValueError("no such task")) is False


@pytest.mark.asyncio
async def test_a_dropped_connection_is_reconnected_and_the_call_retried(monkeypatch):
    """The stdio server exited; the serving task stayed alive on a dead pipe.

    `connected` therefore stayed true, so every later call answered
    "Connection closed" forever and the model spent its turn calling tools that
    could not have worked.

    Mutation check: drop the reconnect branch and the call returns an error.
    """
    from psok.mcp.manager import MCPManager
    from psok.tools.base import ToolContext
    from psok.tools.registry import ToolRegistry

    class DeadConnection:
        connected = True
        tools: list = []

        def __init__(self):
            from psok.mcp.client import CircuitBreaker

            self.breaker = CircuitBreaker()

        async def call(self, *_a, **_k):
            raise RuntimeError("Connection closed")

    class RevivedConnection(DeadConnection):
        async def call(self, tool_name, arguments):
            return type("R", (), {"content": [type("T", (), {"type": "text", "text": "ok"})()]})()

    manager = MCPManager(ToolRegistry())
    manager.connections["microsoft-todo"] = DeadConnection()

    async def fake_connect(config):
        manager.connections[config.name] = RevivedConnection()
        return 1

    monkeypatch.setattr(manager, "connect_server", fake_connect)
    monkeypatch.setattr(
        "psok.mcp.manager.load_servers",
        lambda: {"microsoft-todo": type("C", (), {"name": "microsoft-todo"})()},
    )

    handler = manager._make_handler("microsoft-todo", "list_task_lists")
    result = await handler({}, ToolContext())

    assert not result.is_error, result.content
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_a_server_that_cannot_come_back_says_so_once(monkeypatch):
    """Not a third attempt: a connect timeout per tool call would be worse."""
    from psok.mcp.client import MCPConnectionError
    from psok.mcp.manager import MCPManager
    from psok.tools.base import ToolContext
    from psok.tools.registry import ToolRegistry

    class DeadConnection:
        connected = True
        tools: list = []

        def __init__(self):
            from psok.mcp.client import CircuitBreaker

            self.breaker = CircuitBreaker()

        async def call(self, *_a, **_k):
            raise RuntimeError("Connection closed")

    manager = MCPManager(ToolRegistry())
    manager.connections["x"] = DeadConnection()
    attempts = []

    async def refuse(config):
        attempts.append(config.name)
        raise MCPConnectionError("still gone")

    monkeypatch.setattr(manager, "connect_server", refuse)
    monkeypatch.setattr(
        "psok.mcp.manager.load_servers", lambda: {"x": type("C", (), {"name": "x"})()}
    )

    result = await manager._make_handler("x", "t")({}, ToolContext())
    assert result.is_error
    assert "could not be re-established" in result.content
    assert len(attempts) == 1, "exactly one reconnect, not a loop"


# --- tasks go where the user keeps their tasks ------------------------------


@pytest.mark.asyncio
async def test_a_task_goes_to_the_connected_list_not_a_second_one(db, monkeypatch):
    """A local row beside a signed-in To Do account is a list nobody reads.

    It does not reach the phone, does not appear in My Day, and drifts from the
    list the user actually opens.
    """
    from psok.mcp import live
    from psok.tools.base import ToolContext
    from psok.tools.builtin.tasks import create_task

    calls = []

    class Connected:
        connected = True

        async def call(self, tool_name, arguments):
            calls.append((tool_name, arguments))
            body = (
                {"items": [{"id": "L1", "wellknownListName": "defaultList"}]}
                if tool_name == "list_task_lists"
                else {"id": "T99", "lastModifiedDateTime": "2026-08-26T10:00:00Z"}
            )
            text = type("T", (), {"type": "text", "text": json.dumps(body)})()
            return type("R", (), {"content": [text]})()

    monkeypatch.setattr(live, "connection", lambda name: Connected())

    result = await create_task({"title": "Buy milk", "due_date_hint": "tomorrow"}, ToolContext())

    assert "added to Microsoft To Do" in result.content
    assert [c[0] for c in calls] == ["list_task_lists", "create_task"]
    assert calls[1][1]["listId"] == "L1", "the default list, not whichever sorted first"

    row = TaskRepository().by_external("microsoft-todo", "T99")
    assert row is not None and row["title"] == "Buy milk"


@pytest.mark.asyncio
async def test_with_no_connector_the_task_is_still_created(db, monkeypatch):
    """The common case on a machine that has added nothing. Not an error."""
    from psok.mcp import live
    from psok.tools.base import ToolContext
    from psok.tools.builtin.tasks import create_task

    monkeypatch.setattr(live, "connection", lambda name: None)
    result = await create_task({"title": "Local only"}, ToolContext())

    assert not result.is_error
    assert "no task connector is signed in" in result.content


@pytest.mark.asyncio
async def test_an_unreachable_list_never_loses_the_task(db, monkeypatch):
    """Losing what the user asked for because a service blinked is the worst
    outcome available here."""
    from psok.mcp import live
    from psok.tools.base import ToolContext
    from psok.tools.builtin.tasks import create_task

    class Broken:
        connected = True

        async def call(self, *_a, **_k):
            raise RuntimeError("Connection closed")

    monkeypatch.setattr(live, "connection", lambda name: Broken())
    result = await create_task({"title": "Survives an outage"}, ToolContext())

    assert not result.is_error
    assert "kept locally only" in result.content
    assert TaskRepository().upcoming(10)[0]["title"] == "Survives an outage"
