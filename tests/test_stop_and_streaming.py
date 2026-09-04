"""Stop, and turns that always resolve.

Every test names the mutation that makes it fail. The timings matter: these
guard against a hang, and a test that merely passes slowly proves nothing.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.agent.director import Stopped, _race_cancel, _stream_until_cancelled


async def _slow(seconds: float = 30.0):
    await asyncio.sleep(seconds)
    return "should never arrive"


@pytest.mark.asyncio
async def test_stop_abandons_a_model_call_in_flight():
    """Stop used to be checked only between loop iterations.

    With a 120s timeout and three retries that is up to about eight minutes of
    a dead interface after pressing a button labelled Stop.

    Mutation check: `return await awaitable` at the top of `_race_cancel`.
    """
    cancel = asyncio.Event()
    started = time.monotonic()

    async def press_stop():
        await asyncio.sleep(0.05)
        cancel.set()

    asyncio.create_task(press_stop())
    with pytest.raises(Stopped):
        await _race_cancel(_slow(), cancel)

    assert time.monotonic() - started < 2, "Stop must not wait out the call"


@pytest.mark.asyncio
async def test_the_abandoned_call_is_actually_cancelled():
    """Not merely un-awaited. An un-cancelled request holds its socket open."""
    cancel = asyncio.Event()
    landed = asyncio.Event()

    async def work():
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            landed.set()
            raise

    cancel.set()
    with pytest.raises(Stopped):
        await _race_cancel(work(), cancel)
    assert landed.is_set(), "the work was left running, only the waiter went away"


@pytest.mark.asyncio
async def test_stop_lands_before_the_first_streamed_byte():
    """The wait before the first chunk is the long one, and the one a
    per-chunk check cannot see.

    Mutation check: iterate `stream` directly instead of through
    `_stream_until_cancelled`.
    """
    cancel = asyncio.Event()

    async def never_starts():
        await asyncio.sleep(30)
        yield "too late"

    async def press_stop():
        await asyncio.sleep(0.05)
        cancel.set()

    asyncio.create_task(press_stop())
    started = time.monotonic()
    with pytest.raises(Stopped):
        async for _ in _stream_until_cancelled(never_starts(), cancel):
            pass
    assert time.monotonic() - started < 2


@pytest.mark.asyncio
async def test_a_stream_that_finishes_normally_is_untouched():
    cancel = asyncio.Event()

    async def three():
        for n in ("a", "b", "c"):
            yield n

    assert [c async for c in _stream_until_cancelled(three(), cancel)] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_no_cancel_event_means_no_racing():
    """The CLI passes None. It must not pay for machinery it does not use."""
    assert await _race_cancel(_slow(0), None) == "should never arrive"


@pytest.mark.asyncio
async def test_a_cancelled_tool_call_does_not_block_the_next_one():
    """Cancelling the waiter used to leave the work running on a serial queue,
    so the *next* call to that connector stalled for the full timeout with
    nothing to explain it.

    Mutation check: drop the `waiter` race in `MCPConnection._serve`.
    """
    from backend.mcp.client import MCPConnection
    from backend.mcp.config import ServerConfig, Transport

    config = ServerConfig(name="slow", transport=Transport.STDIO, command="true")
    config.timeout_seconds = 30
    connection = MCPConnection(config)

    running = asyncio.Event()

    class _Session:
        async def call_tool(self, name, arguments):
            if name == "slow":
                running.set()
                await asyncio.sleep(30)
                return "never"
            return f"fast:{name}"

    server = asyncio.create_task(connection._serve(_Session()))
    try:
        first: asyncio.Future = asyncio.get_running_loop().create_future()
        await connection._requests.put(("slow", {}, first))
        await asyncio.wait_for(running.wait(), timeout=2)

        first.cancel()  # the turn was stopped

        second: asyncio.Future = asyncio.get_running_loop().create_future()
        await connection._requests.put(("quick", {}, second))
        assert await asyncio.wait_for(second, timeout=3) == "fast:quick"
    finally:
        # Cancel and let go. Awaiting a cancelled task from inside the test
        # propagates the cancellation into the test itself.
        server.cancel()


# ------------------------------------------------------- streaming honesty


def _sse(*frames: str):
    async def gen(*_a, **_k):
        for f in frames:
            yield f
    return gen


@pytest.mark.asyncio
async def test_a_reasoning_only_stream_is_not_an_answer(monkeypatch):
    """A thinking model that spends its budget in `reasoning_content` and stops
    produced no text and no tool call -- but the empty-stream fallback required
    reasoning to be empty too, so it never fired. The loop then burned both
    continuations and ended the turn on an empty bubble.

    Mutation check: put `not reasoning_parts` back into that condition.
    """
    from backend.runtime.providers import openai_compat
    from backend.runtime.types import ModelResponse

    client = openai_compat.OpenAICompatClient(
        base_url="https://example.invalid/v1", api_key="k", model="thinky"
    )
    monkeypatch.setattr(
        openai_compat, "stream_sse",
        _sse('{"choices":[{"delta":{"reasoning_content":"hmm..."}}]}'),
    )

    asked = {}

    async def fake_complete(messages, tools=None, params=None):
        asked["yes"] = True
        return ModelResponse(text="the actual answer")

    monkeypatch.setattr(client, "complete", fake_complete)

    events = [e async for e in client.stream([{"role": "user", "content": "hi"}])]
    assert asked.get("yes"), "silence after thinking must be asked again, not reported as an answer"
    assert events[-1].response.text == "the actual answer"


@pytest.mark.asyncio
async def test_an_error_frame_inside_a_200_is_raised_not_dropped(monkeypatch):
    from backend.runtime.providers import openai_compat

    client = openai_compat.OpenAICompatClient(
        base_url="https://example.invalid/v1", api_key="k", model="m"
    )
    monkeypatch.setattr(
        openai_compat, "stream_sse", _sse('{"error":{"message":"context length exceeded"}}')
    )

    with pytest.raises(openai_compat.ProviderStreamError, match="context length"):
        async for _ in client.stream([{"role": "user", "content": "hi"}]):
            pass


@pytest.mark.asyncio
async def test_anthropic_raises_on_an_in_stream_error(monkeypatch):
    """This branch did not exist, so `overloaded_error` mid-stream was dropped.

    Mutation check: delete the `kind == "error"` branch in `anthropic.stream`.
    """
    from backend.runtime.providers import anthropic
    from backend.runtime.providers.openai_compat import ProviderStreamError

    client = anthropic.AnthropicClient(
        base_url="https://example.invalid", api_key="k", model="claude-x"
    )
    monkeypatch.setattr(
        anthropic, "stream_sse",
        _sse('{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'),
    )

    with pytest.raises(ProviderStreamError, match="Overloaded"):
        async for _ in client.stream([{"role": "user", "content": "hi"}]):
            pass


@pytest.mark.asyncio
async def test_a_numeric_content_token_does_not_kill_the_stream(monkeypatch):
    """Cloudflare Workers AI serialises a purely numeric content token -- the
    "3" in a reply that counts -- as a JSON *number*, so `delta.content` arrives
    as an int. `"".join(text_parts)` then raised `expected str instance, int
    found` and the whole stream died over one token. The spec says content is a
    string; this is the shim for providers that treat that as advisory.

    Mutation check: drop the `_as_text` coercion in `stream` (append
    `delta["content"]` raw).
    """
    from backend.runtime.providers import openai_compat

    client = openai_compat.OpenAICompatClient(
        base_url="https://example.invalid/v1", api_key="k", model="m"
    )
    monkeypatch.setattr(
        openai_compat,
        "stream_sse",
        _sse(
            '{"choices":[{"delta":{"content":"count: "}}]}',
            '{"choices":[{"delta":{"content":3}}]}',
            '{"choices":[{"delta":{},"finish_reason":"stop"}]}',
        ),
    )

    events = [e async for e in client.stream([{"role": "user", "content": "count"}])]
    text = "".join(e.text for e in events if e.type == "text")
    assert text == "count: 3", "the numeric token is coerced, not dropped and not fatal"
    assert events[-1].response.text == "count: 3"


def test_numeric_content_is_coerced_in_the_non_streaming_path():
    """The same provider can send a numeric `message.content` on a plain call.

    Mutation check: revert `_as_text(message.get("content"))` to
    `message.get("content")` in `_parse`.
    """
    from backend.runtime.providers.openai_compat import OpenAICompatClient

    client = OpenAICompatClient(base_url="https://x/v1", api_key="k", model="m")
    parsed = client._parse({"choices": [{"message": {"content": 7}, "finish_reason": "stop"}]})
    assert parsed.text == "7"


@pytest.mark.asyncio
async def test_heartbeats_fill_a_silent_gap():
    """A long tool call puts no frames on the stream between `tool_call` and
    `tool_result`; a silent SSE stream is one a proxy drops and the client's
    watchdog gives up on. The wrapper must emit keepalives through the gap.

    Mutation check: `yield item` without the `timeout=` branch in
    `_with_heartbeats`.
    """
    from backend.api.main import _HEARTBEAT, _with_heartbeats

    async def slow():
        yield "start"
        await asyncio.sleep(0.3)  # a "long tool call" -- silent for the interval
        yield "end"

    got = [x async for x in _with_heartbeats(slow(), interval=0.05)]

    assert got[0] == "start" and got[-1] == "end", "real events still arrive, in order"
    assert got.count(_HEARTBEAT) >= 1, "the silent gap must be filled with keepalives"


@pytest.mark.asyncio
async def test_heartbeats_stop_when_the_source_ends():
    """No trailing keepalives after the last real event -- the wrapper returns
    on StopAsyncIteration rather than beating forever."""
    from backend.api.main import _HEARTBEAT, _with_heartbeats

    async def quick():
        yield "only"

    got = [x async for x in _with_heartbeats(quick(), interval=0.05)]
    assert got == ["only"], "a source that ends promptly emits no keepalives"
    assert _HEARTBEAT not in got
