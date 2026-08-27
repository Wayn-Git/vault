"""Shared HTTP behaviour for every provider adapter.

Retry lived only in the OpenAI-compatible adapter, which meant Anthropic and
Google were exposed to exactly the transient 5xx that was observed in practice
against NVIDIA NIM. Provider quirks belong in provider modules; "the network is
unreliable" is not a provider quirk.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from typing import Any

import httpx

MAX_RETRIES = 3
RETRYABLE_STATUS = {408, 409, 425, 429}
TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)

log = logging.getLogger(__name__)


class ProviderHTTPError(RuntimeError):
    """Carries the provider's own error body, which is where diagnostics live."""


def backoff(attempt: int) -> float:
    """Exponential backoff with jitter, so retries do not synchronise."""
    return min(2.0**attempt, 8.0) * (0.5 + random.random() / 2)


# One client per event loop, so connections are reused across calls.
#
# A client was built and closed per request and per retry, which meant a fresh
# TCP and TLS handshake to the provider every time. A browser task makes on the
# order of 26 model calls -- each one a tool call's worth of round trip -- so
# that was 26 handshakes to the same host, paid in series, before any tokens
# moved. Keyed by loop because a client is bound to the loop that created it,
# and the CLI, the API and tests each run their own.
_CLIENTS: dict[object, httpx.AsyncClient] = {}


def _client(timeout: float) -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    client = _CLIENTS.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=16, keepalive_expiry=300.0),
        )
        _CLIENTS[loop] = client
    return client


async def close_clients() -> None:
    """Close this loop's pooled client. Called on shutdown; safe to skip."""
    loop = asyncio.get_running_loop()
    client = _CLIENTS.pop(loop, None)
    if client is not None and not client.is_closed:
        await client.aclose()


def is_retryable(status: int) -> bool:
    return status in RETRYABLE_STATUS or status >= 500


def _delay_for(response: httpx.Response, attempt: int) -> float:
    delay = backoff(attempt)
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return max(delay, float(retry_after))
        except ValueError:
            pass
    return delay


async def post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    params: dict[str, Any] | None = None,
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """POST JSON, retrying transient failures, and surface the error body on give-up."""
    last_error = "no response"

    for attempt in range(max_retries + 1):
        try:
            response = await _client(timeout).post(
                url, headers=headers, json=payload, params=params, timeout=timeout
            )
        except TRANSIENT_EXCEPTIONS as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == max_retries:
                raise ProviderHTTPError(f"{url} unreachable: {last_error}") from exc
            await asyncio.sleep(backoff(attempt))
            continue

        if response.status_code < 400:
            return response.json()

        # raise_for_status() throws the body away; the body is the diagnostic.
        last_error = f"{response.status_code}: {response.text[:1000]}"
        if not is_retryable(response.status_code) or attempt == max_retries:
            raise ProviderHTTPError(f"{url} returned {last_error}")

        delay = _delay_for(response, attempt)
        log.warning(
            "%s returned %s, retrying in %.1fs (attempt %d/%d)",
            url,
            response.status_code,
            delay,
            attempt + 1,
            max_retries,
        )
        await asyncio.sleep(delay)

    raise ProviderHTTPError(f"{url} returned {last_error}")


async def stream_sse(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    params: dict[str, Any] | None = None,
    max_retries: int = MAX_RETRIES,
) -> AsyncIterator[str]:
    """Yield raw `data:` payloads from a server-sent-event stream.

    Retries only apply before the first byte arrives. Once tokens are flowing a
    retry would replay a partial response, so a mid-stream failure is raised.
    """
    for attempt in range(max_retries + 1):
        started = False
        try:
            async with _client(timeout).stream(
                "POST", url, headers=headers, json=payload, params=params, timeout=timeout
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode(errors="replace")[:1000]
                    error = f"{response.status_code}: {body}"
                    if not is_retryable(response.status_code) or attempt == max_retries:
                        raise ProviderHTTPError(f"{url} returned {error}")
                    await asyncio.sleep(_delay_for(response, attempt))
                    continue

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data and data != "[DONE]":
                        started = True
                        yield data
                return
        except TRANSIENT_EXCEPTIONS as exc:
            if started or attempt == max_retries:
                raise ProviderHTTPError(f"{url} stream failed: {exc}") from exc
            # Nothing had arrived yet, so replaying is safe -- but it is a whole
            # request, and the provider may well have generated a response it
            # then failed to deliver. Unlogged, a turn could silently cost four
            # times the tokens and four times the wall clock with no trace.
            log.warning(
                "%s dropped the stream before any data; retrying in full (attempt %d/%d): %s",
                url,
                attempt + 1,
                max_retries,
                exc,
            )
            await asyncio.sleep(backoff(attempt))
