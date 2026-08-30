from __future__ import annotations

import pytest

from backend.agent.director import Director, Guards
from backend.agent.prompt import budget_history, build_system_prompt
from backend.config import ProviderConfig
from backend.db.repositories import ConversationRepository, MessageRepository
from backend.runtime.providers.google import sanitize_schema
from backend.runtime.providers.openai_compat import OpenAICompatClient
from backend.runtime.registry import PROVIDER_REGISTRY, ProviderNotConfigured, resolve
from backend.runtime.types import Capabilities, ModelResponse, ResolvedModel, ToolCall
from backend.security.confirmation import ConfirmationService, auto_approve
from backend.tools.base import RiskLevel, Tool, ToolResult
from backend.tools.registry import ToolRegistry

# --------------------------------------------------------------------------
# provider abstraction
# --------------------------------------------------------------------------


def test_unknown_provider_falls_through_to_openai_compatible(psok_home, monkeypatch):
    """The fallback is what gives PSOK an open-ended provider set (ADR-0001)."""
    from backend import config

    yaml_path = psok_home / "config" / "providers.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        "providers:\n"
        "  - name: my-vllm\n"
        "    base_url: http://localhost:8000/v1\n"
        "    default_model: llama-3.1-8b\n"
    )
    assert "my-vllm" not in PROVIDER_REGISTRY

    resolved = resolve("my-vllm")
    assert isinstance(resolved.client, OpenAICompatClient)
    assert resolved.model == "llama-3.1-8b"
    assert config  # keep the import meaningful


def test_unconfigured_unknown_provider_is_reported(psok_home):
    with pytest.raises(ProviderNotConfigured):
        resolve("not-a-real-provider")


def test_openai_payload_drops_reasoning_when_tools_present():
    """A provider quirk, absorbed in the adapter and invisible to the loop."""
    from backend.runtime.types import ModelParameters, ToolSchema

    client = OpenAICompatClient(base_url="http://x/v1", api_key=None, model="gpt-5")
    tool = ToolSchema(name="t", description="", parameters={"type": "object"})
    params = ModelParameters(reasoning_effort="high")

    with_tools = client._build_payload([], [tool], params)
    without_tools = client._build_payload([], None, params)
    assert "reasoning_effort" not in with_tools
    assert without_tools["reasoning_effort"] == "high"


def test_gemini_schema_sanitization():
    """Gemini rejects unions and non-string enums that other providers accept."""
    sanitized = sanitize_schema(
        {
            "type": "object",
            "properties": {
                "count": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "mode": {"type": "string", "enum": [1, 2]},
            },
            "additionalProperties": False,
        }
    )
    assert "anyOf" not in sanitized["properties"]["count"]
    assert sanitized["properties"]["count"]["type"] == "integer"
    assert sanitized["properties"]["mode"]["enum"] == ["1", "2"]
    assert "additionalProperties" not in sanitized


def test_anthropic_maps_tool_results_to_content_blocks():
    from backend.runtime.providers.anthropic import _to_anthropic_messages

    system, messages = _to_anthropic_messages(
        [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "42", "tool_call_id": "c1"},
        ]
    )
    assert system == "be helpful"
    assert messages[-1]["content"][0]["type"] == "tool_result"


# --------------------------------------------------------------------------
# prompt assembly
# --------------------------------------------------------------------------


def test_system_prompt_includes_environment_and_skills(psok_home):
    from backend.skills.loader import seed_builtin_skills

    seed_builtin_skills()
    prompt = build_system_prompt(workspace_root="/tmp/ws")
    assert "<environment>" in prompt and "/tmp/ws" in prompt
    assert "psok-intro" in prompt, "skills are advertised by name in the prompt"
    assert "Diagnosing a failure" not in prompt, "the skill body must NOT be inlined"


def test_history_budgeting_drops_oldest_first():
    messages = [{"role": "user", "content": "x" * 4000} for _ in range(50)]
    kept = budget_history(messages, context_window=8000, system_prompt="", reserved=1000)
    assert 0 < len(kept) < len(messages)


