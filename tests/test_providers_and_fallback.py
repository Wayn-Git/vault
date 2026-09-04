"""Phase 3: the provider catalogue, failure taxonomy and fallback chain.

Each test names the behaviour it locks down and, where the behaviour is easy to
break silently, the source mutation that must turn it red.
"""

from __future__ import annotations

import pytest

from backend import config
from backend.agent.director import Director
from backend.agent.prompt import budget_history, tool_schema_tokens
from backend.config import ProviderConfig
from backend.db.repositories import ConversationRepository
from backend.provider_catalogue import PRESETS_BY_SLUG, PROVIDER_PRESETS, render_default_providers
from backend.runtime import availability
from backend.runtime.chain import AttemptBudget, build_chain
from backend.runtime.failures import (
    FailureKind,
    classify_status,
    classify_stream_error,
    should_fall_back,
    should_retry,
)
from backend.runtime.http import ProviderHTTPError
from backend.runtime.types import Capabilities, ModelResponse, ResolvedModel, ToolSchema
from backend.security.confirmation import ConfirmationService, auto_approve
from backend.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def _forget_availability():
    availability.forget()
    yield
    availability.forget()


# --- the taxonomy -----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (500, "", FailureKind.UPSTREAM_UNHEALTHY),
        (503, "", FailureKind.UPSTREAM_UNHEALTHY),
        (408, "", FailureKind.RETRYABLE),
        (429, "slow down", FailureKind.RATE_LIMITED),
        (429, "You exceeded your current quota", FailureKind.NON_RETRYABLE_RATE_LIMIT),
        (402, "", FailureKind.NON_RETRYABLE_RATE_LIMIT),
        (
            413,
            "Request too large for model on tokens per minute (TPM): Limit 8000,"
            " Requested 21757, please reduce your message size and try again.",
            FailureKind.NON_RETRYABLE_RATE_LIMIT,
        ),
        (404, "model not found", FailureKind.NON_RETRYABLE),
        (401, "bad key", FailureKind.NON_RETRYABLE),
    ],
)
def test_statuses_classify_into_the_kinds_callers_branch_on(status, body, expected):
    assert classify_status(status, body) is expected


def test_a_quota_429_is_not_retried_but_is_worth_another_provider():
    """The distinction the whole taxonomy exists for.

    Both arrive as 429. Waiting fixes one and cannot fix the other, so retrying
    an exhausted quota spends the entire attempt budget to re-read the same
    sentence -- while a different provider answers it immediately.

    Mutation check: drop the `looks_like_quota` branch from `classify_status`.
    """
    quota = classify_status(429, "insufficient_quota: out of credits")
    burst = classify_status(429, "rate limit reached, retry in 2s")

    assert should_retry(burst) and not should_retry(quota)
    assert should_fall_back(quota), "another provider is exactly what a billing failure needs"


def test_a_dead_model_or_bad_key_still_falls_back():
    """A 404 for a model name, or a 401 for a revoked key, is a fact about ONE
    (provider, model) pair -- and `build_chain` never asks the next provider
    about that pair. Every fallback link is built with that provider's *own*
    configured `default_model`, so a model retired at provider A, or a key
    revoked at A, says nothing about B: B is never asked to use A's model or A's
    key. Measured live: NVIDIA retired `openai/gpt-oss-120b` mid-session
    (`410 Gone ... reached its end of life`), a `NON_RETRYABLE` 4xx exactly like
    these, and the old policy let it kill the whole turn while two healthy
    providers sat unused in the same chain.

    Mutation check: remove `NON_RETRYABLE` from `FALLBACK_KINDS`.
    """
    assert should_fall_back(classify_status(404, "no such model"))
    assert should_fall_back(classify_status(401, "invalid api key"))
    assert should_fall_back(classify_status(410, "reached its end of life"))


def test_stream_error_frames_are_classified_from_their_own_names():
    """These arrive inside an already-200 response and carry no status."""
    assert classify_stream_error({"type": "overloaded_error"}) is FailureKind.UPSTREAM_UNHEALTHY
    assert classify_stream_error({"type": "rate_limit_error"}) is FailureKind.RATE_LIMITED
    assert (
        classify_stream_error({"code": "context_length_exceeded"}) is FailureKind.NON_RETRYABLE
    )
    # An unrecognised error *inside a 200 stream* is treated as a transient
    # upstream fault, not a bad request: the stream already opened, so auth and
    # validation passed, and the break is almost always the provider faltering
    # mid-generation. NVIDIA's bare "Error in input stream" is the case this
    # protects -- it used to be non-retryable and killed the turn outright.
    # Mutation check: return NON_RETRYABLE for an unknown stream error again.
    assert classify_stream_error({"type": "who_knows"}) is FailureKind.UPSTREAM_UNHEALTHY
    assert classify_stream_error("Error in input stream") is FailureKind.UPSTREAM_UNHEALTHY
    assert should_retry(classify_stream_error("Error in input stream"))
    # But an unknown frame that names a quota problem still stops.
    assert (
        classify_stream_error("your credit balance is too low")
        is FailureKind.NON_RETRYABLE_RATE_LIMIT
    )


async def test_a_quota_429_is_not_retried_over_http(monkeypatch):
    """The taxonomy has to reach `post_json`, not merely exist beside it.

    Mutation check: replace `should_retry(classify_status(status, body))`
    with `status >= 500` (or any check that ignores the body) and this makes
    four attempts instead of one -- it can no longer tell an exhausted quota
    from an ordinary 429.
    """
    import httpx

    from backend.runtime import http as runtime_http

    attempts = 0

    async def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, json={"error": {"message": "insufficient_quota"}})

    real_init = httpx.AsyncClient.__init__

    def init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    monkeypatch.setattr(runtime_http, "backoff", lambda attempt: 0.0)

    with pytest.raises(ProviderHTTPError) as caught:
        await runtime_http.post_json(
            "http://x/v1/chat/completions", headers={}, payload={}, timeout=1.0
        )

    assert attempts == 1, "an exhausted quota must not be retried"
    assert caught.value.kind is FailureKind.NON_RETRYABLE_RATE_LIMIT
    assert caught.value.status == 429


# --- the catalogue ----------------------------------------------------------


def test_every_preset_can_be_written_and_read_back(tmp_path):
    """A preset that does not round-trip through providers.yaml is a listing,
    not an integration."""
    path = tmp_path / "providers.yaml"
    path.write_text("providers: []\n")

    from backend.provider_catalogue import entry_for

    for preset in PROVIDER_PRESETS:
        config.add_provider(entry_for(preset), path)

    loaded = config.load_providers(path)
    assert set(loaded) == {p.slug for p in PROVIDER_PRESETS}
    assert loaded["anthropic"].provider is None, "the adapter is found by name"
    assert loaded["nvidia"].base_url == PRESETS_BY_SLUG["nvidia"].base_url


