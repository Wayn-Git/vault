"""A turn always ends with something usable (ADR-0016).

The loop already handled the failures it was looking for -- a provider that
refuses, a stream that stops, a tool whose handler raises. Everything else went
up through `Director.run`'s catch-all and ended the turn on a bare error frame:
the model never heard that one thing failed, so it could not work around it, and
the user lost the work of every step before it.

The failure modes here are the ones recorded in `.bugs/`: a provider out of
quota handing over to a second provider that then returns a server error, a
model that stops without answering, and a reply cut off mid-sentence. Each test
names the mutation that makes it fail.
"""

from __future__ import annotations

import pytest

from backend.agent.director import Director, Guards
from backend.db.repositories import ConversationRepository, MessageRepository
from backend.runtime.failures import FailureKind
from backend.runtime.types import Capabilities, ModelResponse, ResolvedModel, ToolCall
from backend.security.confirmation import ConfirmationService, auto_approve
from backend.tools.base import RiskLevel, Tool, ToolResult
from backend.tools.registry import ToolRegistry

#: The frames after which a turn is over, as `backend/api/main.py` defines them.
TERMINAL = {"done", "error", "guard"}


def registry() -> ToolRegistry:
    async def echo(args, ctx):
        return ToolResult.ok(f"echo: {args.get('text', '')}")

    reg = ToolRegistry(ConfirmationService(auto_approve))
    reg.register(
        Tool(
            name="echo",
            description="echo text back",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            handler=echo,
            risk=RiskLevel.LOW,
        )
    )
    return reg


