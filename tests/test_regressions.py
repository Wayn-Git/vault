"""Regression tests for bugs found during a dedicated audit.

Each test names the defect it locks down. They live together so the audit's
findings stay visible rather than dissolving into the suite.
"""

from __future__ import annotations

import json
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

        async def reconcile(self):
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


async def test_the_interface_learns_a_confirmation_is_pending_before_it_answers(
    api, db, monkeypatch
):
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


# --- 21: the OpenAI-compatible adapter replayed PSOK's own message rows -----


def test_replayed_tool_calls_use_the_chat_completions_wire_shape():
    """The Anthropic and Google adapters translate history; this one forwarded
    PSOK's normalized rows untouched. A single-iteration turn hid it, but the
    moment a tool result was replayed the payload carried a tool call with no
    `type` and an `arguments` object instead of a JSON string, plus PSOK's own
    `tool_name` and `is_error` columns on the tool row. Lenient servers ignore
    all of that; OpenAI and schema-validating servers answer 400, which breaks
    every multi-step turn on the adapter that covers most providers."""
    from psok.runtime.providers.openai_compat import OpenAICompatClient

    client = OpenAICompatClient(base_url="http://x/v1", api_key=None, model="m")
    history = [
        {"role": "system", "content": "you are psok"},
        {"role": "user", "content": "read it"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "function": {"name": "view_file", "arguments": {"path": "a.md"}}}
            ],
        },
        {
            "role": "tool",
            "content": "1\thello",
            "tool_call_id": "call_1",
            "tool_name": "view_file",
            "is_error": False,
        },
    ]

    messages = client._build_payload(history, None, None)["messages"]

    assistant = messages[2]
    call = assistant["tool_calls"][0]
    assert call["type"] == "function", "the wire format requires a type on every tool call"
    assert isinstance(call["function"]["arguments"], str), "arguments travel as a JSON string"
    assert json.loads(call["function"]["arguments"]) == {"path": "a.md"}
    assert call["id"] == "call_1"

    tool_row = messages[3]
    assert tool_row == {"role": "tool", "tool_call_id": "call_1", "content": "1\thello"}, (
        "PSOK's own columns must not travel to the provider"
    )


def test_arguments_already_serialized_are_not_double_encoded():
    """Tool calls that never round-tripped through storage arrive with the
    provider's own JSON string. Re-encoding it would send a quoted string."""
    from psok.runtime.providers.openai_compat import OpenAICompatClient

    client = OpenAICompatClient(base_url="http://x/v1", api_key=None, model="m")
    payload = client._build_payload(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c", "function": {"name": "t", "arguments": '{"a": 1}'}}
                ],
            }
        ],
        None,
        None,
    )
    assert payload["messages"][0]["tool_calls"][0]["function"]["arguments"] == '{"a": 1}'


# --- 22: a provider that ignores `stream: true` answered into the void ------


async def test_an_endpoint_that_does_not_stream_still_produces_an_answer(monkeypatch):
    """Plenty of OpenAI-compatible servers answer a streaming request with an
    ordinary JSON body, which yields no SSE frames at all. The adapter turned
    that into a `done` event carrying an empty response, so the turn ended with
    a blank answer, no tool calls, no warning and no error -- the model's actual
    reply, tool call included, silently discarded."""
    import httpx

    from psok.runtime.providers.openai_compat import OpenAICompatClient

    completion = {
        "choices": [
            {"message": {"role": "assistant", "content": "answered"}, "finish_reason": "stop"}
        ]
    }
    real_init = httpx.AsyncClient.__init__

    async def handler(request):
        # Whatever it is asked, this endpoint replies with a plain completion.
        return httpx.Response(200, json=completion)

    def init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)

    client = OpenAICompatClient(base_url="http://x/v1", api_key=None, model="m")
    events = [e async for e in client.stream([{"role": "user", "content": "hi"}])]

    assert [e.type for e in events] == ["done"]
    assert events[0].response.text == "answered"