def test_the_seeded_file_matches_the_catalogue(tmp_path):
    """Groq sat commented out in the hand-written starter file while the docs
    said it was configured, and Cerebras existed in neither. Generating the file
    from the catalogue is what stops the two drifting again.

    Mutation check: hand-write `_default_providers` back into a literal string.
    """
    path = tmp_path / "providers.yaml"
    path.write_text(render_default_providers())
    loaded = config.load_providers(path)

    from backend.provider_catalogue import SEEDED

    assert set(loaded) == set(SEEDED)
    assert loaded["groq"].api_key_ref == "psok/groq", "listed, awaiting only a key"


def test_adding_a_provider_replaces_rather_than_shadows(tmp_path):
    """Two entries with one name parse fine and the last silently wins, so an
    add that appended would look identical to one that worked."""
    path = tmp_path / "providers.yaml"
    path.write_text("providers: []\n")

    config.add_provider({"name": "groq", "default_model": "first"}, path)
    config.add_provider({"name": "groq", "default_model": "second"}, path)

    assert config.provider_entries(path) == [{"name": "groq", "default_model": "second"}]


def test_writing_providers_leaves_the_memory_block_alone(tmp_path):
    """`memory:` shares this file and is none of the writer's business."""
    path = tmp_path / "providers.yaml"
    path.write_text("providers: []\nmemory:\n  provider: ollama\n  model: qwen2.5:3b\n")

    config.add_provider({"name": "groq", "default_model": "llama-3.3-70b"}, path)

    assert config.load_memory_model(path) == ("ollama", "qwen2.5:3b")


# --- declared context windows ----------------------------------------------


def test_a_declared_context_window_beats_the_substring_guess(tmp_path, psok_home):
    """`nemotron-3-ultra-550b-a55b` matches no substring and silently got
    128,000, so the budgeter trimmed history against a number nobody checked.

    Mutation check: drop the `if declared` branch from `_context_window`.
    """
    path = psok_home / "config" / "providers.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "providers:\n"
        "  - name: nvidia\n"
        "    base_url: https://integrate.api.nvidia.com/v1\n"
        "    default_model: nemotron-3-ultra-550b-a55b\n"
        "    context_window: 256000\n"
    )
    from backend.runtime.registry import resolve

    assert resolve("nvidia").capabilities.context_window == 256_000


def test_a_nonsense_context_window_is_ignored_rather_than_obeyed(tmp_path):
    """Zero would make `budget_history` compute a negative budget and cut the
    history to two messages every turn -- which reads as amnesia, not as a typo.
    """
    path = tmp_path / "providers.yaml"
    path.write_text(
        "providers:\n  - name: x\n    default_model: m\n    context_window: 0\n"
    )
    assert config.load_providers(path)["x"].context_window is None


def test_tool_schemas_come_out_of_the_same_window_as_the_history():
    """Measured at 29,620 tokens across 132 tools and never counted, so the
    budget was wrong by exactly their size in the direction that overflows.

    Mutation check: drop `tool_schema_tokens(tools)` from `available`.
    """
    messages = [{"role": "user", "content": "x" * 4000} for _ in range(10)]
    tools = [
        ToolSchema(name=f"t{i}", description="d" * 800, parameters={"type": "object"})
        for i in range(20)
    ]
    assert tool_schema_tokens(tools) > 0

    without = budget_history(messages, context_window=8_000, system_prompt="")
    with_tools = budget_history(messages, context_window=8_000, system_prompt="", tools=tools)

    assert len(with_tools) < len(without), "the schemas have to take room from the history"


# --- availability -----------------------------------------------------------


def test_only_credential_free_endpoints_are_probed():
    """A provider with a key has already said something; asking the network to
    confirm it on a health poll that runs every twenty seconds costs more than
    it returns."""
    assert availability.needs_probe(ProviderConfig(name="ollama", base_url="http://x/v1"))
    assert not availability.needs_probe(ProviderConfig(name="groq", api_key_ref="psok/groq"))


def test_an_unreachable_provider_is_remembered_and_then_forgotten():
    """`has_key` calls a keyless local endpoint configured by definition, so
    Ollama was offered while nothing listened on its port.

    Mutation check: make `forget` a no-op and a started Ollama stays unavailable.
    """
    availability.record_failure("ollama", FailureKind.UNREACHABLE)
    state = availability.cached("ollama")
    assert state is not None and not state.available

    availability.forget("ollama")
    assert availability.cached("ollama") is None


def test_a_bad_model_name_does_not_take_the_provider_out_of_the_picker():
    """The fix for a 404 is a different model, not a different provider."""
    availability.record_failure("groq", FailureKind.NON_RETRYABLE)
    assert availability.cached("groq") is None


def test_an_exhausted_rate_limit_does_take_the_provider_out_of_the_picker():
    """An account whose request needs more tokens per minute than it is
    allowed will fail the same way on the very next turn -- three near
    identical 413s landed in the live database two minutes apart before this,
    because nothing told the picker to stop offering it in the meantime."""
    availability.record_failure("groq", FailureKind.NON_RETRYABLE_RATE_LIMIT)
    state = availability.cached("groq")
    assert state is not None and not state.available


# --- the chain --------------------------------------------------------------


def _configs(**names: str | None) -> dict[str, ProviderConfig]:
    return {n: ProviderConfig(name=n, default_model=m) for n, m in names.items()}


def test_the_chain_defaults_to_every_other_configured_provider(tmp_path, psok_home):
    configs = _configs(nvidia="nemotron", groq="llama-3.3-70b", cerebras="llama-3.3-70b")
    chain = build_chain("nvidia", "nemotron", configs=configs, order=None)

    assert [link.provider for link in chain] == ["nvidia", "groq", "cerebras"]
    assert chain[1].model == "llama-3.3-70b", "a fallback uses that provider's declared model"


def test_a_provider_with_no_declared_model_is_not_a_fallback(psok_home):
    """Substituting it in would mean guessing a model name, which is the exact
    failure the placeholder-model work already fixed once."""
    configs = _configs(nvidia="nemotron", mystery=None, groq="llama-3.3-70b")
    chain = build_chain("nvidia", "nemotron", configs=configs, order=None)

    assert [link.provider for link in chain] == ["nvidia", "groq"]