class Scripted:
    """A provider that hands back a scripted list, raising what it is given."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.seen_system: list[str] = []
        self.seen_tools: list[list[str]] = []

    async def complete(self, messages, tools=None, params=None):
        self.calls += 1
        self.seen_system.append(
            "\n".join(m["content"] for m in messages if m["role"] == "system")
        )
        self.seen_tools.append([t.name for t in tools or []])
        nxt = self.responses.pop(0) if self.responses else ModelResponse(text="done")
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def _model(client, provider="fake", model="fake-1", **caps) -> ResolvedModel:
    return ResolvedModel(
        provider=provider,
        model=model,
        client=client,
        capabilities=Capabilities(streaming=False, context_window=32_000, **caps),
    )


@pytest.fixture
def scripted(monkeypatch):
    """Install one scripted provider for the whole turn."""

    def install(responses, **caps):
        client = Scripted(responses)
        resolved = _model(client, **caps)
        monkeypatch.setattr("backend.agent.director.resolve", lambda *a, **k: resolved)
        return client

    return install


async def run(director, cid, message="do the thing"):
    return [event async for event in director.run(cid, message)]


def terminals(events) -> list[str]:
    return [e.type for e in events if e.type in TERMINAL]


def answer_of(events) -> str:
    """Whatever the turn ended up handing back, from whichever frame ended it."""
    last = events[-1]
    return (last.data.get("text") or last.data.get("message") or "").strip()


# --- failures that used to escape the loop entirely -------------------------


async def test_a_gate_that_raises_does_not_end_the_turn(db, scripted, monkeypatch):
    """`ToolRegistry.dispatch` catches what the *handler* raises. Everything
    before the handler -- the permission gate, the connector lookup, the audit
    write -- was uncovered, and a raise there went out of `_run` from inside a
    `for` loop with no handler over it.

    Mutation check: drop the `except BaseException` from `Director._execute`.
    """
    client = scripted(
        [
            ModelResponse(tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "hi"})]),
            ModelResponse(text="I could not use that tool, so here is what I know."),
        ]
    )

    async def explode(*a, **k):
        raise RuntimeError("the confirmation store is locked")

    monkeypatch.setattr(ConfirmationService, "check", explode)

    cid = ConversationRepository().create("fake", "fake-1")
    events = await run(Director(registry(), memory=False, retrieval=False), cid)

    assert terminals(events) == ["done"], "the turn survives a broken dispatch path"
    failed = [e for e in events if e.type == "tool_result" and e.data["is_error"]]
    assert failed, "the model has to be told the tool failed"
    assert "the confirmation store is locked" in failed[0].data["content"]
    assert client.calls == 2, "the loop carried on and asked for an answer"
    assert answer_of(events) == "I could not use that tool, so here is what I know."


async def test_an_unserializable_tool_argument_does_not_end_the_turn(db, scripted):
    """The repeat-call guard fingerprinted arguments with `json.dumps`, which
    raises on a self-referential value -- before the tool runs, so a single
    malformed call from the model cost the whole turn.

    Mutation check: inline `json.dumps(call.arguments, sort_keys=True)` again.
    """
    looping: dict = {"text": "hi"}
    looping["self"] = looping

    scripted(
        [
            ModelResponse(tool_calls=[ToolCall(id="c1", name="echo", arguments=looping)]),
            ModelResponse(text="done despite the odd arguments"),
        ]
    )
    cid = ConversationRepository().create("fake", "fake-1")
    events = await run(Director(registry(), memory=False, retrieval=False), cid)

    assert terminals(events) == ["done"]
    assert answer_of(events) == "done despite the odd arguments"


async def test_a_broken_system_prompt_degrades_rather_than_aborting(db, scripted, monkeypatch):
    """An unreadable skill file or a capability table mid-migration is not a
    reason the user cannot have an answer: the model can work from the base
    prompt alone.

    Mutation check: remove the try/except around `build_system_prompt`.
    """
    client = scripted([ModelResponse(text="answered from the base prompt")])

    def explode(**_):
        raise OSError("skills directory vanished")

    monkeypatch.setattr("backend.agent.director.build_system_prompt", explode)

    cid = ConversationRepository().create("fake", "fake-1")
    events = await run(Director(registry(), memory=False, retrieval=False), cid)

    assert terminals(events) == ["done"]
    assert answer_of(events) == "answered from the base prompt"
    warnings = [e.data["message"] for e in events if e.type == "warning"]
    assert any("context could not be assembled" in w for w in warnings), "and it says so"
    assert "You are PSOK" in client.seen_system[0], "the base prompt still went out"


async def test_an_unreadable_history_degrades_rather_than_aborting(db, scripted, monkeypatch):
    """A row the budgeter cannot measure used to take the turn with it.

    Mutation check: remove the try/except around `budget_history`.
    """
    def explode(*a, **k):
        raise ValueError("a tool_calls blob will not serialize")

    monkeypatch.setattr("backend.agent.director.budget_history", explode)
    scripted([ModelResponse(text="answered from the last exchange")])

    cid = ConversationRepository().create("fake", "fake-1")
    events = await run(Director(registry(), memory=False, retrieval=False), cid)

    assert terminals(events) == ["done"]
    assert answer_of(events) == "answered from the last exchange"


async def test_a_transcript_write_that_fails_does_not_end_the_turn(db, scripted, monkeypatch):
    """The write is how a turn is remembered, not how it is delivered. A locked
    database cost the answer that was already on screen.

    Mutation check: call `self.messages.append` directly instead of `_persist`.
    """
    import sqlite3

    calls = {"n": 0}
    real = MessageRepository.append

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:  # the assistant's answer
            raise sqlite3.OperationalError("database is locked")
        return real(self, *a, **k)

    monkeypatch.setattr(MessageRepository, "append", flaky)
    scripted([ModelResponse(text="delivered even though it was not saved")])

    cid = ConversationRepository().create("fake", "fake-1")
    events = await run(Director(registry(), memory=False, retrieval=False), cid)

    assert terminals(events) == ["done"]
    assert answer_of(events) == "delivered even though it was not saved"


# --- the sequence recorded in .bugs/ ---------------------------------------


async def test_quota_then_a_server_error_still_settles_the_turn(db, monkeypatch):
    """The screenshot in `.bugs/`: groq runs out of quota, the turn hands over
    to nvidia, nvidia returns a 500, and the user is left with
    "nvidia returned a server error." and nothing else.

    The fallback itself is out of scope here. What is pinned is that the stream
    settles exactly once and the frame that settles it says which provider gave
    up and why -- never a bare traceback.

    Mutation check: re-raise instead of yielding the final `error` frame.
    """
    from backend.runtime.chain import Link

    class Quota(Exception):
        kind = FailureKind.NON_RETRYABLE_RATE_LIMIT

    class ServerError(Exception):
        kind = FailureKind.UPSTREAM_UNHEALTHY

    chain = [Link("groq", "llama-3.3-70b"), Link("nvidia", "nemotron-3-super-120b")]
    monkeypatch.setattr("backend.agent.director.build_chain", lambda *a, **k: chain)

    clients = [Scripted([Quota("rate limit")]), Scripted([ServerError("500")])]
    handed = iter(clients)

    def resolve(provider, model, **_):
        return _model(next(handed), provider=provider, model=model)

    monkeypatch.setattr("backend.agent.director.resolve", resolve)

    cid = ConversationRepository().create("groq", "llama-3.3-70b")
    events = await run(Director(registry(), memory=False, retrieval=False), cid)

    assert terminals(events) == ["error"], "one terminal frame, and the stream closes"
    assert "nvidia" in events[-1].data["message"], "it names who gave up"
    assert "Traceback" not in events[-1].data["message"]
    assert [e.data["state"] for e in events if e.type == "status"][-1] == "failed"
    # The handover is announced while it happens, so the user is not surprised
    # by an answer from a provider they did not choose.
    assert any("groq" in e.data["message"] for e in events if e.type == "warning")


async def test_an_empty_reply_is_continued_then_summarised(db, scripted):
    """"the model stopped without answering" used to close the turn on an empty
    bubble, discarding tool results the user had watched arrive.

    Mutation check: delete the `_summarise` call and leave `answer` empty.
    """
    scripted(
        [
            ModelResponse(tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "hi"})]),
            ModelResponse(text=""),
            ModelResponse(text=""),
            ModelResponse(text=""),
        ]
    )
    cid = ConversationRepository().create("fake", "fake-1")
    events = await run(
        Director(registry(), memory=False, retrieval=False, guards=Guards(max_continuations=2)),
        cid,
    )

    assert terminals(events) == ["done"]
    assert [e.data["state"] for e in events if e.type == "status"].count("retrying") == 2
    text = answer_of(events)
    assert text, "the turn must not end on an empty bubble"
    assert "echo" in text, "and it names the work that did happen"


async def test_a_truncated_reply_is_continued(db, scripted):
    """A provider that cut the model off mid-sentence ended the turn there.

    Mutation check: drop `truncated` from the `unfinished` test.
    """
    scripted(
        [
            ModelResponse(text="the first half", stop_reason="length"),
            ModelResponse(text="and the second half", stop_reason="stop"),
        ]
    )
    cid = ConversationRepository().create("fake", "fake-1")
    events = await run(Director(registry(), memory=False, retrieval=False), cid)

    assert terminals(events) == ["done"]
    assert answer_of(events) == "and the second half"
    said = [m.content for m in MessageRepository().history(cid) if m.role == "assistant"]
    assert said == ["the first half", "and the second half"], "both halves are kept"


async def test_a_guard_hands_back_the_work_not_only_the_reason(db, scripted):
    """`guard` is terminal, and it used to carry a reason and nothing else -- so
    a turn stopped at its iteration limit after real work reported only
    "iteration limit reached".

    Mutation check: yield a bare `Event("guard", {"reason": ...})` again.
    """
    scripted(
        [
            ModelResponse(
                text=f"step {n}",
                tool_calls=[ToolCall(id=f"c{n}", name="echo", arguments={"text": str(n)})],
            )
            for n in range(6)
        ]
    )
    cid = ConversationRepository().create("fake", "fake-1")
    events = await run(
        Director(registry(), memory=False, retrieval=False, guards=Guards(max_iterations=3)), cid
    )

    assert terminals(events) == ["guard"]
    guard = events[-1].data
    assert guard["reason"] == "iteration limit reached"
    assert "step 0" in guard["text"], "what the user already read comes back with it"
    assert guard["tools"] == 3 and guard["duration_ms"] >= 0


# --- the property all of the above are instances of -------------------------


@pytest.mark.parametrize(
    "responses",
    [
        pytest.param([ModelResponse(text="plain")], id="plain-answer"),
        pytest.param([ModelResponse(text="")], id="empty-answer"),
        pytest.param([ModelResponse(text="cut", stop_reason="length")], id="truncated"),
        pytest.param([RuntimeError("the provider exploded")], id="provider-raised"),
        pytest.param(
            [ModelResponse(tool_calls=[ToolCall(id="c", name="nope", arguments={})])],
            id="unknown-tool",
        ),
        pytest.param(
            [ModelResponse(tool_calls=[ToolCall(id="c", name="echo", arguments={"text": "x"})])],
            id="tool-then-nothing",
        ),
    ],
)
async def test_every_turn_ends_with_exactly_one_terminal_frame(db, scripted, responses):
    """The property the SSE contract rests on. An interface keys its composer
    off a terminal frame: none leaves the field disabled forever, and two makes
    a turn look like it ended twice.

    Mutation check: remove the `except Exception` from `Director.run`.
    """
    scripted(responses)
    cid = ConversationRepository().create("fake", "fake-1")
    events = await run(
        Director(registry(), memory=False, retrieval=False, guards=Guards(max_iterations=3)), cid
    )

    assert len(terminals(events)) == 1, f"got {terminals(events)}"
    assert events[-1].type in TERMINAL, "and it is the last thing the reader sees"


# --- the last step answers instead of dead-ending -------------------------


async def test_the_final_step_forces_an_answer_not_an_iteration_guard(db, scripted):
    """A model that keeps calling tools used to exhaust `max_iterations` and end
    on "iteration limit reached" with nothing to show. The last step now
    withholds tools and asks for an answer, so the turn wraps up.

    Mutation check: drop the `final_step` tool-withholding in the loop.
    """
    from backend.agent.director import FINAL_STEP_INSTRUCTION

    # Two tool-calling steps, then the third step -- the last -- is offered no
    # tools, so a real model answers with text. (The fake returns whatever is
    # scripted regardless of the tools argument, so the text response stands in
    # for what a toolless model would do.)
    client = scripted(
        [
            ModelResponse(
                text="step 0",
                tool_calls=[ToolCall(id="c0", name="echo", arguments={"text": "0"})],
            ),
            ModelResponse(
                text="step 1",
                tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "1"})],
            ),
            ModelResponse(text="here is what I found"),
        ]
    )
    cid = ConversationRepository().create("fake", "fake-1")
    events = await run(
        Director(registry(), memory=False, retrieval=False, guards=Guards(max_iterations=3)), cid
    )

    assert terminals(events) == ["done"], "the turn ends on an answer, not a guard"
    # The last request the model saw offered no tools and carried the wrap-up
    # instruction.
    assert client.seen_tools[-1] == [], "no tools are offered on the final step"
    assert any(FINAL_STEP_INSTRUCTION in sys for sys in client.seen_system)
    assert answer_of(events)
