"""Phase 5: two real modes, and a loop that says what it is doing.

Plan mode was eight lines in `Chat.jsx` prepending a sentence to the user's
message. The backend had no reference to it: the tool schemas, the permission
gate and dispatch were identical either way, so the only thing between plan mode
and a deleted file was the model choosing to obey prose.
"""

from __future__ import annotations

import pytest

from psok.agent.director import STATUSES, Director
from psok.agent.planning import PLAN_TOOL_NAME, parse_plan
from psok.db.repositories import ConversationRepository, MessageRepository
from psok.runtime.types import Capabilities, ModelResponse, ResolvedModel, ToolCall
from psok.security.confirmation import ConfirmationService, auto_approve
from psok.tools.base import RiskLevel, Tool, ToolContext, ToolResult
from psok.tools.registry import ToolRegistry


def _tool(name: str, risk: RiskLevel) -> Tool:
    async def handler(args, ctx):
        return ToolResult.ok(f"{name} ran")

    return Tool(
        name=name,
        description="d",
        parameters={"type": "object", "properties": {}},
        handler=handler,
        risk=risk,
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry(ConfirmationService(auto_approve))
    registry.register(_tool("view_file", RiskLevel.LOW))
    registry.register(_tool("write_file", RiskLevel.MEDIUM))
    registry.register(_tool("run_shell_command", RiskLevel.HIGH))
    return registry


class _Scripted:
    def __init__(self, responses):
        self.responses = list(responses)
        self.seen_tools: list[list[str]] = []
        self.seen_system: list[str] = []

    async def complete(self, messages, tools=None, params=None):
        self.seen_tools.append([t.name for t in tools or []])
        self.seen_system.append(next((m["content"] for m in messages if m["role"] == "system"), ""))
        return self.responses.pop(0) if self.responses else ModelResponse(text="done")


def _patch(monkeypatch, client):
    model = ResolvedModel(
        provider="fake",
        model="fake-1",
        client=client,
        capabilities=Capabilities(streaming=False, context_window=32_000),
    )
    monkeypatch.setattr("psok.agent.director.resolve", lambda *a, **k: model)


async def _run(director, cid, message="do a thing"):
    return [e async for e in director.run(cid, message)]


# --- 5.1 plan mode is enforced, not requested -------------------------------


async def test_plan_mode_withholds_every_tool_that_changes_anything(db, monkeypatch):
    """The registry decides, not the model. `RiskLevel.LOW` already means
    "changes nothing", which is the judgement the permission gate has trusted
    since it shipped.

    Mutation check: drop `read_only=planning` from the `schemas` call.
    """
    client = _Scripted([ModelResponse(text="here is the plan")])
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    await _run(Director(_registry(), memory=False, retrieval=False, mode="plan"), cid)

    offered = set(client.seen_tools[0])
    assert "view_file" in offered
    assert "write_file" not in offered and "run_shell_command" not in offered
    assert PLAN_TOOL_NAME in offered, "the model needs a way to hand the plan back"


async def test_chat_mode_offers_everything(db, monkeypatch):
    """Chat mode stays a single fast pass and pays nothing for plan mode."""
    client = _Scripted([ModelResponse(text="done")])
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    await _run(Director(_registry(), memory=False, retrieval=False), cid)

    offered = set(client.seen_tools[0])
    assert {"view_file", "write_file", "run_shell_command"} <= offered
    assert PLAN_TOOL_NAME not in offered, "no plan tool in a turn that is not planning"


async def test_a_write_during_a_plan_turn_is_refused_by_the_registry(db, monkeypatch):
    """The verification this phase was specified with: a `write_file` attempt in
    plan mode is refused *by the registry*, not declined by the model.

    Mutation check: delete the `ctx.read_only` guard in `dispatch`.
    """
    registry = _registry()
    result = await registry.dispatch(
        "write_file", {"path": "x"}, ToolContext(conversation_id="c", read_only=True)
    )

    assert result.is_error
    assert "planning rather than acting" in result.content
    assert "do not try this tool again" in result.content

    allowed = await registry.dispatch(
        "view_file", {"path": "x"}, ToolContext(conversation_id="c", read_only=True)
    )
    assert not allowed.is_error, "reading is the whole point of a plan turn"


async def test_a_plan_turn_refuses_a_write_even_when_the_model_asks(db, monkeypatch):
    """End to end through the loop, not just the registry in isolation."""
    client = _Scripted(
        [
            ModelResponse(tool_calls=[ToolCall(id="c1", name="write_file", arguments={})]),
            ModelResponse(text="I could not"),
        ]
    )
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    events = await _run(Director(_registry(), memory=False, retrieval=False, mode="plan"), cid)

    results = [e for e in events if e.type == "tool_result"]
    assert results and results[0].data["is_error"]
    assert "planning rather than acting" in results[0].data["content"]


async def test_the_plan_instruction_never_reaches_the_transcript(db, monkeypatch):
    """The old prefix was part of the user's message, so it was replayed on
    every later iteration and every later turn -- a conversation asked for a
    plan once kept being asked forever.

    Mutation check: prepend `PLAN_INSTRUCTION` to `user_message` instead.
    """
    client = _Scripted([ModelResponse(text="the plan")])
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    await _run(Director(_registry(), memory=False, retrieval=False, mode="plan"), cid, "tidy up")

    history = MessageRepository().history(cid)
    assert history[0].content == "tidy up", "the user's message, unedited"
    assert not any("<mode name=" in (m.content or "") for m in history)
    # It does reach the model -- on the system prompt, where it is not persisted.
    assert '<mode name="plan">' in client.seen_system[0]


async def test_submitting_a_plan_ends_the_turn_with_structured_steps(db, monkeypatch):
    """An interface cannot offer "approve" on a paragraph."""
    client = _Scripted(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(
                        id="p1",
                        name=PLAN_TOOL_NAME,
                        arguments={
                            "summary": "Tidy the vault",
                            "steps": [
                                {"title": "List the files", "detail": "read only"},
                                {"title": "Rename the strays", "tools": ["write_file"]},
                            ],
                        },
                    )
                ]
            )
        ]
    )
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    events = await _run(Director(_registry(), memory=False, retrieval=False, mode="plan"), cid)

    plans = [e for e in events if e.type == "plan"]
    assert len(plans) == 1
    assert plans[0].data["summary"] == "Tidy the vault"
    assert [s["title"] for s in plans[0].data["steps"]] == ["List the files", "Rename the strays"]
    assert events[-1].type == "done"

    # Persisted as the assistant's own words: "approved" means nothing if the
    # thing approved is not in the history the executing turn reads.
    history = MessageRepository().history(cid)
    assert "Rename the strays" in history[-1].content