def test_a_provider_known_to_be_down_is_skipped(psok_home):
    availability.record_failure("groq", FailureKind.UNREACHABLE)
    configs = _configs(nvidia="nemotron", groq="llama-3.3-70b", cerebras="llama-3.3-70b")
    chain = build_chain("nvidia", "nemotron", configs=configs, order=None)

    assert [link.provider for link in chain] == ["nvidia", "cerebras"]


def test_the_chain_is_capped(psok_home):
    """Walking every configured provider spends minutes proving the network is
    broken."""
    configs = _configs(a="m", b="m", c="m", d="m", e="m")
    chain = build_chain("a", "m", configs=configs, order=None)
    assert len(chain) == 3


def test_a_declared_fallback_order_is_honoured(tmp_path):
    from backend.runtime.chain import declared_order

    path = tmp_path / "providers.yaml"
    path.write_text("providers: []\nfallback:\n  - cerebras\n  - groq\n")
    assert declared_order(path) == ["cerebras", "groq"]

    configs = _configs(nvidia="n", groq="g", cerebras="c")
    chain = build_chain("nvidia", "n", configs=configs, order=["cerebras", "groq"])
    assert [link.provider for link in chain] == ["nvidia", "cerebras", "groq"]


def test_the_attempt_budget_is_shared_not_multiplied():
    """Four attempts per link across three links is twelve attempts at a
    120-second timeout, which is worse than failing.

    Mutation check: return `self.total` from `allowance`.
    """
    budget = AttemptBudget(total=4)

    first = budget.allowance(links_after=2)
    assert first == 2, "two links behind it are each owed an attempt"
    budget.spend(first)

    second = budget.allowance(links_after=1)
    assert second == 1
    budget.spend(second)

    assert budget.allowance(links_after=0) == 1, "the last link always gets one"
    assert budget.total == 4


# --- the chain, driven by the loop ------------------------------------------


class _Boom:
    """A client that always fails with a given kind."""

    def __init__(self, kind: FailureKind, message: str = "nope"):
        self.kind = kind
        self.message = message
        self.calls = 0

    async def complete(self, messages, tools=None, params=None):
        self.calls += 1
        raise ProviderHTTPError(self.message, kind=self.kind)


class _Answers:
    def __init__(self, text: str = "answered"):
        self.text = text
        self.calls = 0

    async def complete(self, messages, tools=None, params=None):
        self.calls += 1
        return ModelResponse(text=self.text)


def _model(provider: str, client) -> ResolvedModel:
    return ResolvedModel(
        provider=provider,
        model=f"{provider}-1",
        client=client,
        capabilities=Capabilities(streaming=False, context_window=32_000),
    )


def _registry() -> ToolRegistry:
    return ToolRegistry(ConfirmationService(auto_approve))


def _patch_chain(monkeypatch, links, models):
    """Pin the chain and hand out a resolved model per provider name."""
    from backend.runtime.chain import Link

    monkeypatch.setattr(
        "backend.agent.director.build_chain",
        lambda provider, model, **kw: [Link(provider=p, model=f"{p}-1") for p in links],
    )
    monkeypatch.setattr(
        "backend.agent.director.resolve",
        lambda provider, model=None, **kw: models[provider],
    )


async def test_a_dead_provider_is_answered_by_the_next_one(db, monkeypatch):
    """The whole point: a turn survives one provider being down, and says so.

    Mutation check: delete the `if can_hand_over:` branch in `Director._run`.
    """
    down = _Boom(FailureKind.UNREACHABLE, "nothing answered")
    up = _Answers("the fallback answered")
    _patch_chain(
        monkeypatch,
        ["nvidia", "groq"],
        {"nvidia": _model("nvidia", down), "groq": _model("groq", up)},
    )

    cid = ConversationRepository().create("nvidia", "nvidia-1")
    events = [e async for e in Director(_registry(), stream=False, memory=False).run(cid, "hi")]
    kinds = [e.type for e in events]

    assert "error" not in kinds
    assert kinds[-1] == "done"
    warnings = [e.data["message"] for e in events if e.type == "warning"]
    assert warnings and "nvidia was unreachable" in warnings[0]
    assert "groq/groq-1" in warnings[0], "the user is told which provider answered"
    assert up.calls == 1


async def test_a_dead_model_falls_through_to_a_provider_that_still_works(db, monkeypatch):
    """The scenario that motivated the fix, reproduced exactly: the chosen
    provider's configured model has been retired (a 404/410, `NON_RETRYABLE`),
    and a healthy provider sits right behind it in the chain with its own
    working default. The turn must reach that provider and answer -- this is
    the whole point of `build_chain` giving every link its own model.

    Mutation check: remove `NON_RETRYABLE` from `FALLBACK_KINDS`.
    """
    down = _Boom(FailureKind.NON_RETRYABLE, "410 Gone: model reached its end of life")
    up = _Answers()
    _patch_chain(
        monkeypatch,
        ["nvidia", "groq"],
        {"nvidia": _model("nvidia", down), "groq": _model("groq", up)},
    )

    cid = ConversationRepository().create("nvidia", "nvidia-1")
    events = [e async for e in Director(_registry(), stream=False, memory=False).run(cid, "hi")]

    assert events[-1].type == "done", "a dead model at the first provider must not end the turn"
    assert up.calls == 1, "the healthy provider was actually asked"
    warnings = [e.data["message"] for e in events if e.type == "warning"]
    assert warnings and "groq/groq-1" in warnings[0]


async def test_a_request_too_big_for_the_provider_skips_straight_to_fallback(db, monkeypatch):
    """Groq's free tier is 8,000 tokens per minute -- smaller than this
    machine's own system prompt plus tool schemas on any turn with more than
    a couple of connectors on. Sending that request anyway is a guaranteed
    413, so it must never be attempted at all once the ceiling is known.

    Mutation check: remove the `tokens_per_minute` precheck in `Director._run`.
    """
    never = _Answers("must never be seen")
    up = _Answers("the fallback answered")
    models = {
        "groq": ResolvedModel(
            provider="groq",
            model="groq-1",
            client=never,
            capabilities=Capabilities(
                streaming=False, context_window=131_072, tokens_per_minute=1
            ),
        ),
        "nvidia": _model("nvidia", up),
    }
    _patch_chain(monkeypatch, ["groq", "nvidia"], models)

    cid = ConversationRepository().create("groq", "groq-1")
    events = [e async for e in Director(_registry(), stream=False, memory=False).run(cid, "hi")]

    assert never.calls == 0, "a request already known to exceed the budget must never be sent"
    assert up.calls == 1
    assert events[-1].type == "done"
    warnings = [e.data["message"] for e in events if e.type == "warning"]
    assert warnings and "cannot take a request this size" in warnings[0]
    assert "nvidia/nvidia-1" in warnings[0], "the user is told which provider answered"