async def test_an_answer_that_never_streamed_is_still_emitted_once(db, monkeypatch):
    """The loop treated "took the streaming path" as "already showed the
    answer". An adapter falling back to a plain call inside stream() then
    delivered nothing the interface may render -- docs are explicit that
    done.text must not be rendered, so the reply vanished."""
    import psok.agent.director as director_module
    from psok.agent.director import Director
    from psok.db.repositories import ConversationRepository
    from psok.runtime.types import Capabilities, ModelResponse, ResolvedModel, StreamEvent
    from psok.security.confirmation import ConfirmationService
    from psok.tools.registry import ToolRegistry

    class FallingBackClient:
        async def complete(self, messages, tools=None, params=None):
            return ModelResponse(text="the whole answer")

        async def stream(self, messages, tools=None, params=None):
            # No deltas: exactly what the adapter yields when the endpoint
            # ignored `stream: true` and it re-asked without streaming.
            yield StreamEvent(type="done", response=ModelResponse(text="the whole answer"))

    monkeypatch.setattr(
        director_module,
        "resolve",
        lambda *a, **k: ResolvedModel("f", "f", FallingBackClient(), Capabilities(streaming=True)),
    )

    cid = ConversationRepository().create("f", "f")
    director = Director(ToolRegistry(ConfirmationService()), stream=True, retrieval=False)
    events = [e async for e in director.run(cid, "hello")]

    answers = [e for e in events if e.type in ("assistant_text", "assistant_delta")]
    assert [e.data["text"] for e in answers] == ["the whole answer"], (
        "the answer must arrive exactly once, and it must arrive"
    )
    assert events[-1].type == "done"


# --- 23: switching a connector on never reached the running API -------------


async def test_a_connector_switched_on_mid_session_becomes_usable(api, db, tmp_path, monkeypatch):
    """One manager serves the process for its lifetime and only connected at
    the moment it was built, so a connector the user switched on in the
    interface stayed dark until PSOK was restarted. The toggle wrote a row
    nothing ever acted on."""
    from psok.capabilities import CapabilityService, Kind
    from psok.mcp.config import ServerConfig, Transport, add_server
    from psok.mcp.manager import MCPManager
    from psok.tools.base import RiskLevel, Tool, ToolResult, ToolSource

    add_server(ServerConfig(name="notes", transport=Transport.STDIO, command="true"))

    connected: list[str] = []

    class FakeManager(MCPManager):
        async def connect_server(self, config):
            connected.append(config.name)

            async def handler(args, ctx):
                return ToolResult.ok("ok")

            self.connections[config.name] = _AlwaysConnected()
            self.registry.register(
                Tool(
                    name=f"note__mcp__{config.name}",
                    description="",
                    parameters={},
                    handler=handler,
                    risk=RiskLevel.MEDIUM,
                    source=ToolSource.MCP,
                    server_name=config.name,
                )
            )
            return 1

        async def disconnect_server(self, name):
            self.connections.pop(name, None)
            self.registry.unregister_server(name)

        async def shutdown(self):
            pass

    monkeypatch.setattr(api, "MCPManager", FakeManager)

    registry, _ = await api._registry_for(str(tmp_path))
    assert connected == [], "a connector nobody switched on must not be started"

    CapabilityService().set_enabled(Kind.CONNECTOR, "notes", True)
    again, _ = await api._registry_for(str(tmp_path))

    assert again is registry, "the same registry, not a rebuilt one"
    assert connected == ["notes"]
    assert "note__mcp__notes" in [t.name for t in registry.list()]

    # ...and switching it off again takes the tools away.
    CapabilityService().set_enabled(Kind.CONNECTOR, "notes", False)
    await api._registry_for(str(tmp_path))
    assert "note__mcp__notes" not in [t.name for t in registry.list()]


class _AlwaysConnected:
    connected = True

    def __init__(self, tools=()):
        self.tools = list(tools)

    async def disconnect(self):
        pass


# --- 24: Stop only closed the browser's read, not the turn ------------------


