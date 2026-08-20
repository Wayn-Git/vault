"""Provider registry and resolution (ADR-0001).

Four builtin adapters. Any provider name not in the registry is looked up in the
user's providers.yaml and resolves to the OpenAI-compatible adapter unless the
entry declares a different native provider -- which is how Ollama, vLLM,
LM Studio, NVIDIA NIM, Groq and OpenRouter are supported with no code.
"""

from __future__ import annotations

from collections.abc import Callable

from psok.config import ProviderConfig, load_providers
from psok.runtime.providers import anthropic, google, ollama, openai_compat
from psok.runtime.types import ResolvedModel

Initializer = Callable[[ProviderConfig, str | None], ResolvedModel]

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


def resolve(provider: str, model: str | None = None) -> ResolvedModel:
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
    return initializer(config, model)