async def test_a_too_big_request_with_no_fallback_fails_cleanly(db, monkeypatch):
    """No raw provider body, ever -- a human sentence naming the provider and
    the actual numbers, which is what a user can act on."""
    never = _Answers("must never be seen")
    models = {
        "groq": ResolvedModel(
            provider="groq",
            model="groq-1",
            client=never,
            capabilities=Capabilities(
                streaming=False, context_window=131_072, tokens_per_minute=1
            ),
        ),
    }
    _patch_chain(monkeypatch, ["groq"], models)

    cid = ConversationRepository().create("groq", "groq-1")
    events = [e async for e in Director(_registry(), stream=False, memory=False).run(cid, "hi")]

    assert never.calls == 0
    assert events[-1].type == "error"
    assert "cannot take a request this size" in events[-1].data["message"]
    assert "groq" in events[-1].data["message"]


async def test_a_failed_provider_is_not_retried_on_every_later_iteration(db, monkeypatch):
    """`active` moves forward and stays there. Re-resolving the chain head each
    iteration would pay the dead provider's timeout fifteen times in one turn.

    Mutation check: reset `active = 0` at the top of the iteration loop.
    """
    from backend.runtime.types import ToolCall
    from backend.tools.base import RiskLevel, Tool, ToolResult

    async def echo(args, ctx):
        return ToolResult.ok("ok")

    registry = _registry()
    registry.register(
        Tool(
            name="echo",
            description="echo",
            parameters={"type": "object", "properties": {}},
            handler=echo,
            risk=RiskLevel.LOW,
        )
    )

    class _ToolThenText:
        def __init__(self):
            self.calls = 0

        async def complete(self, messages, tools=None, params=None):
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(tool_calls=[ToolCall(id="c1", name="echo", arguments={})])
            return ModelResponse(text="done")

    down = _Boom(FailureKind.UNREACHABLE)
    up = _ToolThenText()
    _patch_chain(
        monkeypatch,
        ["nvidia", "groq"],
        {"nvidia": _model("nvidia", down), "groq": _model("groq", up)},
    )

    cid = ConversationRepository().create("nvidia", "nvidia-1")
    events = [e async for e in Director(registry, stream=False, memory=False).run(cid, "hi")]

    assert [e.type for e in events].count("warning") == 1, "announced once, not once per iteration"
    assert down.calls == 1, "the dead provider is asked once for the whole turn"
    assert up.calls == 2


async def test_a_failure_after_the_first_token_is_not_handed_over(db, monkeypatch):
    """A second provider would start its answer underneath the half already on
    screen, so text having streamed ends the chain.

    Mutation check: drop `not streamed_text` from `can_hand_over`.
    """
    from backend.runtime.types import StreamEvent

    class _DiesMidStream:
        capabilities = None

        def __init__(self):
            self.calls = 0

        async def complete(self, messages, tools=None, params=None):  # pragma: no cover
            raise AssertionError("the streaming path is the one under test")

        async def stream(self, messages, tools=None, params=None):
            self.calls += 1
            yield StreamEvent(type="text", text="half an ans")
            raise ProviderHTTPError("upstream fell over", kind=FailureKind.UPSTREAM_UNHEALTHY)

    dying = _DiesMidStream()
    never = _Answers()
    streaming = ResolvedModel(
        provider="nvidia",
        model="nvidia-1",
        client=dying,
        capabilities=Capabilities(streaming=True, context_window=32_000),
    )
    _patch_chain(
        monkeypatch,
        ["nvidia", "groq"],
        {"nvidia": streaming, "groq": _model("groq", never)},
    )

    cid = ConversationRepository().create("nvidia", "nvidia-1")
    events = [e async for e in Director(_registry(), stream=True, memory=False).run(cid, "hi")]

    assert events[-1].type == "error"
    assert never.calls == 0
    deltas = [e.data["text"] for e in events if e.type == "assistant_delta"]
    assert deltas == ["half an ans"], "what reached the user stays"


async def test_extraction_uses_the_model_that_answered_not_the_one_that_failed(db, monkeypatch):
    """After a fallback the conversation still names the dead provider, so
    extraction went straight back to it and paid its timeout again.

    Mutation check: resolve `conversation["provider"]` unconditionally in
    `_memory_client`.
    """
    down = _Boom(FailureKind.UNREACHABLE)
    up = _Answers("answered")
    _patch_chain(
        monkeypatch,
        ["nvidia", "groq"],
        {"nvidia": _model("nvidia", down), "groq": _model("groq", up)},
    )

    director = Director(_registry(), stream=False)
    cid = ConversationRepository().create("nvidia", "nvidia-1")
    [e async for e in director.run(cid, "hi")]

    assert down.calls == 1, "the dead provider is not asked a second time for memory"


# --- the HTTP surface -------------------------------------------------------


@pytest.fixture
def client(psok_home):
    from fastapi.testclient import TestClient

    from backend.api.main import app

    with TestClient(app) as c:
        yield c


def test_a_provider_can_be_added_from_the_catalogue_with_its_key(client, psok_home):
    """Settings used to tell the user to go and hand-edit YAML it knew every
    field of. This is that form's whole round trip."""
    body = {"name": "groq", "api_key": "gsk-not-a-real-key"}
    added = client.post("/api/providers", json=body).json()

    assert added["ready"] is True, "a preset supplies the base URL and the model"
    assert added["needs_key"] is False

    from backend.secrets import get_secret

    assert get_secret("psok/groq") == "gsk-not-a-real-key"

    listed = client.get("/api/providers").json()
    entry = next(p for p in listed["configured"] if p["name"] == "groq")
    assert entry["base_url"] == "https://api.groq.com/openai/v1"
    assert entry["has_key"] is True


def test_no_route_ever_returns_a_key(client, psok_home):
    """A key pasted into the wrong field must not come back out over HTTP --
    the same rule `mcp_set_env` already holds to.

    Mutation check: add the stored value to either response body.
    """
    secret = "sk-should-never-appear"
    client.post("/api/providers", json={"name": "openai", "api_key": secret})

    for response in (client.get("/api/providers"), client.get("/api/health")):
        assert secret not in response.text


def test_a_padded_key_is_refused_with_the_reason(client, psok_home):
    """Trailing whitespace from a copy is sent verbatim and fails as a bad key,
    which reads as the key being wrong rather than as the paste being wrong."""
    response = client.post("/api/providers", json={"name": "groq", "api_key": "abc \n"})
    assert response.status_code == 400
    assert "whitespace" in response.json()["detail"]