def test_a_sloppy_plan_call_is_salvaged_rather_than_dropped():
    """A model that returns a bare string has still told us the step."""
    plan = parse_plan({"steps": ["Do the thing", {"title": "And this"}, {"nope": 1}, 7]})
    assert [s.title for s in plan.steps] == ["Do the thing", "And this"]


# --- 5.2 status frames ------------------------------------------------------


async def test_the_turn_says_what_it_is_doing(db, monkeypatch):
    """Every one of these already happened inside the loop and none was visible:
    the composer said "Thinking" from the moment a turn opened until the first
    token, whatever the wait actually was."""
    client = _Scripted(
        [
            ModelResponse(tool_calls=[ToolCall(id="c1", name="view_file", arguments={})]),
            ModelResponse(text="done"),
        ]
    )
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    events = await _run(Director(_registry(), memory=False, retrieval=False), cid)

    states = [e.data["state"] for e in events if e.type == "status"]
    assert "thinking" in states
    assert "tool" in states
    assert states[-1] == "completed"
    assert set(states) <= set(STATUSES), "the vocabulary is closed"


async def test_a_plan_turn_says_planning_not_thinking(db, monkeypatch):
    client = _Scripted([ModelResponse(text="x")])
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    events = await _run(Director(_registry(), memory=False, retrieval=False, mode="plan"), cid)

    assert "planning" in [e.data["state"] for e in events if e.type == "status"]


