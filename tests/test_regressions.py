"""Regression tests for bugs found during a dedicated audit.

Each test names the defect it locks down. They live together so the audit's
findings stay visible rather than dissolving into the suite.
"""

from __future__ import annotations

import socket
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from psok.agent.prompt import budget_history
from psok.db.repositories import CalendarRepository, TaskRepository
from psok.retrieval.store import _sanitize_fts_query
from psok.secrets import redact
from psok.tools.base import ToolContext
from psok.tools.registry import mcp_tool_key

# --- 1: the API never exposed MCP tools to the agent ------------------------


def test_api_builds_its_registry_through_the_mcp_manager():
    """The HTTP path had no MCP manager at all, so the frontend could never
    reach a connected server's tools."""
    import inspect

    from psok.api import main

    source = inspect.getsource(main)
    assert "MCPManager" in source
    assert "_registry_for" in source
    assert inspect.iscoroutinefunction(main._director), "director creation must await MCP setup"


def test_api_reuses_one_manager_rather_than_spawning_per_request():
    import inspect

    from psok.api import main

    assert "_mcp" in inspect.getsource(main._registry_for)
    assert main._mcp["manager"] is None  # nothing connected until first use


# --- 2: scheduling conflicts skipped when no duration was supplied ----------


async def test_task_without_a_duration_still_checks_for_conflicts(db):
    """The conflict check was gated on a duration estimate, so a task with a
    work time but no estimate was silently booked over an existing event."""
    from psok.tools.builtin.tasks import create_task

    start = (datetime.now() + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
    CalendarRepository().create(
        "existing", start.isoformat(), (start + timedelta(hours=2)).isoformat()
    )

    result = await create_task(
        {"title": "Deep work", "scheduled_hint": start.strftime("%Y-%m-%d %H:%M")},
        ToolContext(),
    )
    assert result.is_error and "conflicts with" in result.content
    assert not TaskRepository().upcoming(), "nothing should have been persisted"


# --- 3: MCP tool keys collided across distinct servers ----------------------


def test_server_names_differing_only_by_punctuation_do_not_collide():
    """'-' and '_' were both rewritten to '_', so two different servers mapped
    to one key -- the exact collision namespacing exists to prevent."""
    assert mcp_tool_key("t", "my-server") != mcp_tool_key("t", "my_server")
    assert mcp_tool_key("t", "a.b") != mcp_tool_key("t", "a_b")


def test_tool_keys_stay_safe_for_provider_schemas():
    key = mcp_tool_key("search", "my-server.example")
    assert all(c.isalnum() or c == "_" for c in key)


# --- 4: single-character search terms were unfindable -----------------------


def test_single_character_terms_are_searchable():
    """Tokens of length 1 were dropped, so 'C' and 'R' matched nothing."""
    assert '"C"' in _sanitize_fts_query("C sharp")
    assert _sanitize_fts_query("R") == '"R"'
    assert _sanitize_fts_query("!!!") == ""


# --- 5: a truncated stream threw away text already shown to the user --------


async def test_truncated_stream_keeps_the_partial_answer(db, monkeypatch):
    import psok.agent.director as director_module
    from psok.agent.director import Director
    from psok.db.repositories import ConversationRepository, MessageRepository
    from psok.runtime.types import Capabilities, ResolvedModel, StreamEvent
    from psok.security.confirmation import ConfirmationService, auto_approve
    from psok.tools.registry import ToolRegistry

    class DropsMidStream:
        async def complete(self, *a, **k):
            raise AssertionError("streaming path should be used")

        async def stream(self, messages, tools=None, params=None):
            yield StreamEvent(type="text", text="the answer is ")
            yield StreamEvent(type="text", text="forty-two")
            # connection dies: no terminal event

    monkeypatch.setattr(
        director_module,
        "resolve",
        lambda *a, **k: ResolvedModel("f", "f", DropsMidStream(), Capabilities(streaming=True)),
    )

    cid = ConversationRepository().create("f", "f")
    director = Director(ToolRegistry(ConfirmationService(auto_approve)), stream=True)
    events = [e async for e in director.run(cid, "hi")]

    kinds = [e.type for e in events]
    assert "warning" in kinds, "the user should be told the answer was cut off"
    assert kinds[-1] == "done", "a truncated stream is still a completed turn"
    assert MessageRepository().history(cid)[-1].content == "the answer is forty-two"


# --- 6: grep found nothing when the root sat under a dotted directory -------


async def test_grep_works_when_the_workspace_is_under_a_hidden_directory(tmp_path):
    """Hidden-component checking used the absolute path, so a workspace under
    e.g. ~/.config silently matched nothing."""
    from psok.tools.builtin.filesystem import grep_files

    root = tmp_path / ".hidden-parent" / "workspace"
    root.mkdir(parents=True)
    (root / "note.md").write_text("findme here\n")

    result = await grep_files({"pattern": "findme"}, ToolContext(workspace_root=str(root)))
    assert "note.md" in result.content


async def test_grep_still_skips_hidden_files_inside_the_workspace(tmp_path):
    from psok.tools.builtin.filesystem import grep_files

    root = tmp_path / "ws"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text("findme\n")
    (root / "ok.md").write_text("findme\n")

    result = await grep_files({"pattern": "findme"}, ToolContext(workspace_root=str(root)))
    assert "ok.md" in result.content
    assert ".git" not in result.content


# --- 7: an orphan tool result could lead the budgeted history ---------------


def test_orphan_tool_result_never_leads_the_history_even_at_a_tiny_budget():
    """The early-return path for an oversized system prompt skipped the orphan
    trim, handing providers a tool result with no originating call."""
    messages = [
        {"role": "tool", "content": "orphan", "tool_call_id": "c1"},
        {"role": "user", "content": "x"},
    ]
    kept = budget_history(messages, context_window=10, system_prompt="y" * 10000, reserved=4096)
    assert not kept or kept[0]["role"] != "tool"


# --- 8: chunk/vector misalignment was silent --------------------------------


async def test_short_embedding_response_is_rejected_not_misaligned(db, tmp_path):
    """Zipping with strict=False paired each vector with the wrong chunk when an
    embedder returned fewer vectors than it was given."""
    from psok.retrieval.embeddings import EmbeddingError
    from psok.retrieval.indexer import Indexer

    root = tmp_path / "v"
    root.mkdir()
    (root / "a.md").write_text("# A\n\n## One\nalpha\n\n## Two\nbeta\n\n## Three\ngamma\n")

    class ShortEmbedder:
        provider, model = "fake", "short"

        async def embed(self, texts):
            return [[0.1] * 8 for _ in texts[:-1]]  # one short

        async def embed_one(self, text):
            return [0.1] * 8

    with pytest.raises(EmbeddingError, match="vectors for"):
        await Indexer(ShortEmbedder(), conn=db).index_file(root / "a.md")


# --- 9/10: OAuth callback port and redaction --------------------------------


async def test_busy_callback_port_reports_what_is_wrong():
    """Login died with a bare OSError; the port is fixed by the registered
    redirect URI, so the fix is a clear message, not a different port."""
    from psok.mcp.oauth import (
        CALLBACK_HOST,
        CALLBACK_PORT,
        CallbackPortUnavailable,
        _wait_for_callback,
    )

    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        blocker.bind((CALLBACK_HOST, CALLBACK_PORT))
        blocker.listen(1)
    except OSError:
        pytest.skip("callback port is already in use by something else")

    try:
        with pytest.raises(CallbackPortUnavailable) as excinfo:
            await _wait_for_callback(timeout=1)
        assert str(CALLBACK_PORT) in str(excinfo.value)
    finally:
        blocker.close()


def test_redaction_blanks_secrets_without_discarding_surrounding_structure():
    """A secret-shaped key holding a container had the whole container blanked,
    losing audit detail that was not itself sensitive."""
    out = redact(
        {
            "authorization_notes": {"important": "keep me", "token": "sk-abcdefghijklmnopqrst"},
            "api_key": "sk-abcdefghijklmnopqrst",
        }
    )
    assert out["api_key"] == "[redacted]"
    assert out["authorization_notes"]["important"] == "keep me"
    assert out["authorization_notes"]["token"] == "[redacted]"


# --- 11: packaging ----------------------------------------------------------


def test_every_source_package_is_importable():
    """psok.mcp had no __init__.py and worked only as an implicit namespace
    package, which does not survive a wheel build."""
    import psok

    root = Path(psok.__file__).parent
    for directory in root.rglob("*"):
        if not directory.is_dir() or "__pycache__" in directory.parts:
            continue
        if not any(f.suffix == ".py" for f in directory.iterdir() if f.is_file()):
            continue
        assert (directory / "__init__.py").exists(), f"{directory} has modules but no __init__.py"


# --- 12: approving a confirmation over HTTP never woke the waiting turn -----


async def test_confirmation_decision_resolves_a_future_from_another_thread():
    """The decision endpoint was a sync `def`, so FastAPI ran it in a threadpool.
    asyncio futures are not thread-safe: the decision was recorded but the turn
    waiting on it never resumed, hanging every gated tool call made over HTTP."""
    import asyncio
    import inspect

    from psok.api import main

    assert inspect.iscoroutinefunction(main.decide_confirmation), (
        "must be async so it runs on the event loop that owns the future"
    )
    assert "call_soon_threadsafe" in inspect.getsource(main.decide_confirmation)

    # The stored entry must carry its loop so any caller can resolve it safely.
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()
    main._pending["probe"] = {"future": future, "loop": loop, "payload": None}
    try:
        await main.decide_confirmation("probe", main.ConfirmationDecision(allow=True))
        assert await asyncio.wait_for(future, timeout=2) is True
    finally:
        main._pending.pop("probe", None)


def test_pending_confirmations_record_the_owning_loop():
    import inspect

    from psok.api import main

    assert '"loop": loop' in inspect.getsource(main._await_confirmation)


# --- 13-19: found while making the backend serviceable from a browser -------


@pytest.fixture
def api():
    """The API keeps process-global MCP and confirmation state; restore it so
    these tests cannot leak into each other or into the tests above."""
    from psok.api import main

    saved_mcp = dict(main._mcp)
    saved_pending = dict(main._pending)
    main._mcp.update({"manager": None, "registry": None, "workspace": None, "errors": {}})
    main._pending.clear()
    yield main
    main._mcp.clear()
    main._mcp.update(saved_mcp)
    main._pending.clear()
    main._pending.update(saved_pending)


def test_browser_requests_from_the_vite_dev_server_are_allowed(api):
    """The API had no CORS middleware, so every request from the frontend's
    origin was blocked before it reached a route. curl does not enforce CORS,
    which is why this went unnoticed."""
    from fastapi.testclient import TestClient

    with TestClient(api.app) as client:
        response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"

        preflight = client.options(
            "/api/conversations",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert preflight.status_code == 200

    # Not a wildcard: this API drives the user's machine.
    assert "*" not in api._cors_origins()


async def test_remember_is_stored_under_the_key_the_gate_reads_back(api, db):
    """'Don't ask again' over HTTP wrote the preference under the bare tool
    name while the gate looks it up under operation[:subtype]. The two never
    matched, so the checkbox silently did nothing -- and had they matched,
    approving a read-only shell command would have approved destructive ones."""
    from psok.security.confirmation import ConfirmationService
    from psok.tools.base import RiskLevel, Tool

    async def never_runs(args, ctx):  # pragma: no cover - the gate denies first
        raise AssertionError("handler must not run in this test")

    shell = Tool(
        name="run_shell_command",
        description="run a command",
        parameters={},
        handler=never_runs,
        risk=RiskLevel.HIGH,
    )

    import asyncio

    service = ConfirmationService(callback=api._await_confirmation)
    read_only = {"operation_type": "read-only"}

    async def approve_the_next_prompt(*, remember: bool) -> None:
        for _ in range(1000):
            if api._pending:
                break
            await asyncio.sleep(0)
        else:  # pragma: no cover - only on a regression in the gate itself
            raise AssertionError("the gate never asked")
        await api.decide_confirmation(
            next(iter(api._pending)), api.ConfirmationDecision(allow=True, remember=remember)
        )

    # First call: the user approves through the API and ticks "don't ask again".
    pending = asyncio.create_task(service.check(shell, read_only))
    await approve_the_next_prompt(remember=True)
    assert (await pending).allowed

    # Second identical call must now skip the prompt. The timeout matters: when
    # the preference is stored under the wrong key the gate asks again and waits
    # six hours for an answer, so without it this test hangs instead of failing.
    outcome = await asyncio.wait_for(service.check(shell, read_only), timeout=5)
    assert outcome.decision == "skipped_by_pref", (
        "the standing preference was stored under a key the gate never reads"
    )

    # And the approval must not have leaked to a different subtype.
    assert service.preferences.get("run_shell_command:destructive") is None
    assert service.preferences.get("run_shell_command") is None


async def test_an_unconfigured_provider_becomes_an_error_event(db):
    """resolve() raised straight out of the loop's async generator. Over SSE the
    headers are already sent, so the client saw a 200 whose body simply stopped
    -- indistinguishable from a dropped connection, with no error to show."""
    from psok.agent.director import Director
    from psok.db.repositories import ConversationRepository
    from psok.security.confirmation import ConfirmationService, auto_approve
    from psok.tools.registry import ToolRegistry

    cid = ConversationRepository().create("not-a-real-provider", "m")
    registry = ToolRegistry(ConfirmationService(auto_approve))

    events = [e async for e in Director(registry, stream=True).run(cid, "hi")]

    assert [e.type for e in events] == ["error"]
    assert "not-a-real-provider" in events[0].data["message"]


def test_the_turn_stream_never_dies_without_saying_why(api, db):
    """The same defect through the HTTP surface: the stream must carry an
    error event rather than the response body ending mid-flight."""
    import json

    from fastapi.testclient import TestClient

    from psok.db.repositories import ConversationRepository

    with TestClient(api.app) as client:
        cid = ConversationRepository().create("not-a-real-provider", "m")
        with client.stream("POST", f"/api/conversations/{cid}/turn", json={"message": "hi"}) as r:
            assert r.status_code == 200
            events = [
                json.loads(line.removeprefix("data: "))
                for line in r.iter_lines()
                if line.startswith("data: ")
            ]

    assert [e["type"] for e in events] == ["error"]


async def test_a_streamed_answer_is_emitted_once(db):
    """Streaming sent the answer as deltas and then again whole as
    assistant_text, with done carrying it a third time. An interface rendering
    the documented events showed the reply twice."""
    from psok.agent.director import Director
    from psok.db.repositories import ConversationRepository
    from psok.runtime.types import Capabilities, ModelResponse, ResolvedModel, StreamEvent
    from psok.security.confirmation import ConfirmationService, auto_approve
    from psok.tools.registry import ToolRegistry

    class StreamingClient:
        async def stream(self, messages, tools=None, params=None):
            yield StreamEvent(type="text", text="hel")
            yield StreamEvent(type="text", text="lo")
            yield StreamEvent(type="done", response=ModelResponse(text="hello"))

    model = ResolvedModel("fake", "fake-1", StreamingClient(), Capabilities(streaming=True))
    import psok.agent.director as director_module

    original = director_module.resolve
    director_module.resolve = lambda *a, **k: model
    try:
        cid = ConversationRepository().create("fake", "fake-1")
        registry = ToolRegistry(ConfirmationService(auto_approve))
        events = [e async for e in Director(registry, stream=True).run(cid, "hi")]
    finally:
        director_module.resolve = original

    assert [e.data["text"] for e in events if e.type == "assistant_delta"] == ["hel", "lo"]
    assert not [e for e in events if e.type == "assistant_text"], (
        "the answer already went out as deltas"
    )
    assert events[-1].type == "done"


async def test_a_non_streamed_answer_still_arrives_whole(db):
    """The other side of the fix: a provider that cannot stream must still
    produce exactly one assistant_text."""
    from psok.agent.director import Director
    from psok.db.repositories import ConversationRepository
    from psok.runtime.types import Capabilities, ModelResponse, ResolvedModel
    from psok.security.confirmation import ConfirmationService, auto_approve
    from psok.tools.registry import ToolRegistry

    class PlainClient:
        async def complete(self, messages, tools=None, params=None):
            return ModelResponse(text="whole answer")

    model = ResolvedModel("fake", "fake-1", PlainClient(), Capabilities(streaming=False))
    import psok.agent.director as director_module

    original = director_module.resolve
    director_module.resolve = lambda *a, **k: model
    try:
        cid = ConversationRepository().create("fake", "fake-1")
        registry = ToolRegistry(ConfirmationService(auto_approve))
        events = [e async for e in Director(registry, stream=True).run(cid, "hi")]
    finally:
        director_module.resolve = original

    assert [e.data["text"] for e in events if e.type == "assistant_text"] == ["whole answer"]


def test_health_counts_the_live_registry_including_mcp_tools(api, db):
    """Health built a throwaway builtin-only registry, so the tool count never
    included connected MCP tools and never moved when a connector failed."""
    from fastapi.testclient import TestClient

    from psok.tools.base import RiskLevel, Tool, ToolSource
    from psok.tools.registry import build_default_registry

    async def noop(args, ctx):  # pragma: no cover - never dispatched here
        raise AssertionError

    registry = build_default_registry()
    builtin_count = len(registry.list())
    registry.register(
        Tool(
            name="search__mcp__example",
            description="from a connected server",
            parameters={},
            handler=noop,
            risk=RiskLevel.MEDIUM,
            source=ToolSource.MCP,
            server_name="example",
        )
    )
    api._mcp.update({"registry": registry, "errors": {"broken": "connection refused"}})

    with TestClient(api.app) as client:
        body = client.get("/api/health").json()

    assert body["tools"] == builtin_count + 1
    assert body["mcp_tools"] == 1
    assert body["connector_errors"] == {"broken": "connection refused"}
    assert body["status"] == "degraded"


async def test_concurrent_turns_share_one_mcp_manager(api, db, tmp_path, monkeypatch):
    """Two turns starting at once each rebuilt the registry, orphaning one set
    of stdio subprocesses -- and a workspace change shut down the manager the
    other turn was mid-tool-call against.

    Connecting has to actually suspend for the race to exist, which it does the
    moment a real server is configured. With no servers the second caller never
    gets to run before the first finishes, so a stub supplies the await.
    """
    import asyncio

    built = []

    class SlowManager:
        def __init__(self, registry, *, open_browser=True):
            built.append(self)
            self.registry = registry

        async def connect_all(self, *, conversation_id=None):
            await asyncio.sleep(0.01)
            return {}

        async def shutdown(self):
            pass

    monkeypatch.setattr(api, "MCPManager", SlowManager)

    first, second = await asyncio.gather(
        api._registry_for(str(tmp_path)), api._registry_for(str(tmp_path))
    )

    assert len(built) == 1, f"{len(built)} managers built for one workspace"
    assert first[0] is second[0], "both turns must reach the same registry"
    assert api._mcp["manager"] is built[0]


def test_a_conversations_model_can_be_switched_after_it_starts(api, db):
    """ai-runtime.md describes switching model mid-conversation as a string
    write the interface performs. There was no endpoint to perform it, and no
    validation, so a bad provider name only failed once a turn was streaming."""
    from fastapi.testclient import TestClient

    with TestClient(api.app) as client:
        assert client.post(
            "/api/conversations", json={"provider": "nope", "model": "m"}
        ).status_code == 400

        cid = client.post(
            "/api/conversations", json={"provider": "ollama", "model": "qwen2.5:7b"}
        ).json()["id"]

        patched = client.patch(
            f"/api/conversations/{cid}",
            json={"provider": "anthropic", "model": "claude-sonnet-4-20250514", "title": "renamed"},
        )
        assert patched.status_code == 200
        assert patched.json()["provider"] == "anthropic"
        assert patched.json()["title"] == "renamed"

        rejected = client.patch(f"/api/conversations/{cid}", json={"provider": "nope"})
        assert rejected.status_code == 400
        assert client.patch("/api/conversations/missing", json={"title": "x"}).status_code == 404


def test_a_non_streaming_provider_prints_its_answer_in_the_cli(db, capsys, monkeypatch):
    """The CLI dropped assistant_text on the floor to avoid the double-render
    the loop used to cause. With a provider that cannot stream -- Google
    declares streaming=False -- that was the only carrier of the answer, so the
    turn finished having printed nothing at all."""
    import psok.agent.director as director_module
    from psok.cli import cmd_chat
    from psok.runtime.types import Capabilities, ModelResponse, ResolvedModel

    class PlainClient:
        async def complete(self, messages, tools=None, params=None):
            return ModelResponse(text="the whole answer")

    monkeypatch.setattr(
        director_module,
        "resolve",
        lambda *a, **k: ResolvedModel("f", "f", PlainClient(), Capabilities(streaming=False)),
    )

    import argparse

    cmd_chat(
        argparse.Namespace(
            provider="f", model="f", workspace=None, message="hi", conversation=None
        )
    )

    assert "the whole answer" in capsys.readouterr().out


# --- 20: a suspended turn was invisible until the interface guessed ---------


async def test_the_interface_learns_a_confirmation_is_pending_before_it_answers(api, db, monkeypatch):
    """A gated tool call suspends the turn with no signal but the stream going
    quiet, which looks exactly like a slow tool. The interface had to poll
    GET /api/confirmations and guess, matching on tool name -- ambiguous with
    two pending calls to the same tool, and never terminating for a low-risk
    call that produces no confirmation at all."""
    import asyncio

    import psok.agent.director as director_module
    from psok.agent.director import Director
    from psok.db.repositories import ConversationRepository
    from psok.runtime.types import Capabilities, ModelResponse, ResolvedModel, ToolCall
    from psok.security.confirmation import ConfirmationService
    from psok.tools.base import RiskLevel, Tool, ToolResult
    from psok.tools.registry import ToolRegistry

    async def write(args, ctx):
        return ToolResult.ok("written")

    registry = ToolRegistry(ConfirmationService(callback=api._await_confirmation))
    registry.register(
        Tool(
            name="write_note",
            description="write a note",
            parameters={},
            handler=write,
            risk=RiskLevel.MEDIUM,  # medium confirms by default
        )
    )

    responses = [
        ModelResponse(tool_calls=[ToolCall(id="c1", name="write_note", arguments={"t": "x"})]),
        ModelResponse(text="done"),
    ]

    class Scripted:
        async def complete(self, messages, tools=None, params=None):
            return responses.pop(0)

    monkeypatch.setattr(
        director_module,
        "resolve",
        lambda *a, **k: ResolvedModel("f", "f", Scripted(), Capabilities(streaming=False)),
    )

    cid = ConversationRepository().create("f", "f")
    seen = []

    async def drive():
        async for event in Director(registry, stream=True).run(cid, "note this"):
            seen.append(event)
            if event.type == "confirmation_required":
                # Answering with the id the event carried is the whole point: if
                # the event never arrived, or arrived after the gate was already
                # answered, there is no id to use and this times out.
                assert event.data["request_id"] in api._pending
                await api.decide_confirmation(
                    event.data["request_id"], api.ConfirmationDecision(allow=True)
                )

    await asyncio.wait_for(drive(), timeout=10)

    kinds = [e.type for e in seen]
    assert "confirmation_required" in kinds
    assert kinds.index("tool_call") < kinds.index("confirmation_required")
    assert kinds.index("confirmation_required") < kinds.index("tool_result")
    assert kinds[-1] == "done"

    prompt = next(e for e in seen if e.type == "confirmation_required").data
    assert prompt["tool_name"] == "write_note"
    assert prompt["risk"] == "medium"
    assert prompt["operation_key"] == "write_note"
    assert prompt["arguments"] == {"t": "x"}
    assert not [e for e in seen if e.type == "tool_result" and e.data["is_error"]]


async def test_a_low_risk_call_never_announces_a_confirmation(api, db, monkeypatch):
    """The other half: an interface that starts polling on tool_call must have
    something that tells it not to. Low-risk tools run without a prompt, so no
    confirmation_required is emitted for them."""
    import asyncio

    import psok.agent.director as director_module
    from psok.agent.director import Director
    from psok.db.repositories import ConversationRepository
    from psok.runtime.types import Capabilities, ModelResponse, ResolvedModel, ToolCall
    from psok.security.confirmation import ConfirmationService
    from psok.tools.base import RiskLevel, Tool, ToolResult
    from psok.tools.registry import ToolRegistry

    async def peek(args, ctx):
        return ToolResult.ok("read")

    registry = ToolRegistry(ConfirmationService(callback=api._await_confirmation))
    registry.register(
        Tool(
            name="read_note",
            description="read a note",
            parameters={},
            handler=peek,
            risk=RiskLevel.LOW,
        )
    )

    responses = [
        ModelResponse(tool_calls=[ToolCall(id="c1", name="read_note", arguments={})]),
        ModelResponse(text="done"),
    ]

    class Scripted:
        async def complete(self, messages, tools=None, params=None):
            return responses.pop(0)

    monkeypatch.setattr(
        director_module,
        "resolve",
        lambda *a, **k: ResolvedModel("f", "f", Scripted(), Capabilities(streaming=False)),
    )

    cid = ConversationRepository().create("f", "f")

    async def collect():
        return [e async for e in Director(registry, stream=True).run(cid, "read it")]

    events = await asyncio.wait_for(collect(), timeout=10)

    kinds = [e.type for e in events]
    assert "confirmation_required" not in kinds
    assert "tool_result" in kinds and kinds[-1] == "done"