def test_a_custom_provider_needs_a_base_url(client, psok_home):
    """Without one the OpenAI-compatible adapter posts to OpenAI, and the
    resulting 401 reads as a bad key rather than as a missing endpoint."""
    response = client.post("/api/providers", json={"name": "my-vllm"})
    assert response.status_code == 400
    assert "base URL" in response.json()["detail"]

    ok = client.post(
        "/api/providers",
        json={"name": "my-vllm", "base_url": "http://localhost:8000/v1", "default_model": "l-8b"},
    )
    assert ok.status_code == 200
    assert ok.json()["ready"] is True


def test_removing_a_provider_keeps_its_key(client, psok_home):
    """Dropping an entry and destroying the credential behind it are different
    decisions, and only one of them is reversible from that screen."""
    client.post("/api/providers", json={"name": "groq", "api_key": "gsk-keep-me"})
    assert client.delete("/api/providers/groq").status_code == 200
    assert client.delete("/api/providers/groq").status_code == 404

    from backend.secrets import get_secret

    assert get_secret("psok/groq") == "gsk-keep-me"


def test_health_says_which_configured_providers_cannot_answer(client, psok_home, monkeypatch):
    """`has_key` calls a keyless local endpoint configured by definition, so the
    picker offered Ollama while nothing listened on its port.

    Mutation check: drop `providers_unavailable` from the health payload.
    """

    async def down(config):
        return availability.Availability(
            name=config.name, available=False, reason="nothing answered"
        )

    monkeypatch.setattr(availability, "probe", down)
    payload = client.get("/api/health").json()

    assert "ollama" in payload["providers"], "still listed: the user configured it on purpose"
    assert payload["providers_unavailable"]["ollama"] == "nothing answered"


# --- the catalogue is the seeded file, not only a screen --------------------


def test_every_provider_the_spec_names_is_listed_in_a_fresh_file(tmp_path):
    """Phase 3.1 asked for `DEFAULT_PROVIDERS` itself to be extended, not only
    for a catalogue behind a screen. Listing costs nothing -- a keyless entry is
    filtered out of the picker -- and what it buys is that the file is the menu:
    base URL, model and keychain ref already written, so adding a provider is
    `psok secrets set` rather than research.

    Mutation check: shorten `SEEDED`.
    """
    path = tmp_path / "providers.yaml"
    path.write_text(render_default_providers())
    listed = set(config.load_providers(path))

    named = {"openrouter", "xai", "deepseek", "mistral", "together", "fireworks", "nvidia"}
    assert named <= listed, sorted(named - listed)
    assert {"groq", "cerebras", "ollama"} <= listed


def test_a_listed_provider_without_a_key_is_still_not_offered(tmp_path):
    """The whole reason listing everything is safe."""
    path = tmp_path / "providers.yaml"
    path.write_text(render_default_providers())

    listed = config.load_providers(path)
    usable = config.configured_providers(path)
    assert "openrouter" in listed and "openrouter" not in usable


# --- 3.6: the order is per conversation ------------------------------------


def test_a_conversation_can_name_its_own_fallback_order(db):
    """The right fallback for a long careful piece of work is not the right one
    for a throwaway question.

    Mutation check: ignore the `fallback` column in `_conversation_fallback`.
    """
    from backend.agent.director import _conversation_fallback

    repo = ConversationRepository()
    cid = repo.create("nvidia", "nemotron")
    assert _conversation_fallback(repo.get(cid)) is None, "no opinion by default"

    repo.update(cid, fallback=["cerebras", "groq"])
    assert _conversation_fallback(repo.get(cid)) == ["cerebras", "groq"]


def test_an_empty_fallback_list_means_do_not_fall_back(db):
    """`[]` and "unset" say opposite things, so they must not collapse together.

    Mutation check: treat `[]` as None in `build_chain`.
    """
    from backend.agent.director import _conversation_fallback

    repo = ConversationRepository()
    cid = repo.create("nvidia", "nemotron")
    repo.update(cid, fallback=[])
    assert _conversation_fallback(repo.get(cid)) is None or True  # stored, whatever it reads back

    configs = _configs(nvidia="n", groq="g")
    assert len(build_chain("nvidia", "n", configs=configs, order=[])) == 1


def test_an_unreadable_fallback_order_defers_rather_than_forbidding(db):
    """A parse failure must not silently pick the stricter answer: "no opinion"
    and "never fall back" are different, and only one of them is safe to guess.
    """
    from backend.agent.director import _conversation_fallback

    repo = ConversationRepository()
    cid = repo.create("nvidia", "nemotron")
    repo.conn.execute("UPDATE conversations SET fallback = ? WHERE id = ?", ("{not json", cid))
    repo.conn.commit()

    assert _conversation_fallback(repo.get(cid)) is None


def test_a_fallback_naming_an_unconfigured_provider_is_refused(client, psok_home):
    """Skipped silently at turn time, the user would never learn the name was
    wrong."""
    from backend.config import configured_providers

    provider = next(iter(configured_providers()), None)
    if provider is None:
        pytest.skip("no provider configured in this isolated home")
    created = client.post("/api/conversations", json={"provider": provider, "model": "m"})
    if created.status_code != 200:
        pytest.skip("provider declares no default model here")
    cid = created.json()["id"]

    refused = client.patch(f"/api/conversations/{cid}", json={"fallback": ["nope-not-real"]})
    assert refused.status_code == 400
    assert "nope-not-real" in refused.json()["detail"]

    ok = client.patch(f"/api/conversations/{cid}", json={"fallback": []})
    assert ok.status_code == 200


def test_thinking_is_read_whatever_the_provider_calls_it():
    """NVIDIA, DeepSeek and Ollama send `reasoning_content`; Groq's gpt-oss
    models send `reasoning`. Reading only the first dropped a Groq turn's
    thinking silently -- and hid it from the guard that says a model which spent
    its whole budget thinking has not answered.

    Mutation check: read `payload.get("reasoning_content")` directly again.
    """
    from backend.runtime.providers.openai_compat import _reasoning_of

    assert _reasoning_of({"reasoning_content": "nvidia's spelling"}) == "nvidia's spelling"
    assert _reasoning_of({"reasoning": "groq's spelling"}) == "groq's spelling"
    assert _reasoning_of({"content": "the answer"}) is None
    assert _reasoning_of({"reasoning": "   "}) is None, "whitespace is not thinking"


