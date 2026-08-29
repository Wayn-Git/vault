"""Ollama adapter.

Ollama speaks the OpenAI chat-completions format, so it rides the compatible
client. The thin adapter exists only for the two things the generic fallback
cannot do: enumerating locally installed models and native embeddings, both of
which the first-run experience and the retrieval pipeline need.
"""

from __future__ import annotations

from psok.config import ProviderConfig
from psok.runtime.http import MAX_RETRIES
from psok.runtime.providers.openai_compat import OpenAICompatClient
from psok.runtime.types import Capabilities, ResolvedModel

DEFAULT_BASE = "http://localhost:11434"


def _native_base(base_url: str | None) -> str:
    """Strip the /v1 OpenAI shim to reach Ollama's own API."""
    base = (base_url or DEFAULT_BASE).rstrip("/")
    return base[:-3].rstrip("/") if base.endswith("/v1") else base


def initialize(
    config: ProviderConfig, model: str | None = None, *, max_retries: int = MAX_RETRIES
) -> ResolvedModel:
    resolved_model = model or config.default_model
    if not resolved_model:
        raise ValueError(f"no model specified for provider '{config.name}'")
    base = config.base_url or f"{DEFAULT_BASE}/v1"
    client = OpenAICompatClient(
        base_url=base, api_key=None, model=resolved_model, max_retries=max_retries
    )
    return ResolvedModel(
        provider=config.name,
        model=resolved_model,
        client=client,
        capabilities=Capabilities(
            tools=True,
            streaming=True,
            vision=False,
            reasoning=False,
            # A local model's window is whatever the Modelfile says, which only
            # the person who pulled it knows.
            context_window=config.context_window or 32_768,
            max_tools=config.max_tools,
        ),
    )
