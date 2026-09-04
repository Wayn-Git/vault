"""Provider registry and resolution (ADR-0001).

Four builtin adapters. Any provider name not in the registry is looked up in the
user's providers.yaml and resolves to the OpenAI-compatible adapter unless the
entry declares a different native provider -- which is how Ollama, vLLM,
LM Studio, NVIDIA NIM, Groq and OpenRouter are supported with no code.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from backend.config import ProviderConfig, configured_providers, load_providers, load_tiers
from backend.runtime.http import MAX_RETRIES
from backend.runtime.providers import anthropic, google, ollama, openai_compat
from backend.runtime.types import ResolvedModel

log = logging.getLogger(__name__)

#: `(config, model, *, max_retries) -> ResolvedModel`. The retry allowance is
#: a keyword with a default, so an adapter written against the two-argument form
#: still satisfies it -- the fallback chain is the only caller that sets it.
Initializer = Callable[..., ResolvedModel]

PROVIDER_REGISTRY: dict[str, Initializer] = {
    "openai": openai_compat.initialize,
    "openai-compatible": openai_compat.initialize,
    "anthropic": anthropic.initialize,
    "google": google.initialize,
    "gemini": google.initialize,
    "ollama": ollama.initialize,
}


class ProviderNotConfigured(RuntimeError):
    pass


def is_known_provider(provider: str) -> bool:
    """Whether resolve() would find an adapter, without initializing one.

    Lets an interface reject a bad provider name up front rather than letting it
    surface mid-turn, where the failure lands inside an already-open stream.
    """
    return provider in load_providers() or provider in PROVIDER_REGISTRY


def resolve_tier(
    tier: str, *, max_retries: int = MAX_RETRIES
) -> ResolvedModel | None:
    """The model configured for a job, or None when nothing is configured for it.

    None is the ordinary answer on a machine with one provider, and every caller
    treats it as "use the conversation's own model" rather than as a failure.
    An offer PSOK cannot honour -- a heavy tier with nothing behind it -- is
    worse than no offer, so this returning None is what withholds the escalation
    tool rather than a separate flag somebody has to keep in step.
    """
    entry = load_tiers().get(tier)
    if entry is None:
        return None
    try:
        return resolve(entry.provider, entry.model, max_retries=max_retries)
    except ProviderNotConfigured:
        # The provider was configured when the file was read and is not now, or
        # its key has gone. A tier that cannot be built is the same as one that
        # was never named.
        log.warning("tier '%s' names %s, which cannot be resolved", tier, entry.provider)
        return None


def default_chain(*, tier: str = "fast", limit: int | None = None) -> list:
    """Who to ask for background work that has no conversation behind it.

    A turn gets its provider from the conversation and its fallbacks from
    `build_chain`. A briefing has no conversation, so this picks the head the
    same way the rest of the system would -- the named tier if there is one,
    otherwise the first configured provider that declares a model -- and then
    hands it to `build_chain` for the alternatives.

    Walking a chain matters more here than it does in a turn. Nobody is watching
    at seven in the morning, and providers.yaml commonly lists a local endpoint
    first: without the chain, "Ollama is not running" was the entire briefing on
    a machine with two working cloud providers configured behind it.

    An empty list means nothing on this machine can answer, which the caller
    must say out loud. An entry with no prose and a stated reason is honest; an
    entry with invented prose is not.
    """
    from backend.runtime.chain import MAX_FALLBACK_LINKS, Link, _usable, build_chain

    configured = configured_providers()
    head: Link | None = None

    entry = load_tiers().get(tier)
    if entry is not None and entry.provider in configured:
        head = Link(provider=entry.provider, model=entry.model)
    else:
        for name, config in configured.items():
            if _usable(name, config):
                head = Link(provider=name, model=config.default_model or "")
                break

    if head is None:
        return []
    return build_chain(
        head.provider,
        head.model,
        configs=configured,
        limit=MAX_FALLBACK_LINKS if limit is None else limit,
    )


def resolve(
    provider: str, model: str | None = None, *, max_retries: int = MAX_RETRIES
) -> ResolvedModel:
    configs = load_providers()
    config = configs.get(provider)

    if config is None:
        if provider in PROVIDER_REGISTRY:
            # A builtin adapter with no providers.yaml entry: usable via env vars.
            config = ProviderConfig(name=provider)
        else:
            raise ProviderNotConfigured(
                f"provider '{provider}' is not in providers.yaml and is not a builtin adapter"
            )

    # An entry may name the adapter explicitly; otherwise use its own name;
    # otherwise fall through to the OpenAI-compatible adapter.
    adapter_key = config.provider or config.name
    initializer = PROVIDER_REGISTRY.get(adapter_key, openai_compat.initialize)
    return initializer(config, model, max_retries=max_retries)