async def test_a_failed_turn_is_named_as_failed(db, monkeypatch):
    class _Boom:
        async def complete(self, *a, **k):
            raise RuntimeError("nope")

    _patch(monkeypatch, _Boom())
    cid = ConversationRepository().create("fake", "fake-1")
    events = await _run(Director(_registry(), memory=False, retrieval=False), cid)

    assert [e.data["state"] for e in events if e.type == "status"][-1] == "failed"
    assert events[-1].type == "error"


# --- 5.3 the turn-cost line -------------------------------------------------


async def test_done_carries_what_the_turn_cost(db, monkeypatch):
    """`execution_logs.duration_ms` has held this since logging shipped and
    nothing has ever read it.

    Mutation check: drop `**_cost(...)` from the `done` payload.
    """
    client = _Scripted(
        [
            ModelResponse(tool_calls=[ToolCall(id="c1", name="view_file", arguments={})]),
            ModelResponse(text="done"),
        ]
    )
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    events = await _run(Director(_registry(), memory=False, retrieval=False), cid)

    done = events[-1].data
    assert done["steps"] == 2
    assert done["tools"] == 1
    assert isinstance(done["duration_ms"], int) and done["duration_ms"] >= 0


# --- the HTTP surface -------------------------------------------------------


@pytest.fixture
def client(psok_home):
    from fastapi.testclient import TestClient

    from psok.api.main import app

    with TestClient(app) as c:
        yield c


def test_an_unknown_mode_is_refused_before_the_stream_opens(client, psok_home):
    """A mode nobody honours would silently act when the user asked for a plan.
    Rejected up front, like an unknown provider, rather than inside an open SSE
    body where the failure reads as a truncated response."""
    from psok.config import configured_providers

    provider = next(iter(configured_providers()), None)
    if provider is None:
        pytest.skip("no provider configured in this isolated home")

    created = client.post(
        "/api/conversations", json={"provider": provider, "model": "m"}
    )
    if created.status_code != 200:
        pytest.skip("provider declares no default model here")
    cid = created.json()["id"]

    refused = client.post(f"/api/conversations/{cid}/turn", json={"message": "hi", "mode": "yolo"})
    assert refused.status_code == 400
    assert "yolo" in refused.json()["detail"]


# --- 5.1, second half: approve, edit, and progress through the plan ---------


async def test_an_executing_turn_reports_progress_through_the_plan(db, monkeypatch):
    """The spec asked for `step_started`/`step_done`. They come from the model's
    own `begin_step` calls -- inferring the current step from which tools were
    called would be inventing a progress bar, and an invented one is worse than
    none.

    Mutation check: delete the `STEP_TOOL_NAME` branch in the tool loop.
    """
    from psok.agent.planning import STEP_TOOL_NAME

    client = _Scripted(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(id="s1", name=STEP_TOOL_NAME, arguments={"number": 1, "title": "One"})
                ]
            ),
            ModelResponse(
                tool_calls=[
                    ToolCall(id="s2", name=STEP_TOOL_NAME, arguments={"number": 2, "title": "Two"})
                ]
            ),
            ModelResponse(text="finished"),
        ]
    )
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    events = await _run(
        Director(_registry(), memory=False, retrieval=False),
        cid,
        "Approved. Carry out the plan.",
    )

    started = [e.data["number"] for e in events if e.type == "step_started"]
    done = [e.data["number"] for e in events if e.type == "step_done"]
    assert started == [1, 2]
    # Step 1 closes when step 2 opens; step 2 closes when the turn does.
    assert done == [1, 2]
    assert events[-1].type == "done"


async def test_begin_step_is_only_offered_when_a_plan_is_being_carried_out(db, monkeypatch):
    """A tool with nothing to describe is one models call anyway."""
    from psok.agent.planning import STEP_TOOL_NAME

    client = _Scripted([ModelResponse(text="ok"), ModelResponse(text="ok")])
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    await _run(Director(_registry(), memory=False, retrieval=False), cid, "what time is it")
    assert STEP_TOOL_NAME not in client.seen_tools[0]

    await _run(
        Director(_registry(), memory=False, retrieval=False), cid, "Approved. Carry out the plan."
    )
    assert STEP_TOOL_NAME in client.seen_tools[1]


