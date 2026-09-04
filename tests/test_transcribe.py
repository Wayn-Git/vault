"""Speech to text, and every gate in front of it.

Each cap is checked before the step it protects, and the point of most of these
is that the expensive thing does not happen -- not that it happens and fails.
"""

from __future__ import annotations

import pytest

from backend.config import add_provider, save_transcription
from backend.runtime import availability
from backend.runtime.transcribe import (
    MAX_UPLOAD_BYTES,
    TranscriptionUnavailable,
    resolve_transcriber,
    transcribe,
    unavailable_reason,
)


@pytest.fixture
def groq(db, psok_home):
    """A provider with a key, so it counts as configured."""
    from backend.secrets import set_secret

    set_secret("psok/groq", "gsk_" + "x" * 40)
    add_provider(
        {
            "name": "groq",
            "base_url": "https://api.groq.com/openai/v1",
            "default_model": "a-model",
            "api_key_ref": "psok/groq",
        }
    )
    return "groq"


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "clip.ogg"
    path.write_bytes(b"not really audio, but the right size")
    return path


def test_with_no_provider_the_reason_is_stated_not_guessed(db, audio):
    """A reel with no caption and nothing able to transcribe has no text at all.
    Saying which of those it is, is the difference between a thin item and a
    broken one.

    Mutation check: return an empty Transcript instead of raising.
    """
    assert resolve_transcriber() is None
    with pytest.raises(TranscriptionUnavailable) as caught:
        import asyncio

        asyncio.run(transcribe(audio))
    assert "Groq and OpenAI" in str(caught.value)
    assert "Groq and OpenAI" in unavailable_reason()


def test_a_configured_choice_wins_over_the_guess(groq):
    """The allowlist is a fallback, not a policy. An explicit block always wins.

    Mutation check: check the allowlist before providers.yaml.
    """
    assert resolve_transcriber()[1] == "whisper-large-v3-turbo"

    save_transcription("groq", "whisper-large-v3")
    config, model = resolve_transcriber()
    assert (config.name, model) == ("groq", "whisper-large-v3")


async def test_a_file_over_the_cap_is_refused_before_it_is_uploaded(groq, tmp_path, monkeypatch):
    """Twenty-five megabytes of somebody's bandwidth, spent to be told no.

    Mutation check: check the size after the request.
    """
    def fail(*args, **kwargs):
        raise AssertionError("nothing should be uploaded past the cap")

    monkeypatch.setattr("backend.runtime.transcribe._client", fail)

    big = tmp_path / "long.ogg"
    big.write_bytes(b"0" * (MAX_UPLOAD_BYTES + 1))

    with pytest.raises(TranscriptionUnavailable, match="over the"):
        await transcribe(big)


async def test_a_missing_file_is_a_sentence_not_a_traceback(groq, tmp_path):
    with pytest.raises(TranscriptionUnavailable, match="no audio"):
        await transcribe(tmp_path / "gone.ogg")


async def test_a_refused_file_does_not_mark_the_provider_unavailable(groq, audio, monkeypatch):
    """The cross-contamination guard.

    A 413 says *this file* was too big. Recording it against the provider would
    make the chat fallback chain skip a perfectly healthy Groq because somebody
    saved a long video.

    Mutation check: record every failure kind.
    """
    _patch_response(monkeypatch, status=413, body="file too large")
    availability.forget()

    with pytest.raises(TranscriptionUnavailable):
        await transcribe(audio)

    assert availability.cached("groq") is None


async def test_a_rejected_key_says_so_without_taking_the_provider_out(groq, audio, monkeypatch):
    """A 401 here is a wrong key, not an unwell provider.

    `availability` only records the kinds that mean "this provider, right now",
    and a rejected key is not one of them -- the fix is a new key, not a
    different provider. So the sentence names Groq and the chat chain is left
    alone.
    """
    _patch_response(monkeypatch, status=401, body="invalid api key")
    availability.forget()

    with pytest.raises(TranscriptionUnavailable, match="groq refused"):
        await transcribe(audio)

    assert availability.cached("groq") is None


async def test_speech_comes_back_as_text(groq, audio, monkeypatch):
    _patch_response(monkeypatch, status=200, body="so the thing about pour over is grind size")
    result = await transcribe(audio)

    assert result.text.startswith("so the thing")
    assert (result.provider, result.model) == ("groq", "whisper-large-v3-turbo")


async def test_silence_is_no_transcript_rather_than_a_short_one(groq, audio, monkeypatch):
    """A reel that is ninety per cent licensed music transcribes to nothing
    useful, and a two-word transcript is worse than an honest empty one."""
    _patch_response(monkeypatch, status=200, body="  . ")
    assert (await transcribe(audio)).text == ""


def _patch_response(monkeypatch, *, status: int, body: str):
    class Response:
        status_code = status
        text = body

        def json(self):
            raise ValueError("not json")

    class Client:
        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("backend.runtime.transcribe._client", lambda timeout: Client())