async def test_stopping_a_turn_ends_the_loop_and_the_tool_call(db, monkeypatch):
    """The interface had a Stop button that aborted the fetch. The turn behind
    it kept calling models and tools, and a call suspended on a confirmation
    held the gate open for its full timeout with nobody left to answer it."""
    import asyncio

    import psok.agent.director as director_module
    from psok.agent.director import Director
    from psok.db.repositories import ConversationRepository, MessageRepository
    from psok.runtime.types import Capabilities, ModelResponse, ResolvedModel, ToolCall
    from psok.security.confirmation import ConfirmationService
    from psok.tools.base import RiskLevel, Tool, ToolResult
    from psok.tools.registry import ToolRegistry

    never_answered = asyncio.Event()

    async def hangs(args, ctx):
        await never_answered.wait()  # a confirmation nobody will answer
        return ToolResult.ok("finished")

    registry = ToolRegistry(ConfirmationService())
    registry.register(
        Tool(
            name="slow_tool",
            description="hangs",
            parameters={},
            handler=hangs,
            risk=RiskLevel.LOW,
        )
    )

    calls = 0

    class Scripted:
        async def complete(self, messages, tools=None, params=None):
            nonlocal calls
            calls += 1
            return ModelResponse(
                tool_calls=[ToolCall(id=f"c{calls}", name="slow_tool", arguments={})]
            )

    monkeypatch.setattr(
        director_module,
        "resolve",
        lambda *a, **k: ResolvedModel("f", "f", Scripted(), Capabilities(streaming=False)),
    )

    cid = ConversationRepository().create("f", "f")
    cancel = asyncio.Event()
    events = []

    async def drive():
        async for event in Director(registry, retrieval=False, memory=False).run(
            cid, "do it", cancel
        ):
            events.append(event)
            if event.type == "tool_call":
                cancel.set()

    await asyncio.wait_for(drive(), timeout=5)

    kinds = [e.type for e in events]
    assert kinds[-1] == "guard"
    assert events[-1].data["reason"] == "stopped by the user"
    assert calls == 1, "the loop must not call the model again after being stopped"

    interrupted = [e for e in events if e.type == "tool_result"]
    assert interrupted and interrupted[0].data["is_error"]
    assert "interrupted" in interrupted[0].data["content"]

    persisted = MessageRepository().history(cid)[-1]
    assert persisted.role == "tool" and persisted.is_error, (
        "the trajectory must not claim a call that never finished"
    )


def test_the_api_can_stop_a_turn_it_is_streaming(api, db):
    """Nothing can interrupt a turn without a route to ask through."""
    import asyncio

    from psok.db.repositories import ConversationRepository

    cid = ConversationRepository().create("f", "f")
    with pytest.raises(Exception) as unknown:
        api.stop_turn(cid)
    assert "404" in str(unknown.value) or "no turn" in str(unknown.value)

    cancel = asyncio.Event()
    api._active_turns[cid] = cancel
    try:
        assert api.stop_turn(cid) == {"status": "stopping"}
        assert cancel.is_set()
    finally:
        api._active_turns.pop(cid, None)


# --- 25: an existing database from an older version broke startup ----------


LEGACY_MEMORIES = """
CREATE TABLE memories (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    fact                   TEXT NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active', 'superseded')),
    superseded_by          INTEGER REFERENCES memories(id),
    source_conversation_id TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
    last_recalled_at       TEXT,
    recall_count           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_memories_status ON memories(status, created_at);
CREATE TABLE conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT,
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL,
    memory_enabled INTEGER NOT NULL DEFAULT 1,
    system_prompt_override TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE credentials (id INTEGER PRIMARY KEY, ref TEXT);
"""


def test_a_database_from_an_older_version_still_opens(tmp_path):
    """schema.sql is written with CREATE TABLE IF NOT EXISTS, which is a no-op
    against a table that already exists in an older shape -- and the index over
    its new column then failed with a bare "no such column: superseded_at",
    taking startup with it. Upgrading in place is the normal case for a single
    user, so a stale database has to be brought forward, not deleted."""
    import sqlite3

    from psok.db import connection

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(LEGACY_MEMORIES)
    old.execute(
        "INSERT INTO conversations (id, title, provider, model) VALUES ('c1', 't', 'p', 'm')"
    )
    old.execute("INSERT INTO memories (fact, source_conversation_id) VALUES ('an old fact', 'c1')")
    old.commit()
    old.close()

    conn = connection.connect(path)
    connection.migrate(conn)  # used to raise sqlite3.OperationalError

    columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    assert {"superseded_at", "conversation_id"} <= columns
    assert "status" in columns, "columns this version does not use are left alone"

    kept = conn.execute("SELECT fact FROM memories").fetchall()
    assert [r[0] for r in kept] == ["an old fact"], "existing rows survive the upgrade"

    # And the current code paths work against the upgraded table.
    from psok.memory import MemoryStore

    store = MemoryStore(conn)
    new_id = store.add("a new fact", "c1")
    assert {m.fact for m in store.live()} == {"an old fact", "a new fact"}
    assert store.supersede([new_id]) == 1
    assert [m.fact for m in store.live()] == ["an old fact"]