async def test_an_unfinished_step_is_left_open_rather_than_claimed_finished(db, monkeypatch):
    """A model that starts a step and never mentions it again has not finished
    it, and saying it did would be the interface inventing the outcome."""
    from psok.agent.planning import STEP_TOOL_NAME

    client = _Scripted(
        [
            ModelResponse(
                tool_calls=[ToolCall(id="s1", name=STEP_TOOL_NAME, arguments={"number": 1})]
            ),
            ModelResponse(text="I gave up"),
        ]
    )
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    events = await _run(
        Director(_registry(), memory=False, retrieval=False), cid, "Approved. go"
    )
    # It closes at the end of the turn, and only then -- never mid-turn on a
    # guess about which tool call ended it.
    assert [e.data["number"] for e in events if e.type == "step_done"] == [1]


def test_an_edited_plan_travels_with_the_approval():
    """The model's original is already in the transcript, so approving without
    sending the edit would approve the plan the user just changed."""
    from psok.agent.planning import APPROVAL_MESSAGE, Plan, PlanStep, approval_message

    assert approval_message(None) == APPROVAL_MESSAGE
    edited = approval_message(Plan(steps=[PlanStep(title="Do it differently")]))
    assert "Do it differently" in edited
    assert "begin_step" in edited


# --- 5.2, second half: no state is declared without being emitted -----------


def test_no_status_is_declared_without_being_emitted():
    """A name in the list that nothing sends is a reserved enum slot, which the
    ground rules forbid. `generating` was exactly that.

    Mutation check: add a state to `STATUSES` and do not emit it.
    """
    import re
    from pathlib import Path

    source = Path("psok/agent/director.py").read_text()
    emitted = set(re.findall(r'"state": "(\w+)"', source))
    emitted |= {
        name
        for pair in re.findall(r'"state": "(\w+)" if [^,]+ else "(\w+)"', source)
        for name in pair
    }
    assert set(STATUSES) - emitted == set()


async def test_generating_is_announced_when_the_answer_starts(db, monkeypatch):
    """"Thinking" used to stay on screen underneath text already arriving."""
    client = _Scripted([ModelResponse(text="the answer")])
    _patch(monkeypatch, client)

    cid = ConversationRepository().create("fake", "fake-1")
    events = await _run(Director(_registry(), memory=False, retrieval=False), cid)

    states = [e.data["state"] for e in events if e.type == "status"]
    assert "generating" in states
    assert states.index("thinking") < states.index("generating")


# --- escalation: the fast model asking for the slow one ---------------------


def _heavy(monkeypatch, provider="nvidia", model="deepseek-v4-pro"):
    """A resolvable `heavy` tier, without a providers.yaml or a network."""
    heavy = ResolvedModel(
        provider=provider,
        model=model,
        client=_Scripted([]),
        capabilities=Capabilities(streaming=False, context_window=32_000),
    )
    monkeypatch.setattr(
        "psok.agent.director.resolve_tier", lambda tier, **k: heavy if tier == "heavy" else None
    )
    return heavy


@pytest.mark.asyncio
async def test_the_model_can_hand_a_hard_job_to_a_bigger_one(db, monkeypatch):
    """The only party that knows the job is too big is the model doing it. A
    classifier would cost a round trip on every message to answer a question
    most messages do not raise, and a heuristic on message length guesses
    silently -- so the model says so, through a tool the director offers,
    never registers, and answers itself.

    The turn ends. Nothing has run, exactly as in plan mode, and the interface
    asks before the slower model is spent.

    Mutation check: stop appending `ESCALATE_TOOL` in `Director.run`, or
    dispatch the call instead of intercepting it.
    """
    from psok.agent.escalation import ESCALATE_TOOL_NAME, ESCALATION_MARKER

    client = _Scripted([
        ModelResponse(
            text=None,
            tool_calls=[ToolCall(id="1", name=ESCALATE_TOOL_NAME,
                                 arguments={"reason": "this needs a schema migration designed"})],
        )
    ])
    _patch(monkeypatch, client)
    _heavy(monkeypatch)

    cid = ConversationRepository().create("fake", "fake-1", "t")
    director = Director(registry=_registry(), retrieval=None, memory=None)
    events = await _run(director, cid, "redesign the task schema")

    assert ESCALATE_TOOL_NAME in client.seen_tools[0], "offered on an ordinary chat turn"

    escalations = [e for e in events if e.type == "escalation"]
    assert len(escalations) == 1
    assert escalations[0].data["reason"] == "this needs a schema migration designed"
    assert escalations[0].data["to_model"] == "nvidia/deepseek-v4-pro"
    assert escalations[0].data["from_model"] == "fake/fake-1"
    assert [e.type for e in events][-1] == "done", "the turn ends; nothing runs"

    stored = MessageRepository().history(cid)
    assert str(stored[-1].content).startswith(ESCALATION_MARKER), (
        "persisted as the assistant's own words, so a reload still shows the question"
    )


