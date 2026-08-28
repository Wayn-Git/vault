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

from psok.runtime.failures import FailureKind, classify_status, should_retry

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


class ProviderError(RuntimeError):
    """Base for every provider failure, carrying why rather than only what.

    `kind` is the field callers branch on; the message stays human prose. Both
    exist because the two audiences are different -- a fallback chain needs the
    kind, a user reading a `warning` frame needs the sentence.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: FailureKind = FailureKind.NON_RETRYABLE,
        status: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.body = body

    @property
    def retryable(self) -> bool:
        return should_retry(self.kind)


class ProviderHTTPError(ProviderError):
    """Carries the provider's own error body, which is where diagnostics live."""


class ProviderStreamError(ProviderError):
    """An error frame arrived inside an already-successful 200 stream.

    Lives here rather than in an adapter because both the OpenAI-compatible and
    Anthropic adapters raise it, and Anthropic was importing it -- along with a
    private helper -- across module boundaries to do so.
    """


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


def is_retryable(status: int, body: str | None = None) -> bool:
    """Whether asking this same endpoint again could plausibly work.

    The body is consulted because a 429 is two different failures wearing one
    status: a rate limit clears by waiting, an exhausted quota does not, and
    retrying the second one spends four attempts to learn what the first
    response already said.
    """
    return should_retry(classify_status(status, body))


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
    last_status: int | None = None
    last_body: str | None = None

    for attempt in range(max_retries + 1):
        try:
            response = await _client(timeout).post(
                url, headers=headers, json=payload, params=params, timeout=timeout
            )
        except TRANSIENT_EXCEPTIONS as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            last_status, last_body = None, None
            if attempt == max_retries:
                raise ProviderHTTPError(
                    f"{url} unreachable: {last_error}", kind=FailureKind.UNREACHABLE
                ) from exc
            await asyncio.sleep(backoff(attempt))
            continue

        if response.status_code < 400:
            return response.json()

        # raise_for_status() throws the body away; the body is the diagnostic.
        body = response.text[:1000]
        last_error = f"{response.status_code}: {body}"
        last_status, last_body = response.status_code, body
        if not is_retryable(response.status_code, body) or attempt == max_retries:
            raise ProviderHTTPError(
                f"{url} returned {last_error}",
                kind=classify_status(response.status_code, body),
                status=response.status_code,
                body=body,
            )

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

    raise ProviderHTTPError(
        f"{url} returned {last_error}",
        kind=(
            classify_status(last_status, last_body)
            if last_status is not None
            else FailureKind.UNREACHABLE
        ),
        status=last_status,
        body=last_body,
    )


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
                    if not is_retryable(response.status_code, body) or attempt == max_retries:
                        raise ProviderHTTPError(
                            f"{url} returned {error}",
                            kind=classify_status(response.status_code, body),
                            status=response.status_code,
                            body=body,
                        )
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
                # Once bytes have moved, a different provider cannot take over
                # cleanly either -- half an answer is already on screen -- so
                # this is not a fallback opportunity, only a failure.
                raise ProviderHTTPError(
                    f"{url} stream failed: {exc}",
                    kind=(FailureKind.NON_RETRYABLE if started else FailureKind.UNREACHABLE),
                ) from exc
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
