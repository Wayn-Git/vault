"""Embedding generation, local by default (ADR-0013).

Embeddings touch every document in the user's vault, so this is exactly the role
where the local-first posture is strongest: the default runs through Ollama on
the user's own machine. A cloud embedding API is configurable through the same
provider entries the chat models use, not a parallel system.
"""

from __future__ import annotations

import logging

from backend.config import load_providers
from backend.runtime.failures import FailureKind
from backend.runtime.http import ProviderHTTPError, post_json
from backend.secrets import resolve_api_key

log = logging.getLogger(__name__)

DEFAULT_LOCAL_MODEL = "nomic-embed-text"
DEFAULT_LOCAL_BASE = "http://localhost:11434"
BATCH_SIZE = 32

# Endpoints that refused a connection, so the next caller in this process does
# not pay the wait again.
#
# A refused connection is not a transient failure: nothing is listening, and
# trying three more times with backoff cannot change that. It cost 6.09s
# measured, on a path the agent loop runs twice a turn -- recall before the
# first model call, and again after memory extraction -- so a machine without
# Ollama installed paid ~12s per turn for a service it does not have. Cleared
# only by restarting, which is also when someone would have started Ollama.
_UNREACHABLE: set[str] = set()


def forget_unreachable() -> None:
    """Try a previously-refused endpoint again (it may have been started since)."""
    _UNREACHABLE.clear()


class EmbeddingError(RuntimeError):
    pass


class Embedder:
    def __init__(self, provider: str = "ollama", model: str | None = None):
        self.provider = provider
        self.model = model or DEFAULT_LOCAL_MODEL

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        result = await self.embed([text])
        if not result:
            raise EmbeddingError("embedding returned no vector")
        return result[0]

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        config = load_providers().get(self.provider)
        base_url = (config.base_url if config else None) or DEFAULT_LOCAL_BASE

        if self.provider == "ollama" or "11434" in base_url:
            return await self._embed_ollama(batch, base_url)
        return await self._embed_openai_compatible(batch, base_url, config)

    async def _embed_ollama(self, batch: list[str], base_url: str) -> list[list[float]]:
        native = base_url.rstrip("/")
        if native.endswith("/v1"):
            native = native[:-3].rstrip("/")
        url = f"{native}/api/embed"
        if url in _UNREACHABLE:
            raise EmbeddingError(f"Ollama at {native} refused a connection earlier this session")
        try:
            data = await post_json(
                url,
                headers={"Content-Type": "application/json"},
                payload={"model": self.model, "input": batch},
                timeout=120.0,
                # A refused connection means nothing is listening, which no
                # amount of backoff fixes.
                max_retries=0,
            )
        except ProviderHTTPError as exc:
            # Was `if "unreachable" in str(exc)`: a caller re-parsing prose the
            # raiser already knew the shape of. The kind says it outright.
            if exc.kind is FailureKind.UNREACHABLE:
                _UNREACHABLE.add(url)
            raise EmbeddingError(
                f"could not reach Ollama at {native}. Is it running, and has"
                f" '{self.model}' been pulled? (ollama pull {self.model}). {exc}"
            ) from exc
        except Exception as exc:
            raise EmbeddingError(
                f"could not reach Ollama at {native}. Is it running, and has"
                f" '{self.model}' been pulled? (ollama pull {self.model}). {exc}"
            ) from exc

        embeddings = data.get("embeddings")
        if not embeddings:
            raise EmbeddingError(f"Ollama returned no embeddings for model '{self.model}'")
        return embeddings

    async def _embed_openai_compatible(
        self, batch: list[str], base_url: str, config
    ) -> list[list[float]]:
        api_key = resolve_api_key(
            ref=getattr(config, "api_key_ref", None), env=getattr(config, "api_key_env", None)
        )
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        data = await post_json(
            f"{base_url.rstrip('/')}/embeddings",
            headers=headers,
            payload={"model": self.model, "input": batch},
            timeout=120.0,
        )
        rows = sorted(data.get("data") or [], key=lambda r: r.get("index", 0))
        if not rows:
            raise EmbeddingError(f"'{self.provider}' returned no embeddings")
        return [row["embedding"] for row in rows]


async def available(provider: str = "ollama", model: str | None = None) -> tuple[bool, str]:
    """Check embeddings work before indexing, so failure is reported once up front."""
    embedder = Embedder(provider, model)
    try:
        vector = await embedder.embed_one("probe")
    except Exception as exc:
        return False, str(exc)
    return True, f"{embedder.model} ({len(vector)} dimensions)"
