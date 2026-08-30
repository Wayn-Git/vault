"""Known model providers, as data.

Adding a provider to PSOK needs no code (ADR-0001): any name not in
`PROVIDER_REGISTRY` resolves to the OpenAI-compatible adapter, so an entry in
providers.yaml with a base URL and a key is the whole integration. What was
missing was not capability but knowledge -- the base URL, the model id and the
page where a key is issued -- which left `Settings.jsx` telling the user to go
and hand-edit YAML it could not help them write.

So this is a catalogue, not an abstraction layer. Each preset is the four facts
a person needs to fill that form: where the endpoint is, what to call the model,
where to get a key, and what the docs are.

Two deliberate omissions:

* **No auth-style field.** A generic client with per-provider flags is the right
  shape when every provider goes through one client. PSOK already has native
  adapters for the two that do not speak Bearer-and-chat-completions (Anthropic,
  Google), so a flag nothing reads would be a reserved slot for code that does
  not exist. `adapter` names the existing mechanism instead.
* **`context_window` only where it is known.** A declared window overrides the
  adapter's substring guess, so a wrong one is worse than none: it fails
  loudly mid-generation rather than merely wasting room. Presets whose window
  varies per model leave it unset and let the guess stand until someone
  declares the real figure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    """Everything needed to write one providers.yaml entry."""

    slug: str
    label: str
    base_url: str | None = None
    default_model: str | None = None
    context_window: int | None = None
    #: The endpoint's cap on how many tool schemas one request may carry, where
    #: it has one. Groq answers `400 'tools' : maximum number of items is 128`;
    #: everyone else observed so far takes what they are given.
    max_tools: int | None = None
    #: Native adapter name for providers that do not speak chat-completions.
    #: None means the OpenAI-compatible fall-through, which is most of them.
    adapter: str | None = None
    #: Where a key is issued. None means the endpoint needs no key.
    keys_url: str | None = None
    docs_url: str | None = None
    #: A local endpoint: no key, and reachability is the only thing that
    #: determines whether it can answer.
    local: bool = False
    note: str = ""

    @property
    def api_key_ref(self) -> str | None:
        return None if self.local else f"psok/{self.slug}"

    @property
    def api_key_env(self) -> str | None:
        """The environment variable this provider's key may also arrive in.

        The keychain stays first -- `has_key` and `resolve_api_key` both check
        the reference before the variable -- and this is the way in for a host
        that has no keychain to check. A container is the whole reason it
        exists: without it, a deployed PSOK could be given a key only by
        hand-editing providers.yaml on a disk nobody has a shell on.

        The name is the vendor's own where the vendor has one, because that is
        the variable the key is already sitting in on the machine of anyone who
        has used the provider before. `PSOK_*` for the rest, which is a name
        nothing else will collide with.
        """
        if self.local:
            return None
        # A hyphen is fine in a slug and not in an environment variable name --
        # `ollama-cloud` would otherwise generate `PSOK_OLLAMA-CLOUD_API_KEY`,
        # which no shell can export.
        fallback = f"PSOK_{self.slug.upper().replace('-', '_')}_API_KEY"
        return _CONVENTIONAL_ENV.get(self.slug, fallback)


#: Names the vendors themselves document, so a key already exported for their
#: own SDK is found without being copied under a second name.
_CONVENTIONAL_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "xai": "XAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
}


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        slug="ollama",
        label="Ollama",
        base_url="http://localhost:11434/v1",
        default_model="qwen2.5:7b",
        adapter="ollama",
        docs_url="https://ollama.com/library",
        local=True,
        note=(
            "Runs on this machine. Nothing leaves it, and nothing answers"
            " until `ollama serve` does."
        ),
    ),
    ProviderPreset(
        slug="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        context_window=131_072,
        max_tools=128,
        keys_url="https://console.groq.com/keys",
        docs_url="https://console.groq.com/docs/models",
        note="Free tier, no card. Fast enough that the round trip stops being the bottleneck.",
    ),
    ProviderPreset(
        slug="cerebras",
        label="Cerebras",
        base_url="https://api.cerebras.ai/v1",
        default_model="llama-3.3-70b",
        keys_url="https://cloud.cerebras.ai",
        docs_url="https://inference-docs.cerebras.ai/introduction",
        note="Free tier. The other fast open-weights option.",
    ),
    ProviderPreset(
        slug="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o",
        context_window=128_000,
        adapter="openai",
        keys_url="https://platform.openai.com/api-keys",
        docs_url="https://platform.openai.com/docs/models",
    ),
    ProviderPreset(
        slug="anthropic",
        label="Anthropic",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-sonnet-4-20250514",
        context_window=200_000,
        adapter="anthropic",
        keys_url="https://console.anthropic.com/settings/keys",
        docs_url="https://docs.anthropic.com/en/docs/about-claude/models",
    ),
    ProviderPreset(
        slug="google",
        label="Google Gemini",
        default_model="gemini-2.0-flash",
        context_window=1_000_000,
        adapter="google",
        keys_url="https://aistudio.google.com/app/apikey",
        docs_url="https://ai.google.dev/gemini-api/docs/models",
        note="No streaming adapter yet, so answers arrive whole rather than progressively.",
    ),
    ProviderPreset(
        slug="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        keys_url="https://openrouter.ai/keys",
        docs_url="https://openrouter.ai/models",
        note=(
            "One key for many providers. Model ids are namespaced,"
            " so pick one from the model list."
        ),
    ),
    ProviderPreset(
        slug="xai",
        label="xAI",
        base_url="https://api.x.ai/v1",
        default_model="grok-2-latest",
        keys_url="https://console.x.ai",
        docs_url="https://docs.x.ai/docs/models",
    ),
    ProviderPreset(
        slug="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        keys_url="https://platform.deepseek.com/api_keys",
        docs_url="https://api-docs.deepseek.com/quick_start/pricing",
    ),
    ProviderPreset(
        slug="mistral",
        label="Mistral",
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-large-latest",
        keys_url="https://console.mistral.ai/api-keys",
        docs_url="https://docs.mistral.ai/getting-started/models/models_overview/",
    ),
    ProviderPreset(
        slug="together",
        label="Together AI",
        base_url="https://api.together.xyz/v1",
        keys_url="https://api.together.xyz/settings/api-keys",
        docs_url="https://docs.together.ai/docs/serverless-models",
    ),
    ProviderPreset(
        slug="fireworks",
        label="Fireworks AI",
        base_url="https://api.fireworks.ai/inference/v1",
        keys_url="https://fireworks.ai/account/api-keys",
        docs_url="https://fireworks.ai/models",
    ),
    ProviderPreset(
        slug="nvidia",
        label="NVIDIA NIM",
        base_url="https://integrate.api.nvidia.com/v1",
        keys_url="https://build.nvidia.com",
        docs_url="https://build.nvidia.com/models",
        note="Model ids are namespaced, e.g. `nvidia/nemotron-3-ultra-550b-a55b`.",
    ),
    # --- free tiers that do not expire ------------------------------------
    #
    # Added 2026-08-30. Each model list below was fetched live that day, and the
    # default named is one that endpoint actually returned. Chat completions
    # need a key on all of them -- the listings are open, the inference is not
    # -- so **tool calling on these is unverified**, which is the thing PSOK
    # depends on most and the first thing to check when a key arrives.
    #
    # GitHub Models was asked for and is deliberately absent: its endpoint
    # answers `410 github_models_retirement_brownout`, a scheduled outage ahead
    # of retirement. Absent beats permanently-failing.
    ProviderPreset(
        slug="modelscope",
        label="ModelScope",
        base_url="https://api-inference.modelscope.cn/v1",
        default_model="deepseek-ai/DeepSeek-V4-Flash-0731",
        keys_url="https://modelscope.cn/my/myaccesstoken",
        docs_url="https://modelscope.cn/docs/model-service/API-Inference/intro",
        note=(
            "Alibaba's. 50 models on a free tier with no card, strongest on the"
            " Qwen and DeepSeek families. Ids are namespaced by owner."
        ),
    ),
    ProviderPreset(
        slug="ovhcloud",
        label="OVHcloud AI Endpoints",
        base_url="https://oai.endpoints.kepler.ai.cloud.ovh.net/v1",
        default_model="gpt-oss-120b",
        keys_url="https://endpoints.ai.cloud.ovh.net",
        docs_url="https://endpoints.ai.cloud.ovh.net/catalog",
        note=(
            "EU-hosted, 24 open models, permanently free. There is an anonymous"
            " tier at roughly two requests a minute per IP -- enough to prove it"
            " works and not enough to use, so get a token."
        ),
    ),
    ProviderPreset(
        slug="llm7",
        label="LLM7",
        base_url="https://api.llm7.io/v1",
        default_model="deepseek-v4-flash",
        keys_url="https://token.llm7.io",
        docs_url="https://api.llm7.io/v1/models",
        note=(
            "44 models behind one free OpenAI-compatible endpoint, including"
            " proxied frontier ones. A relay rather than a host: what you send"
            " passes through them, which is the trade for the price."
        ),
    ),
    ProviderPreset(
        slug="ollama-cloud",
        label="Ollama Cloud",
        base_url="https://ollama.com/v1",
        default_model="gpt-oss:120b",
        keys_url="https://ollama.com/settings/keys",
        docs_url="https://ollama.com/search?c=cloud",
        note=(
            "The hosted side of the local runner, 19 models. Distinct from the"
            " `ollama` entry above, which is this machine and needs no key."
        ),
    ),
    ProviderPreset(
        slug="cloudflare",
        label="Cloudflare Workers AI",
        # The account id lives in the path, so this is the one preset that does
        # not work as written. Left as a placeholder rather than omitted: the
        # rest of the entry -- the key reference, the default model, where to
        # get a token -- is still worth not researching, and a URL that says
        # ACCOUNT_ID fails visibly where a wrong one would fail as a 404 nobody
        # could explain.
        base_url="https://api.cloudflare.com/client/v4/accounts/ACCOUNT_ID/ai/v1",
        default_model="@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        keys_url="https://dash.cloudflare.com/profile/api-tokens",
        docs_url="https://developers.cloudflare.com/workers-ai/models/",
        note=(
            "Replace ACCOUNT_ID in the base URL with yours from the Cloudflare"
            " dashboard, or every call 404s. 10,000 neurons a day, reset at"
            " midnight UTC, run at the edge."
        ),
    ),
)

PRESETS_BY_SLUG: dict[str, ProviderPreset] = {p.slug: p for p in PROVIDER_PRESETS}

#: Seeded as live entries in a new providers.yaml -- every preset except the
#: ones needing a model id the user has to choose anyway.
#:
#: Listing costs nothing: `configured_providers` filters out any entry whose key
#: is missing, so a listed provider is not an offered one. What it buys is that
#: the file itself is the menu -- base URL, model and keychain ref already
#: written -- so adding a provider is `psok secrets set`, not research. That was
#: the point of extending `DEFAULT_PROVIDERS` rather than only building a
#: catalogue behind a screen.
SEEDED = (
    "ollama",
    "groq",
    "cerebras",
    "openai",
    "anthropic",
    "openrouter",
    "xai",
    "deepseek",
    "mistral",
    "together",
    "fireworks",
    "nvidia",
    "modelscope",
    "ovhcloud",
    "llm7",
    "ollama-cloud",
    # Not `cloudflare`: its base URL carries an account id, so a seeded entry
    # would be one that cannot answer until it is edited -- which is exactly the
    # "listed but dead" row this file exists to avoid.
)


def preset(slug: str) -> ProviderPreset | None:
    return PRESETS_BY_SLUG.get(slug)


def entry_for(preset: ProviderPreset) -> dict:
    """The providers.yaml mapping for a preset, omitting anything unset.

    Keeps the written file as short as the hand-written one it replaced -- an
    entry full of nulls invites someone to fill them in with guesses.
    """
    entry: dict = {"name": preset.slug}
    if preset.adapter and preset.adapter != preset.slug:
        entry["provider"] = preset.adapter
    if preset.base_url:
        entry["base_url"] = preset.base_url
    if preset.api_key_ref:
        entry["api_key_ref"] = preset.api_key_ref
    if preset.api_key_env:
        entry["api_key_env"] = preset.api_key_env
    if preset.default_model:
        entry["default_model"] = preset.default_model
    if preset.context_window:
        entry["context_window"] = preset.context_window
    if preset.max_tools:
        entry["max_tools"] = preset.max_tools
    return entry


def render_default_providers() -> str:
    """The starter providers.yaml, generated from the presets.

    Generated rather than hand-written so the file a new install gets and the
    catalogue the Settings panel offers cannot drift apart -- which is exactly
    what happened to Groq and Cerebras, present in one and absent from the other
    for long enough that `psok doctor` grew a check for it.
    """
    lines = [
        "# PSOK model providers. api_key_ref points at an OS keychain entry --",
        "# never a literal key.",
        "#",
        "# A listed provider is not an offered one: an entry whose key is missing is",
        "# skipped by the model picker until `psok secrets set <ref>` fills it in.",
        "# More providers -- OpenRouter, DeepSeek, Mistral, xAI, Together, Fireworks,",
        "# NVIDIA -- are in Settings > Models, or `psok providers add <name>`.",
        "providers:",
    ]
    for slug in SEEDED:
        p = PRESETS_BY_SLUG[slug]
        if p.note:
            lines.append(f"  # {p.label}: {p.note}")
        if p.keys_url:
            lines.append(f"  #   key: {p.keys_url}  ->  psok secrets set {p.api_key_ref}")
        entry = entry_for(p)
        lines.append(f"  - name: {entry['name']}")
        for key, value in entry.items():
            if key != "name":
                lines.append(f"    {key}: {value}")
    return "\n".join(lines) + "\n"
