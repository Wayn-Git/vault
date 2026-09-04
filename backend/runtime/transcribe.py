"""Speech to text, through a provider that already has a key.

This lives in `backend/runtime/` and not in `backend/media/` because that is
where every other "talk to a configured provider" concern lives -- key
resolution, failure classification, availability. `backend/media/` shells out to
ffmpeg; this posts to an API. They are different layers even though one feeds
the other.

It is also deliberately **not** a fourth tier. `default_chain` describes chat,
and a chat tier that silently doubled as a transcription tier is exactly the kind
of drift that makes a config file stop meaning what it says. The choice is:
an explicit `transcription:` block in providers.yaml, else the first configured
provider on a short allowlist of endpoints observed to serve OpenAI's
`/audio/transcriptions` shape.

A short allowlist rather than a probe, because finding out an endpoint answers
404 by uploading twenty megabytes to it costs a minute of somebody's bandwidth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from backend.config import ProviderConfig, configured_providers, load_transcription
from backend.runtime import availability
from backend.runtime.failures import FailureKind
from backend.runtime.http import _client
from backend.secrets import resolve_api_key

log = logging.getLogger(__name__)

#: Providers observed to serve `/audio/transcriptions`, and what to ask them for.
KNOWN_MODELS = {
    "groq": "whisper-large-v3-turbo",
    "openai": "whisper-1",
}

#: Groq refuses at 25MB. Under it, with room for the multipart envelope.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024
DEFAULT_TIMEOUT = 300.0

#: Shorter than this and there is nothing to search on or summarise from, so it
#: is treated as no transcript at all rather than as a bad one.
MIN_USEFUL_CHARS = 40


class TranscriptionUnavailable(RuntimeError):
    """Nothing here can transcribe. Carries a sentence fit to show someone."""


@dataclass(frozen=True)
class Transcript:
    text: str
    provider: str
    model: str


def resolve_transcriber() -> tuple[ProviderConfig, str] | None:
    """Which provider and model, or None because none of them can."""
    configured = configured_providers()

    chosen = load_transcription()
    if chosen is not None and chosen.provider in configured:
        return configured[chosen.provider], chosen.model

    for name, config in configured.items():
        model = KNOWN_MODELS.get(name)
        if model:
            return config, model
    return None


def unavailable_reason() -> str:
    return (
        "no configured provider here transcribes audio, so a reel with no caption"
        " has no text at all. Groq and OpenAI both do -- add a key for one in"
        " Settings, then re-enrich."
    )


async def transcribe(
    path: Path, *, language: str | None = None, timeout: float = DEFAULT_TIMEOUT
) -> Transcript:
    """What was actually said. Raises rather than guessing."""
    resolved = resolve_transcriber()
    if resolved is None:
        raise TranscriptionUnavailable(unavailable_reason())
    config, model = resolved

    if not path.exists():
        raise TranscriptionUnavailable(f"there is no audio at {path}")
    size = path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        # Splitting with overlap is a real feature and is not this one. Saying so
        # is better than silently transcribing the first four minutes.
        raise TranscriptionUnavailable(
            f"the audio is {size // (1024 * 1024)}MB, over the"
            f" {MAX_UPLOAD_BYTES // (1024 * 1024)}MB a transcription request accepts."
            " Long recordings are not split up yet."
        )

    key = resolve_api_key(ref=config.api_key_ref, env=config.api_key_env)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    data = {"model": model, "response_format": "text"}
    if language:
        data["language"] = language

    try:
        with path.open("rb") as handle:
            response = await _client(timeout).post(
                f"{config.base_url.rstrip('/')}/audio/transcriptions",
                headers=headers,
                data=data,
                files={"file": (path.name, handle, "application/octet-stream")},
                timeout=timeout,
            )
    except httpx.HTTPError as exc:
        # Unreachable is about the provider, so the chat chain should know.
        availability.record_failure(config.name, FailureKind.UNREACHABLE, str(exc))
        raise TranscriptionUnavailable(
            f"{config.name} could not be reached to transcribe: {exc}"
        ) from exc

    if response.status_code >= 400:
        body = response.text[:300]
        # Deliberately not recorded against the provider. A 413 means *this file*
        # was too big and a 401 means the key is wrong -- neither is "this
        # provider is unwell", and `availability.record_failure` ignores both
        # kinds anyway, for its own stated reasons. Marking Groq unavailable
        # because somebody saved a long video would make the chat fallback chain
        # skip a provider that is working perfectly.
        raise TranscriptionUnavailable(
            f"{config.name} refused the transcription (HTTP {response.status_code}): {body}"
        )

    availability.record_success(config.name)
    text = _text_of(response)
    if len(text.strip()) < MIN_USEFUL_CHARS:
        return Transcript("", config.name, model)
    return Transcript(text.strip(), config.name, model)


def _text_of(response: httpx.Response) -> str:
    """`response_format=text` returns bare text; some gateways still send JSON."""
    body = response.text or ""
    stripped = body.lstrip()
    if stripped.startswith("{"):
        try:
            return str(response.json().get("text") or "")
        except ValueError:
            return body
    return body
