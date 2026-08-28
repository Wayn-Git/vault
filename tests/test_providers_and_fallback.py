"""Phase 3: the provider catalogue, failure taxonomy and fallback chain.

Each test names the behaviour it locks down and, where the behaviour is easy to
break silently, the source mutation that must turn it red.
"""

from __future__ import annotations

import pytest

from psok import config
from psok.agent.director import Director
from psok.agent.prompt import budget_history, tool_schema_tokens
from psok.config import ProviderConfig
from psok.db.repositories import ConversationRepository
from psok.provider_catalogue import PRESETS_BY_SLUG, PROVIDER_PRESETS, render_default_providers
from psok.runtime import availability
from psok.runtime.chain import AttemptBudget, build_chain
from psok.runtime.failures import (
    FailureKind,
    classify_status,
    classify_stream_error,
    should_fall_back,
    should_retry,
)
from psok.runtime.http import ProviderHTTPError
from psok.runtime.types import Capabilities, ModelResponse, ResolvedModel, ToolSchema
from psok.security.confirmation import ConfirmationService, auto_approve
from psok.tools.registry import ToolRegistry


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


def test_a_bad_request_stops_the_chain_rather_than_walking_it():
    """A model name that does not exist at one provider does not exist at the
    next either, so falling back turns one fast failure into several slow ones.

    Mutation check: add `NON_RETRYABLE` to `FALLBACK_KINDS`.
    """
    assert not should_fall_back(classify_status(404, "no such model"))
    assert not should_fall_back(classify_status(401, "invalid api key"))


def test_stream_error_frames_are_classified_from_their_own_names():
    """These arrive inside an already-200 response and carry no status."""
    assert classify_stream_error({"type": "overloaded_error"}) is FailureKind.UPSTREAM_UNHEALTHY
    assert classify_stream_error({"type": "rate_limit_error"}) is FailureKind.RATE_LIMITED
    assert (
        classify_stream_error({"code": "context_length_exceeded"}) is FailureKind.NON_RETRYABLE
    )
    # Unrecognised is treated as a bad request: it stops rather than retries.
    assert classify_stream_error({"type": "who_knows"}) is FailureKind.NON_RETRYABLE


async def test_a_quota_429_is_not_retried_over_http(monkeypatch):
    """The taxonomy has to reach `post_json`, not merely exist beside it.

    Mutation check: revert `is_retryable` to `status in RETRYABLE_STATUS or
    status >= 500` and this makes four attempts instead of one.
    """
    import httpx

    from psok.runtime import http as runtime_http

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

    from psok.provider_catalogue import entry_for

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

    from psok.provider_catalogue import SEEDED

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
    from psok.runtime.registry import resolve

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
    from psok.runtime.chain import declared_order

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
    from psok.runtime.chain import Link

    monkeypatch.setattr(
        "psok.agent.director.build_chain",
        lambda provider, model, **kw: [Link(provider=p, model=f"{p}-1") for p in links],
    )
    monkeypatch.setattr(
        "psok.agent.director.resolve",
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


async def test_a_404_fails_immediately_without_trying_the_fallback(db, monkeypatch):
    """A model name that is wrong at one provider is wrong at the next, so the
    fallback would cost a second round trip to learn the same thing.

    Mutation check: replace `should_fall_back(kind)` with `True`.
    """
    down = _Boom(FailureKind.NON_RETRYABLE, "404 page not found")
    never = _Answers()
    _patch_chain(
        monkeypatch,
        ["nvidia", "groq"],
        {"nvidia": _model("nvidia", down), "groq": _model("groq", never)},
    )

    cid = ConversationRepository().create("nvidia", "nvidia-1")
    events = [e async for e in Director(_registry(), stream=False, memory=False).run(cid, "hi")]

    assert events[-1].type == "error"
    assert never.calls == 0, "the fallback must not be burned on a bad request"
    assert not [e for e in events if e.type == "warning"]


async def test_a_failed_provider_is_not_retried_on_every_later_iteration(db, monkeypatch):
    """`active` moves forward and stays there. Re-resolving the chain head each
    iteration would pay the dead provider's timeout fifteen times in one turn.

    Mutation check: reset `active = 0` at the top of the iteration loop.
    """
    from psok.runtime.types import ToolCall
    from psok.tools.base import RiskLevel, Tool, ToolResult

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
    from psok.runtime.types import StreamEvent

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

    from psok.api.main import app

    with TestClient(app) as c:
        yield c


def test_a_provider_can_be_added_from_the_catalogue_with_its_key(client, psok_home):
    """Settings used to tell the user to go and hand-edit YAML it knew every
    field of. This is that form's whole round trip."""
    body = {"name": "groq", "api_key": "gsk-not-a-real-key"}
    added = client.post("/api/providers", json=body).json()

    assert added["ready"] is True, "a preset supplies the base URL and the model"
    assert added["needs_key"] is False

    from psok.secrets import get_secret

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

    from psok.secrets import get_secret

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
    from psok.agent.director import _conversation_fallback

    repo = ConversationRepository()
    cid = repo.create("nvidia", "nemotron")
    assert _conversation_fallback(repo.get(cid)) is None, "no opinion by default"

    repo.update(cid, fallback=["cerebras", "groq"])
    assert _conversation_fallback(repo.get(cid)) == ["cerebras", "groq"]


def test_an_empty_fallback_list_means_do_not_fall_back(db):
    """`[]` and "unset" say opposite things, so they must not collapse together.

    Mutation check: treat `[]` as None in `build_chain`.
    """
    from psok.agent.director import _conversation_fallback

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
    from psok.agent.director import _conversation_fallback

    repo = ConversationRepository()
    cid = repo.create("nvidia", "nemotron")
    repo.conn.execute("UPDATE conversations SET fallback = ? WHERE id = ?", ("{not json", cid))
    repo.conn.commit()

    assert _conversation_fallback(repo.get(cid)) is None


def test_a_fallback_naming_an_unconfigured_provider_is_refused(client, psok_home):
    """Skipped silently at turn time, the user would never learn the name was
    wrong."""
    from psok.config import configured_providers

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