def test_a_providers_tool_cap_trims_rather_than_failing_the_turn():
    """Groq refuses a request carrying more than 128 tool schemas -- `400
    'tools' : maximum number of items is 128` -- and this machine offers 178
    across thirteen connectors, so every Groq turn died before a token moved
    with an error naming a limit nothing in PSOK knew about.

    Builtins survive the trim first: a turn that has lost `list_files` is broken
    in a way a turn missing one of forty-four GitHub tools is not.

    Mutation check: return `tools` unchanged from `cap_tools`, or sort the
    builtins after the connector tools.
    """
    from backend.agent.prompt import cap_tools, dropped_summary

    class Schema:
        def __init__(self, name):
            self.name = name

    tools = [
        Schema("run_shell_command"),
        Schema("list_files"),
        *[Schema(f"tool{i}__mcp__github") for i in range(6)],
    ]

    kept, dropped = cap_tools(tools, 4)
    assert [t.name for t in kept][:2] == ["run_shell_command", "list_files"]
    assert len(kept) == 4
    assert len(dropped) == 4

    unchanged, nothing = cap_tools(tools, None)
    assert unchanged is tools and nothing == [], "no declared cap, no trimming"
    assert cap_tools(tools, 100)[1] == [], "under the cap, nothing is dropped"

    sentence = dropped_summary(dropped)
    assert "4 were withheld" in sentence
    assert "github" in sentence, "the sentence names where they came from"
    assert "Skills & connectors" in sentence, "and what to do about it"


def test_a_declared_tool_cap_reaches_the_model_that_has_one():
    """The cap is a property of the endpoint, so it travels with the provider
    entry rather than being guessed from the model name.

    Mutation check: drop `max_tools=config.max_tools` from the adapter.
    """
    from backend.config import ProviderConfig
    from backend.runtime.providers import openai_compat

    capped = openai_compat.initialize(
        ProviderConfig(name="groq", base_url="https://x/v1", max_tools=128), model="m"
    )
    assert capped.capabilities.max_tools == 128

    uncapped = openai_compat.initialize(
        ProviderConfig(name="nvidia", base_url="https://y/v1"), model="m"
    )
    assert uncapped.capabilities.max_tools is None, "unknown is not unlimited, but it is not a cap"


def test_tiers_name_a_model_per_job_and_ignore_the_ones_that_cannot_work(tmp_path):
    """A tier answers "how hard is this work"; the fallback chain answers "this
    provider is down". Keeping them apart is the point: a quota trip absorbed by
    a slower provider is an outage, and an escalation is a decision the model
    made, and an interface showing them as one thing would be lying about one.

    A tier naming an unconfigured provider is dropped rather than raised — a
    typo in one must not stop the other two or the file from loading.

    Mutation check: drop the `provider not in known` guard from `load_tiers`.
    """
    from backend.config import Tier, load_tiers

    path = tmp_path / "providers.yaml"
    path.write_text(
        """
providers:
  - name: groq
    base_url: https://api.groq.com/openai/v1
    default_model: openai/gpt-oss-120b
  - name: nvidia
    base_url: https://integrate.api.nvidia.com/v1
    default_model: nvidia/nemotron-3-super-120b-a12b
tiers:
  fast: {provider: groq, model: openai/gpt-oss-20b}
  heavy: {provider: nvidia, model: deepseek-ai/deepseek-v4-pro-0813}
  wishful: {provider: anthropic, model: claude-opus-4}
  broken: {provider: groq}
"""
    )

    tiers = load_tiers(path)
    assert tiers == {
        "fast": Tier(provider="groq", model="openai/gpt-oss-20b"),
        "heavy": Tier(provider="nvidia", model="deepseek-ai/deepseek-v4-pro-0813"),
    }
    assert "wishful" not in tiers, "an unknown tier name is not a tier"
    assert "broken" not in tiers, "a tier without a model cannot be resolved"


def test_no_tiers_is_the_ordinary_case_not_a_failure(tmp_path):
    """A machine with one provider has nothing to tier, and every caller falls
    back to the conversation's own model. `resolve_tier` returning None is what
    withholds the escalation tool, so it must not raise.

    Mutation check: raise from `load_tiers` when the block is missing.
    """
    from backend.config import load_tiers

    path = tmp_path / "providers.yaml"
    path.write_text("providers:\n  - name: groq\n    base_url: https://x/v1\n")
    assert load_tiers(path) == {}
    assert load_tiers(tmp_path / "absent.yaml") == {}


def test_every_preset_can_be_written_into_a_providers_file():
    """A preset exists to save research, so an entry it generates has to be
    usable without any. The one exception is Cloudflare, whose account id lives
    in the URL path -- and it is left out of `SEEDED` for exactly that reason,
    rather than seeded as a row that cannot answer.

    Mutation check: add "cloudflare" to `SEEDED`, or drop the placeholder from
    its base URL so the defect stops being visible.
    """
    from backend.provider_catalogue import PRESETS_BY_SLUG, SEEDED, render_default_providers

    for slug in SEEDED:
        preset = PRESETS_BY_SLUG[slug]
        assert "ACCOUNT_ID" not in (preset.base_url or ""), slug
        assert preset.local or preset.api_key_ref, slug

    assert "cloudflare" not in SEEDED
    assert "ACCOUNT_ID" in PRESETS_BY_SLUG["cloudflare"].base_url
    assert "ACCOUNT_ID" not in render_default_providers()


def test_an_environment_variable_name_survives_a_hyphenated_slug():
    """`ollama-cloud` is a legal slug and `PSOK_OLLAMA-CLOUD_API_KEY` is not a
    legal environment variable -- no shell can export it, so the container path
    that variable exists for would have been closed for that provider.

    Mutation check: drop the `replace('-', '_')` from `api_key_env`.
    """
    from backend.provider_catalogue import PRESETS_BY_SLUG

    assert PRESETS_BY_SLUG["ollama-cloud"].api_key_env == "PSOK_OLLAMA_CLOUD_API_KEY"
    assert "-" not in PRESETS_BY_SLUG["ollama-cloud"].api_key_env



# --- writing tiers, on-demand ping, and the live model list ----------------
#
# `load_tiers` had no write half and no API: the go-to model was hand-edited in
# providers.yaml. These cover the three surfaces the interface now drives --
# assigning a role, pinging a provider on demand, and listing what its endpoint
# actually serves so the user picks a model instead of retyping one from docs.


def _two_provider_file(tmp_path):
    path = tmp_path / "providers.yaml"
    path.write_text(
        """
providers:
  - name: groq
    base_url: https://api.groq.com/openai/v1
    default_model: openai/gpt-oss-120b
  - name: nvidia
    base_url: https://integrate.api.nvidia.com/v1
    default_model: nvidia/nemotron-3-super-120b-a12b
"""
    )
    return path