def test_migrating_twice_changes_nothing(tmp_path):
    import sqlite3

    from psok.db import connection

    path = tmp_path / "twice.db"
    conn = connection.connect(path)
    connection.migrate(conn)
    before = sorted(r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE sql NOT NULL"))
    connection.migrate(conn)
    after = sorted(r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE sql NOT NULL"))
    assert before == after
    assert isinstance(conn, sqlite3.Connection)


# --- 26: a connector switch that reported intent, not fact ------------------


async def test_switching_a_connector_on_starts_it_and_says_what_happened(api, db, monkeypatch):
    """The switch wrote a capability row and left connecting to the next turn,
    so it read "on" whether the process had started, had died, or had never
    been asked to start. Nothing in the interface could tell the difference --
    the user saw connectors enabled and an agent with none of their tools."""
    from psok.mcp.config import ServerConfig, Transport, add_server
    from psok.mcp.manager import MCPManager
    from psok.tools.base import RiskLevel, Tool, ToolResult, ToolSource

    add_server(ServerConfig(name="browser", transport=Transport.STDIO, command="true"))

    class FakeManager(MCPManager):
        fail = False

        async def connect_server(self, config):
            # Same contract as the real one: connecting an already-connected
            # server replaces it rather than colliding with its own tools.
            await self.disconnect_server(config.name)
            if FakeManager.fail:
                self.errors[config.name] = "npx: command not found"
                raise RuntimeError("npx: command not found")

            async def handler(args, ctx):
                return ToolResult.ok("ok")

            self.connections[config.name] = _AlwaysConnected(tools=[1, 2, 3])
            self.registry.register(
                Tool(
                    name=f"navigate__mcp__{config.name}",
                    description="",
                    parameters={},
                    handler=handler,
                    risk=RiskLevel.MEDIUM,
                    source=ToolSource.MCP,
                    server_name=config.name,
                )
            )
            return 3

        async def disconnect_server(self, name):
            self.connections.pop(name, None)
            self.registry.unregister_server(name)

        async def shutdown(self):
            pass

    monkeypatch.setattr(api, "MCPManager", FakeManager)
    try:
        on = await api.toggle_capability(
            "connector", "browser", api.CapabilityToggle(enabled=True)
        )
        assert on["live"] == {"connected": True, "tools": 3, "error": None}, (
            "the response has to carry what actually happened"
        )

        listed = api.list_capabilities()["connectors"]
        row = next(c for c in listed if c["name"] == "browser")
        assert row["enabled"] is True
        assert row["live"]["connected"] is True and row["live"]["tools"] == 3

        off = await api.toggle_capability(
            "connector", "browser", api.CapabilityToggle(enabled=False)
        )
        assert off["live"]["connected"] is False
        assert not [t for t in api._mcp["registry"].list() if t.server_name == "browser"]

        # A server that cannot start reports the reason instead of reading "on".
        FakeManager.fail = True
        broken = await api.toggle_capability(
            "connector", "browser", api.CapabilityToggle(enabled=True)
        )
        assert broken["enabled"] is True, "the preference is still recorded"
        assert broken["live"]["connected"] is False
        assert "npx" in broken["live"]["error"], "the reason has to reach the interface"

        row = next(c for c in api.list_capabilities()["connectors"] if c["name"] == "browser")
        assert row["live"]["error"], "and it has to persist on the row, not just the response"
    finally:
        FakeManager.fail = False
        api._mcp.update({"manager": None, "registry": None, "workspace": None, "errors": {}})


async def test_removing_a_connector_takes_its_failure_with_it(db, psok_home):
    """A server removed from mcp.yaml left its error behind, so /api/health
    reported degraded forever over a connector that no longer existed."""
    from psok.mcp.config import ServerConfig, Transport, add_server, remove_server
    from psok.mcp.manager import MCPManager
    from psok.security.confirmation import ConfirmationService, auto_approve
    from psok.tools.registry import ToolRegistry

    add_server(ServerConfig(name="gone", transport=Transport.STDIO, command="true"))
    manager = MCPManager(ToolRegistry(ConfirmationService(auto_approve)), open_browser=False)
    manager.errors["gone"] = "npx: command not found"

    assert manager.state()["gone"]["error"]

    remove_server("gone")
    await manager.reconcile()

    assert "gone" not in manager.errors
    assert "gone" not in manager.state()