@pytest.mark.asyncio
async def test_the_same_question_is_not_asked_twice(db, monkeypatch):
    """"Answer anyway" is the user re-sending the message. Without this the fast
    model would escalate again and the two buttons would be one button.

    Read from the transcript rather than from a flag on the request: a flag in
    the interface does not survive a reload, and the transcript does.

    Mutation check: drop the `was_escalated` guard in `Director.run`.
    """
    from psok.agent.escalation import ESCALATE_TOOL_NAME

    client = _Scripted([ModelResponse(text="fine, here it is")])
    _patch(monkeypatch, client)
    _heavy(monkeypatch)

    cid = ConversationRepository().create("fake", "fake-1", "t")
    messages = MessageRepository()
    messages.append(cid, "user", "redesign the task schema")
    messages.append(cid, "assistant", "**Escalation requested.** it is big\n\nneeds more")

    director = Director(registry=_registry(), retrieval=None, memory=None)
    await _run(director, cid, "redesign the task schema")

    assert ESCALATE_TOOL_NAME not in client.seen_tools[0], (
        "the transcript already carries the request; asking again is a loop"
    )


@pytest.mark.asyncio
async def test_no_heavy_tier_means_no_offer(db, monkeypatch):
    """An offer PSOK cannot honour is worse than no offer. A machine with one
    provider has nothing to escalate to, and the tool is simply absent rather
    than present and failing.

    Mutation check: offer `ESCALATE_TOOL` regardless of `resolve_tier`.
    """
    from psok.agent.escalation import ESCALATE_TOOL_NAME

    client = _Scripted([ModelResponse(text="answered")])
    _patch(monkeypatch, client)
    monkeypatch.setattr("psok.agent.director.resolve_tier", lambda tier, **k: None)

    cid = ConversationRepository().create("fake", "fake-1", "t")
    director = Director(registry=_registry(), retrieval=None, memory=None)
    await _run(director, cid, "do a thing")

    assert ESCALATE_TOOL_NAME not in client.seen_tools[0]


@pytest.mark.asyncio
async def test_reasoning_mode_runs_on_the_heavy_tier_and_does_not_offer_to_escalate(
    db, monkeypatch
):
    """The user already chose to wait. Offering the bigger model to the bigger
    model would be a loop with a confirmation in it.

    Mutation check: resolve the conversation's own model in reasoning mode, or
    keep offering the tool.
    """
    from psok.agent.escalation import ESCALATE_TOOL_NAME

    client = _Scripted([ModelResponse(text="thought about it")])
    _patch(monkeypatch, client)
    heavy = _heavy(monkeypatch)
    heavy.client = client

    cid = ConversationRepository().create("fake", "fake-1", "t")
    director = Director(registry=_registry(), retrieval=None, memory=None, mode="reasoning")
    await _run(director, cid, "think hard about this")

    assert ESCALATE_TOOL_NAME not in client.seen_tools[0]
    assert "reasoning" in client.seen_system[0], "the mode reaches the system prompt"


def test_reasoning_is_a_mode_the_api_accepts(client, psok_home):
    """Mutation check: drop "reasoning" from `TURN_MODES`."""
    from psok.api.main import TURN_MODES

    assert TURN_MODES == {"chat", "plan", "reasoning"}