def test_budgeting_never_leaves_an_orphan_tool_result():
    messages = [
        {"role": "user", "content": "a" * 8000},
        {"role": "tool", "content": "orphan", "tool_call_id": "c1"},
        {"role": "user", "content": "b"},
    ]
    kept = budget_history(messages, context_window=2000, system_prompt="", reserved=500)
    assert not kept or kept[0]["role"] != "tool"


# --------------------------------------------------------------------------
# the loop
# --------------------------------------------------------------------------


class ScriptedClient:
    """A fake provider so the loop is testable with no network."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def complete(self, messages, tools=None, params=None):
        self.calls += 1
        return self.responses.pop(0) if self.responses else ModelResponse(text="done")


def scripted_model(responses) -> ResolvedModel:
    return ResolvedModel(
        provider="fake",
        model="fake-1",
        client=ScriptedClient(responses),
        capabilities=Capabilities(context_window=32000),
    )


@pytest.fixture
def patched_resolve(monkeypatch):
    def install(responses):
        model = scripted_model(responses)
        monkeypatch.setattr("backend.agent.director.resolve", lambda *a, **k: model)
        return model

    return install


def echo_registry() -> ToolRegistry:
    async def echo(args, ctx):
        return ToolResult.ok(f"echo: {args.get('text', '')}")

    registry = ToolRegistry(ConfirmationService(auto_approve))
    registry.register(
        Tool(
            name="echo",
            description="echo text back",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            handler=echo,
            risk=RiskLevel.LOW,
        )
    )
    return registry


async def collect(director, cid, message):
    return [event async for event in director.run(cid, message)]


async def test_loop_terminates_on_plain_text(db, patched_resolve):
    patched_resolve([ModelResponse(text="hello there")])
    cid = ConversationRepository().create("fake", "fake-1")
    events = await collect(Director(echo_registry()), cid, "hi")

    assert events[-1].type == "done"
    roles = [m.role for m in MessageRepository().history(cid)]
    assert roles == ["user", "assistant"]


async def test_loop_executes_a_tool_then_finishes(db, patched_resolve):
    patched_resolve(
        [
            ModelResponse(tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "hi"})]),
            ModelResponse(text="the tool said hi"),
        ]
    )
    cid = ConversationRepository().create("fake", "fake-1")
    events = await collect(Director(echo_registry()), cid, "use the tool")

    kinds = [e.type for e in events]
    assert "tool_call" in kinds and "tool_result" in kinds and kinds[-1] == "done"

    history = MessageRepository().history(cid)
    assert [m.role for m in history] == ["user", "assistant", "tool", "assistant"]
    assert "echo: hi" in history[2].content


async def test_iteration_guard_stops_a_runaway_loop(db, patched_resolve):
    forever = [
        ModelResponse(tool_calls=[ToolCall(id=f"c{i}", name="echo", arguments={"text": str(i)})])
        for i in range(50)
    ]
    patched_resolve(forever)
    cid = ConversationRepository().create("fake", "fake-1")
    director = Director(echo_registry(), guards=Guards(max_iterations=3))
    events = await collect(director, cid, "go")

    assert events[-1].type == "guard"
    assert "iteration limit" in events[-1].data["reason"]


async def test_repeated_identical_calls_are_broken_out_of(db, patched_resolve):
    same = [
        ModelResponse(tool_calls=[ToolCall(id=f"c{i}", name="echo", arguments={"text": "same"})])
        for i in range(10)
    ]
    patched_resolve(same)
    cid = ConversationRepository().create("fake", "fake-1")
    director = Director(echo_registry(), guards=Guards(max_iterations=8, max_repeated_calls=2))
    events = await collect(director, cid, "go")

    nudges = [
        e for e in events if e.type == "tool_result" and "Stop repeating it" in e.data["content"]
    ]
    assert nudges, "the loop should tell the model to stop repeating itself"


async def test_model_error_is_reported_not_raised(db, monkeypatch):
    class Failing:
        async def complete(self, *a, **k):
            raise ConnectionError("provider unreachable")

    model = ResolvedModel("fake", "fake-1", Failing(), Capabilities())
    monkeypatch.setattr("backend.agent.director.resolve", lambda *a, **k: model)

    cid = ConversationRepository().create("fake", "fake-1")
    events = await collect(Director(echo_registry()), cid, "hi")
    assert events[-1].type == "error" and "unreachable" in events[-1].data["message"]


async def test_denied_tool_result_reaches_the_model(db, patched_resolve):
    """A denial must come back as an observation, not end the run."""

    async def deny(_):
        return False

    patched_resolve(
        [
            ModelResponse(tool_calls=[ToolCall(id="c1", name="risky", arguments={})]),
            ModelResponse(text="understood, I won't do that"),
        ]
    )

    async def handler(args, ctx):
        return ToolResult.ok("should not run")

    registry = ToolRegistry(ConfirmationService(deny))
    registry.register(
        Tool(
            name="risky",
            description="",
            parameters={"type": "object"},
            handler=handler,
            risk=RiskLevel.HIGH,
        )
    )

    cid = ConversationRepository().create("fake", "fake-1")
    events = await collect(Director(registry), cid, "do the risky thing")
    results = [e for e in events if e.type == "tool_result"]
    assert results and results[0].data["is_error"]
    assert events[-1].type == "done"


# --------------------------------------------------------------------------
# credential isolation
# --------------------------------------------------------------------------


def test_redaction_covers_keys_and_value_patterns():
    from backend.secrets import redact

    cleaned = redact(
        {
            "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
            "note": "token is sk-abcdefghijklmnopqrstuvwxyz here",
            "nested": {"Authorization": "Bearer abcdefghijklmnopqrst"},
            "safe": "ordinary text",
        }
    )
    assert cleaned["api_key"] == "[redacted]"
    assert "sk-abcdefghij" not in cleaned["note"]
    assert cleaned["nested"]["Authorization"] == "[redacted]"
    assert cleaned["safe"] == "ordinary text"


def test_audit_log_stores_redacted_arguments(db):
    from backend.db.repositories import ExecutionLogRepository

    repo = ExecutionLogRepository()
    repo.record(
        tool_name="gmail_send",
        tool_source="integration",
        arguments={"api_key": "sk-verysecretvalue123456"},
    )
    stored = repo.recent(1)[0]["arguments"]
    assert "sk-verysecret" not in stored and "[redacted]" in stored


def test_provider_config_holds_a_reference_not_a_secret():
    config = ProviderConfig(name="openai", api_key_ref="psok/openai")
    assert config.api_key_ref == "psok/openai"
    assert not hasattr(config, "api_key")


# --------------------------------------------------------------------------
# transient failure handling
#
# Hosted endpoints return sporadic 5xx under load; observed directly against
# NVIDIA NIM, where identical requests succeed on retry.
# --------------------------------------------------------------------------


class _FlakyTransport:
    """Fails with the given statuses, then succeeds."""

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.attempts = 0

    async def handler(self, request):
        import httpx

        self.attempts += 1
        if self.statuses:
            code = self.statuses.pop(0)
            return httpx.Response(code, json={"error": {"message": "transient"}})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "recovered"}, "finish_reason": "stop"}],
                "usage": {},
            },
        )


def _patch_transport(monkeypatch, flaky):
    import httpx

    real_init = httpx.AsyncClient.__init__

    def init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(flaky.handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)


async def test_transient_500_is_retried(monkeypatch):
    from backend.runtime import http as runtime_http
    from backend.runtime.providers import openai_compat

    monkeypatch.setattr(runtime_http, "backoff", lambda attempt: 0.0)
    flaky = _FlakyTransport([500, 500])
    _patch_transport(monkeypatch, flaky)

    client = openai_compat.OpenAICompatClient(base_url="http://x/v1", api_key=None, model="m")
    response = await client.complete([{"role": "user", "content": "hi"}])
    assert response.text == "recovered"
    assert flaky.attempts == 3


async def test_rate_limit_is_retried(monkeypatch):
    from backend.runtime import http as runtime_http
    from backend.runtime.providers import openai_compat

    monkeypatch.setattr(runtime_http, "backoff", lambda attempt: 0.0)
    flaky = _FlakyTransport([429])
    _patch_transport(monkeypatch, flaky)

    client = openai_compat.OpenAICompatClient(base_url="http://x/v1", api_key=None, model="m")
    assert (await client.complete([{"role": "user", "content": "hi"}])).text == "recovered"


async def test_client_errors_are_not_retried_and_surface_the_body(monkeypatch):
    from backend.runtime import http as runtime_http
    from backend.runtime.providers import openai_compat

    monkeypatch.setattr(runtime_http, "backoff", lambda attempt: 0.0)
    flaky = _FlakyTransport([400])
    _patch_transport(monkeypatch, flaky)

    client = openai_compat.OpenAICompatClient(base_url="http://x/v1", api_key=None, model="m")
    with pytest.raises(runtime_http.ProviderHTTPError) as excinfo:
        await client.complete([{"role": "user", "content": "hi"}])
    assert "transient" in str(excinfo.value), "the provider's own message must reach the caller"
    assert flaky.attempts == 1, "a 400 is the caller's fault; retrying it is pointless"


async def test_persistent_failure_eventually_gives_up(monkeypatch):
    from backend.runtime import http as runtime_http
    from backend.runtime.providers import openai_compat

    monkeypatch.setattr(runtime_http, "backoff", lambda attempt: 0.0)
    flaky = _FlakyTransport([503] * 10)
    _patch_transport(monkeypatch, flaky)

    client = openai_compat.OpenAICompatClient(base_url="http://x/v1", api_key=None, model="m")
    with pytest.raises(runtime_http.ProviderHTTPError):
        await client.complete([{"role": "user", "content": "hi"}])
    assert flaky.attempts == runtime_http.MAX_RETRIES + 1


async def test_reasoning_content_is_kept_out_of_the_answer(monkeypatch):
    """Nemotron and similar return chain-of-thought in a sibling field.

    It must not be mistaken for the answer, or the user reads the model's
    private deliberation instead of its reply.
    """
    import httpx

    from backend.runtime.providers import openai_compat

    async def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "The time is 3pm.",
                            "reasoning_content": "Let me think about which timezone...",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    stub = type("Stub", (), {})()
    stub.attempts = 0
    stub.handler = handler
    _patch_transport(monkeypatch, stub)

    client = openai_compat.OpenAICompatClient(base_url="http://x/v1", api_key=None, model="m")
    response = await client.complete([{"role": "user", "content": "time?"}])

    assert response.text == "The time is 3pm."
    assert response.reasoning == "Let me think about which timezone..."
    assert "timezone" not in (response.text or ""), "reasoning must not leak into the answer"


# --------------------------------------------------------------------------
# streaming
# --------------------------------------------------------------------------


def _sse(chunks: list[dict]) -> bytes:
    import json as _json

    body = "".join(f"data: {_json.dumps(c)}\n\n" for c in chunks)
    return (body + "data: [DONE]\n\n").encode()


def _patch_stream(monkeypatch, payload: bytes, status: int = 200):
    import httpx

    real_init = httpx.AsyncClient.__init__

    async def handler(request):
        return httpx.Response(status, content=payload)

    def init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)


async def test_streaming_yields_text_deltas_then_a_final_response(monkeypatch):
    from backend.runtime.providers.openai_compat import OpenAICompatClient

    _patch_stream(
        monkeypatch,
        _sse(
            [
                {"choices": [{"delta": {"content": "Hel"}}]},
                {"choices": [{"delta": {"content": "lo"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ]
        ),
    )

    client = OpenAICompatClient(base_url="http://x/v1", api_key=None, model="m")
    events = [e async for e in client.stream([{"role": "user", "content": "hi"}])]

    assert [e.text for e in events if e.type == "text"] == ["Hel", "lo"]
    assert events[-1].type == "done"
    assert events[-1].response.text == "Hello"
    assert events[-1].response.stop_reason == "stop"


async def test_streamed_tool_calls_are_reassembled_from_fragments(monkeypatch):
    """Arguments arrive a few characters at a time and are useless until complete."""
    from backend.runtime.providers.openai_compat import OpenAICompatClient

    _patch_stream(
        monkeypatch,
        _sse(
            [
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "function": {"name": "get_time", "arguments": ""},
                                    }
                                ]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [{"index": 0, "function": {"arguments": '{"tz"'}}]
                            }
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "function": {"arguments": ': "Asia/Tokyo"}'}}
                                ]
                            }
                        }
                    ]
                },
                {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            ]
        ),
    )

    client = OpenAICompatClient(base_url="http://x/v1", api_key=None, model="m")
    events = [e async for e in client.stream([{"role": "user", "content": "time?"}])]

    calls = events[-1].response.tool_calls
    assert len(calls) == 1
    assert calls[0].name == "get_time"
    assert calls[0].arguments == {"tz": "Asia/Tokyo"}
    assert calls[0].id == "call_1"


async def test_streamed_reasoning_stays_separate_from_the_answer(monkeypatch):
    from backend.runtime.providers.openai_compat import OpenAICompatClient

    _patch_stream(
        monkeypatch,
        _sse(
            [
                {"choices": [{"delta": {"reasoning_content": "thinking..."}}]},
                {"choices": [{"delta": {"content": "42"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
            ]
        ),
    )

    client = OpenAICompatClient(base_url="http://x/v1", api_key=None, model="m")
    events = [e async for e in client.stream([{"role": "user", "content": "?"}])]

    assert [e.type for e in events if e.type == "reasoning"] == ["reasoning"]
    final = events[-1].response
    assert final.text == "42"
    assert final.reasoning == "thinking..."


async def test_anthropic_streaming_assembles_content_blocks(monkeypatch):
    from backend.runtime.providers.anthropic import AnthropicClient

    _patch_stream(
        monkeypatch,
        _sse(
            [
                {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hi"},
                },
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "tool_use", "id": "tu_1", "name": "lookup"},
                },
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": '{"q": "x"}'},
                },
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
            ]
        ),
    )

    client = AnthropicClient(api_key="k", model="m", base_url="http://x/v1")
    events = [e async for e in client.stream([{"role": "user", "content": "hi"}])]

    assert [e.text for e in events if e.type == "text"] == ["Hi"]
    final = events[-1].response
    assert final.text == "Hi"
    assert final.tool_calls[0].name == "lookup"
    assert final.tool_calls[0].arguments == {"q": "x"}


async def test_director_emits_deltas_when_streaming(db, monkeypatch):
    """The loop must surface increments without losing the assembled response."""
    from backend.agent.director import Director
    from backend.runtime.types import Capabilities, ModelResponse, ResolvedModel, StreamEvent

    class StreamingClient:
        async def complete(self, *a, **k):
            raise AssertionError("complete() must not be used when streaming is available")

        async def stream(self, messages, tools=None, params=None):
            yield StreamEvent(type="text", text="par")
            yield StreamEvent(type="text", text="tial")
            yield StreamEvent(type="done", response=ModelResponse(text="partial"))

    model = ResolvedModel("fake", "fake-1", StreamingClient(), Capabilities(streaming=True))
    monkeypatch.setattr("backend.agent.director.resolve", lambda *a, **k: model)

    cid = ConversationRepository().create("fake", "fake-1")
    events = [e async for e in Director(echo_registry(), stream=True).run(cid, "hi")]

    assert [e.data["text"] for e in events if e.type == "assistant_delta"] == ["par", "tial"]
    assert events[-1].type == "done" and events[-1].data["text"] == "partial"
    assert MessageRepository().history(cid)[-1].content == "partial"


async def test_director_falls_back_when_the_provider_cannot_stream(db, monkeypatch):
    from backend.agent.director import Director
    from backend.runtime.types import Capabilities, ModelResponse, ResolvedModel

    class NonStreamingClient:
        async def complete(self, messages, tools=None, params=None):
            return ModelResponse(text="whole answer")

    model = ResolvedModel("fake", "fake-1", NonStreamingClient(), Capabilities(streaming=False))
    monkeypatch.setattr("backend.agent.director.resolve", lambda *a, **k: model)

    cid = ConversationRepository().create("fake", "fake-1")
    events = [e async for e in Director(echo_registry(), stream=True).run(cid, "hi")]

    assert not [e for e in events if e.type == "assistant_delta"]
    assert events[-1].data["text"] == "whole answer"


def test_google_declares_no_streaming_because_it_has_none():
    """A capability flag that lies is worse than one that admits a gap."""
    from backend.config import ProviderConfig
    from backend.runtime.providers import google

    resolved = google.initialize(ProviderConfig(name="google", default_model="gemini-2.0-flash"))
    assert resolved.capabilities.streaming is False
    assert not hasattr(resolved.client, "stream")


# --------------------------------------------------------------------------
# turns that stop before the work is done
# --------------------------------------------------------------------------


async def test_an_empty_reply_continues_the_turn_instead_of_ending_it(db, patched_resolve):
    """Models stop after a tool result rather than acting on it, returning no
    text at all. That used to end the turn on an empty bubble, and the user had
    to type "continue" to get work they had already asked for."""
    patched_resolve(
        [
            ModelResponse(tool_calls=[ToolCall(id="c1", name="echo", arguments={"text": "hi"})]),
            ModelResponse(text="   "),
            ModelResponse(text="the repository is cloned and the skill is installed"),
        ]
    )
    cid = ConversationRepository().create("fake", "fake-1")
    events = await collect(Director(echo_registry()), cid, "install that skill")

    assert events[-1].type == "done"
    assert events[-1].data["text"] == "the repository is cloned and the skill is installed"
    assert any(e.type == "warning" for e in events)

    # The blank turn is not written to history: nothing was said.
    contents = [m.content for m in MessageRepository().history(cid) if m.role == "assistant"]
    assert "   " not in contents


async def test_a_truncated_answer_is_continued_rather_than_left_mid_sentence(db, patched_resolve):
    patched_resolve(
        [
            ModelResponse(text="Here is the first half", stop_reason="length"),
            ModelResponse(text=" and here is the rest."),
        ]
    )
    cid = ConversationRepository().create("fake", "fake-1")
    events = await collect(Director(echo_registry()), cid, "write something long")

    assert events[-1].type == "done"
    said = [m.content for m in MessageRepository().history(cid) if m.role == "assistant"]
    assert said == ["Here is the first half", " and here is the rest."]


async def test_the_continuation_is_an_instruction_not_part_of_the_transcript(db, patched_resolve):
    """The nudge steers the next call only. Writing it to history would put
    words in the user's mouth and it would be recalled in every later turn."""
    model = patched_resolve([ModelResponse(text=""), ModelResponse(text="done properly")])
    seen: list[list[dict]] = []
    original = model.client.complete

    async def recording(messages, tools=None, params=None):
        seen.append(list(messages))
        return await original(messages, tools=tools, params=params)

    model.client.complete = recording

    cid = ConversationRepository().create("fake", "fake-1")
    await collect(Director(echo_registry()), cid, "do the thing")

    # The second call carries the instruction; the transcript does not.
    assert any("Continue now" in m.get("content", "") for m in seen[1])
    assert not any("Continue now" in (m.content or "") for m in MessageRepository().history(cid))
    assert all(m.role != "system" for m in MessageRepository().history(cid))


async def test_a_model_that_only_ever_returns_nothing_still_ends(db, patched_resolve):
    """The continuation is bounded: an always-empty model must not spin."""
    model = patched_resolve([ModelResponse(text="") for _ in range(10)])
    cid = ConversationRepository().create("fake", "fake-1")
    events = await collect(Director(echo_registry(), guards=Guards(max_continuations=2)), cid, "hi")

    assert events[-1].type == "done"
    assert model.client.calls == 3  # the first call, plus two continuations
    warnings = [e.data.get("message", "") for e in events if e.type == "warning"]
    assert any("without an answer" in message for message in warnings)