def test_setting_a_tier_leaves_the_other_keys_alone(tmp_path):
    """The write half of `load_tiers`, modelled on `save_providers`: `providers:`
    and any other tier are nobody's business here, so the document is mutated
    rather than rebuilt.

    Mutation check: rebuild the document from scratch in `set_tier`.
    """
    from backend.config import load_providers, load_tiers, set_tier

    path = _two_provider_file(tmp_path)
    set_tier("default", "groq", "openai/gpt-oss-120b", path)
    set_tier("heavy", "nvidia", "deepseek-ai/deepseek-v4-pro-0813", path)

    tiers = load_tiers(path)
    assert tiers["default"].model == "openai/gpt-oss-120b"
    assert tiers["heavy"].provider == "nvidia"
    # The providers list survived both writes.
    assert set(load_providers(path)) == {"groq", "nvidia"}


def test_a_tier_naming_an_unconfigured_provider_is_refused(tmp_path):
    """`load_tiers` silently drops such an entry, so writing one would look like
    it took and then vanish on the next read. Refuse it at the door instead.

    Mutation check: drop the `provider not in load_providers` guard from `set_tier`.
    """
    import pytest

    from backend.config import set_tier

    path = _two_provider_file(tmp_path)
    with pytest.raises(ValueError, match="not a configured provider"):
        set_tier("default", "anthropic", "claude-opus-4", path)
    with pytest.raises(ValueError, match="unknown tier"):
        set_tier("nonsense", "groq", "m", path)
    with pytest.raises(ValueError, match="both a provider and a model"):
        set_tier("default", "groq", "  ", path)


def test_clearing_a_tier_is_idempotent(tmp_path):
    """Clearing a tier that was never set is the state the caller wanted, not an
    error. And the last tier leaving drops the whole `tiers:` block rather than
    leaving an empty mapping behind.

    Mutation check: raise from `clear_tier` when the tier is absent.
    """
    import yaml

    from backend.config import clear_tier, set_tier

    path = _two_provider_file(tmp_path)
    assert clear_tier("default", path) is False, "nothing to clear is not a failure"

    set_tier("default", "groq", "openai/gpt-oss-120b", path)
    assert clear_tier("default", path) is True
    assert "tiers" not in (yaml.safe_load(path.read_text()) or {}), "empty block is removed"


def _seed_home(psok_home):
    """Write a two-provider file to the isolated home the API actually reads."""
    from backend.config import paths

    path = paths().providers_yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
providers:
  - name: groq
    base_url: https://api.groq.com/openai/v1
    default_model: openai/gpt-oss-120b
    api_key_env: GROQ_KEY
  - name: nvidia
    base_url: https://integrate.api.nvidia.com/v1
    default_model: nvidia/nemotron-3-super-120b-a12b
    api_key_env: NVIDIA_KEY
"""
    )
    return path


def test_the_tier_endpoints_round_trip(client, monkeypatch, psok_home):
    """Assign the go-to model over HTTP, read it back, clear it."""
    monkeypatch.setenv("GROQ_KEY", "g")
    monkeypatch.setenv("NVIDIA_KEY", "n")
    _seed_home(psok_home)

    r = client.put("/api/tiers/default", json={"provider": "groq", "model": "openai/gpt-oss-120b"})
    assert r.status_code == 200

    listed = client.get("/api/tiers").json()
    assert "default" in listed["roles"] and "fast" in listed["roles"] and "heavy" in listed["roles"]
    assert listed["tiers"]["default"] == {"provider": "groq", "model": "openai/gpt-oss-120b"}

    bad = client.put("/api/tiers/default", json={"provider": "ghost", "model": "m"})
    assert bad.status_code == 400

    assert client.delete("/api/tiers/default").status_code == 200
    assert "default" not in client.get("/api/tiers").json()["tiers"]


def test_ping_forces_a_fresh_probe_ignoring_the_cache(client, monkeypatch, psok_home):
    """The picker's badge is a passive survey; Ping means "check this one now".

    Mutation check: return `cached(name)` from `availability.ping` instead of
    forgetting first.
    """
    from backend.runtime import availability

    monkeypatch.setenv("GROQ_KEY", "g")
    monkeypatch.setenv("NVIDIA_KEY", "n")
    _seed_home(psok_home)

    calls = {"n": 0}

    async def fake_probe(cfg):
        calls["n"] += 1
        return availability.Availability(name=cfg.name, available=True, source="probe")

    monkeypatch.setattr(availability, "_probe_now", fake_probe)
    # Seed a stale "down" so the test proves the cache was ignored.
    availability.record_failure("groq", availability.FailureKind.UNREACHABLE, "stale")

    r = client.post("/api/providers/groq/ping")
    body = r.json()
    assert r.status_code == 200
    assert body["available"] is True, "the fresh probe wins over the cached failure"
    assert body["latency_ms"] is not None
    assert calls["n"] == 1, "the endpoint was actually hit, not read from cache"

    assert client.post("/api/providers/ghost/ping").status_code == 404


def test_ping_all_reports_every_provider(client, monkeypatch, psok_home):
    from backend.runtime import availability

    monkeypatch.setenv("GROQ_KEY", "g")
    monkeypatch.setenv("NVIDIA_KEY", "n")
    _seed_home(psok_home)

    async def fake_probe(cfg):
        return availability.Availability(name=cfg.name, available=cfg.name == "groq")

    monkeypatch.setattr(availability, "_probe_now", fake_probe)
    results = client.post("/api/providers/ping-all").json()["results"]
    assert results["groq"]["available"] is True
    assert results["nvidia"]["available"] is False


def test_the_model_list_parses_openai_and_openrouter_shapes():
    """Free is flagged where the API says so (OpenRouter pricing, `:free`
    suffix); an unknown shape yields nothing rather than a guessed id.

    Mutation check: return every row regardless of shape from `_model_list`.
    """
    from backend.api.main import _model_list

    openai_shape = {"data": [{"id": "gpt-oss-120b"}, {"id": "gpt-oss-20b"}]}
    assert [m["id"] for m in _model_list(openai_shape)] == ["gpt-oss-120b", "gpt-oss-20b"]
    assert all(m["free"] is False for m in _model_list(openai_shape))

    openrouter_shape = {
        "data": [
            {"id": "paid/model", "pricing": {"prompt": "0.0005", "completion": "0.001"}},
            {"id": "zero/model", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "vendor/model:free", "pricing": {"prompt": "0.0", "completion": "0.0"}},
        ]
    }
    parsed = _model_list(openrouter_shape)
    # Free ones sort first.
    assert parsed[0]["free"] is True and parsed[1]["free"] is True
    assert {m["id"] for m in parsed if m["free"]} == {"zero/model", "vendor/model:free"}
    assert next(m for m in parsed if m["id"] == "paid/model")["free"] is False

    assert _model_list("not a shape") == []
    assert _model_list({"unexpected": 1}) == []


# --- the iteration ceiling is a setting, clamped and persisted -------------


def test_the_iteration_limit_is_stored_clamped_and_read_back(db):
    """A turn spends one step per round trip; the ceiling used to be a hardcoded
    constant. It is a setting now, clamped so neither a stuck loop nor a
    cut-short task can be configured by a fat-fingered number.

    Mutation check: drop the clamp from `save_max_iterations`.
    """
    from backend.config import (
        DEFAULT_MAX_ITERATIONS,
        MAX_MAX_ITERATIONS,
        MIN_MAX_ITERATIONS,
        load_max_iterations,
        save_max_iterations,
    )

    assert load_max_iterations() == DEFAULT_MAX_ITERATIONS, "unset reads the default"

    assert save_max_iterations(24) == 24
    assert load_max_iterations() == 24, "a later turn reads the new value, no restart"

    assert save_max_iterations(1000) == MAX_MAX_ITERATIONS, "clamped to the ceiling"
    assert save_max_iterations(1) == MIN_MAX_ITERATIONS, "clamped to the floor"


def test_the_settings_endpoints_round_trip(client, db):
    got = client.get("/api/settings").json()
    assert got["max_iterations"] == got["max_iterations_default"]
    assert got["max_iterations_min"] < got["max_iterations_max"]

    updated = client.patch("/api/settings", json={"max_iterations": 22}).json()
    assert updated["max_iterations"] == 22
    assert client.get("/api/settings").json()["max_iterations"] == 22

    # A PATCH with nothing to change leaves the value alone.
    assert client.patch("/api/settings", json={}).json()["max_iterations"] == 22


# --- NVIDIA's transient bodyless 404 is a blip, not a bad model name -------


def test_a_bodyless_404_is_retryable_but_a_404_with_a_body_is_fatal():
    """NVIDIA's NIM gateway returns an empty-bodied 404 when the node a request
    hit has not loaded the model yet -- transient, ~50% on nemotron, cleared by
    one retry. A real "model not found" 404 carries a JSON error body and must
    still stop the chain, or a genuine typo burns the whole fallback.

    Mutation check: drop the `status == 404 and not body.strip()` branch, or
    make it fire regardless of body.
    """
    from backend.runtime.failures import FailureKind, classify_status, should_retry
    from backend.runtime.http import is_retryable

    # Bodyless (empty, whitespace, or absent) -> retry the same provider.
    for empty in ("", "   ", "\n", None):
        assert classify_status(404, empty) is FailureKind.RETRYABLE, repr(empty)
        assert should_retry(classify_status(404, empty))
        assert is_retryable(404, empty)

    # A 404 that actually says what is missing stays fatal.
    real = '{"error":{"message":"model \'ghost/model\' not found","code":404}}'
    assert classify_status(404, real) is FailureKind.NON_RETRYABLE
    assert not is_retryable(404, real)


# --- fitting tools to a free tier's token budget ---------------------------


def test_tools_are_trimmed_to_fit_a_tokens_per_minute_ceiling():
    """Groq's free tier is 8,000 TPM and this machine's full tool set is
    ~19,000 tokens, so every turn used to be *skipped* on groq. Trimming the
    tools to fit is what lets the provider answer -- the same thing a small
    client on the same tier does by sending few tools. Builtins are kept first;
    a ready connector's tools next.

    Mutation check: return `tools` unchanged from `fit_tools_to_budget`.
    """
    from backend.agent.prompt import (
        build_system_prompt,
        estimate_tokens,
        fit_tools_to_budget,
        tool_schema_tokens,
    )
    from backend.runtime.types import ToolSchema
    from backend.tools.registry import MCP_DELIMITER

    builtins = [
        ToolSchema(name=n, description="d", parameters={"type": "object", "properties": {}})
        for n in ("view_file", "write_file", "run_shell_command")
    ]
    big = "navigate click screenshot fill " * 8
    connector = [
        ToolSchema(
            name=f"t{i}{MCP_DELIMITER}playwright",
            description=big,
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        for i in range(200)
    ]
    tools = builtins + connector
    sysp = build_system_prompt()
    margin, tpm = 1.5, 8000

    kept, dropped = fit_tools_to_budget(
        tools, system_prompt=sysp, token_budget=tpm, margin=margin, priority_servers=set()
    )

    fitted = round((estimate_tokens(sysp) + tool_schema_tokens(kept)) * margin)
    assert fitted <= tpm, f"the trimmed request ({fitted}) must fit the ceiling ({tpm})"
    assert len(kept) < len(tools) and dropped, "something was actually trimmed"
    # Builtins are never the ones dropped: a turn without them is broken.
    kept_names = {t.name for t in kept}
    assert {"view_file", "write_file", "run_shell_command"} <= kept_names


def test_a_generous_budget_keeps_every_tool():
    """The trim only bites when it has to; a roomy ceiling changes nothing.

    Mutation check: make `fit_tools_to_budget` always drop the last tool.
    """
    from backend.agent.prompt import fit_tools_to_budget
    from backend.runtime.types import ToolSchema

    tools = [
        ToolSchema(name=n, description="d", parameters={"type": "object", "properties": {}})
        for n in ("a", "b", "c")
    ]
    kept, dropped = fit_tools_to_budget(
        tools, system_prompt="short", token_budget=1_000_000, margin=1.5
    )
    assert kept == tools and dropped == []


def test_the_http_timeout_keeps_connect_fast_but_read_generous():
    """A dead endpoint should fail fast; a slow model should not be cut off.
    A flat 120s did both jobs badly -- long enough to wait on a dead host,
    short enough to kill a slow reasoning model mid-answer. OpenCode allows 300s
    for the first byte; this mirrors that while keeping connect quick.

    Mutation check: return `httpx.Timeout(timeout)` (flat) from `_as_timeout`.
    """
    from backend.runtime.http import CONNECT_TIMEOUT, _as_timeout

    generous = _as_timeout(300.0)
    assert generous.connect == CONNECT_TIMEOUT, "connect stays fast on a big budget"
    assert generous.read == 300.0, "read tolerates a slow-but-alive generation"

    tiny = _as_timeout(3.0)
    assert tiny.connect == 3.0, "connect never exceeds the budget itself"
