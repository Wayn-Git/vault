"""Which configured providers can actually answer right now.

`has_key` answers a different question -- whether the credential a provider says
it needs is present -- and for a local endpoint the honest answer is "it needs
none", so Ollama is reported configured whether or not anything is listening on
its port. Four conversations in the real database collected nine consecutive
`All connection attempts failed` because of exactly that: the picker offered a
provider, every turn against it died on the first round trip, and the failure
read as PSOK being broken rather than as `ollama serve` not running.

Two sources feed this, deliberately kept apart:

* **A probe**, for endpoints whose credential tells us nothing. One cheap
  request to the endpoint's model list. Any HTTP answer at all counts as
  reachable -- a 401 means something is there and disagrees with us, which is a
  different problem from nothing being there.
* **Observed failures**, for everything else. Probing a dozen cloud providers on
  a health poll that runs every twenty seconds would spend real latency to
  learn what the next turn finds out for free, so a cloud provider is presumed
  available until a turn proves otherwise, and the director reports what it saw.

Both entries expire. A provider that was down is not down forever, and a cache
with no way out is how "start Ollama and it still says unavailable" happens.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from backend.config import ProviderConfig
from backend.runtime.failures import FailureKind

#: How long a probe result is trusted. Short enough that starting a local server
#: is noticed within one health poll or two, long enough that a picker render
#: does not become a burst of network calls.
PROBE_TTL_SECONDS = 60.0

#: How long an observed failure sticks. Longer than a probe because it cost a
#: real turn to learn, shorter than a session because providers recover.
FAILURE_TTL_SECONDS = 300.0

#: A probe is a liveness check, not a request that has to succeed. Anything
#: slower than this is unusable for a turn anyway.
PROBE_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class Availability:
    name: str
    available: bool
    #: Prose for a person, empty when there is nothing to explain.
    reason: str = ""
    #: "probe" or "observed" -- so an interface can say whether this was checked
    #: or merely remembered.
    source: str = "probe"


_cache: dict[str, tuple[float, Availability]] = {}
_locks: dict[str, asyncio.Lock] = {}


def forget(name: str | None = None) -> None:
    """Drop what is remembered, for one provider or all of them.

    The escape hatch every cache of "this is broken" needs: the user fixed the
    thing and wants to be believed without restarting the process.
    """
    if name is None:
        _cache.clear()
    else:
        _cache.pop(name, None)


def record_failure(name: str, kind: FailureKind, message: str = "") -> None:
    """Remember that a real turn could not reach this provider.

    Only the kinds that mean "this provider, right now" are recorded. A 404 for
    a model name says nothing about the provider's health and must not take it
    out of the picker -- the fix for that is a different model, not a different
    provider. `NON_RETRYABLE_RATE_LIMIT` belongs here too: an account whose
    tokens-per-minute ceiling is smaller than what this request needed will
    fail the same way on the next turn, and a picker that keeps offering it
    anyway is what turned three near-identical 413s into three separate
    real conversations.
    """
    if kind not in (
        FailureKind.UNREACHABLE,
        FailureKind.UPSTREAM_UNHEALTHY,
        FailureKind.NON_RETRYABLE_RATE_LIMIT,
    ):
        return
    reason = {
        FailureKind.UNREACHABLE: "nothing answered at its endpoint",
        FailureKind.UPSTREAM_UNHEALTHY: "the provider is returning server errors",
        FailureKind.NON_RETRYABLE_RATE_LIMIT: "the account's rate limit or quota was exceeded",
    }[kind]
    _cache[name] = (
        time.monotonic() + FAILURE_TTL_SECONDS,
        Availability(name=name, available=False, reason=message or reason, source="observed"),
    )


def record_success(name: str) -> None:
    """A provider that just answered is available, whatever was remembered."""
    _cache[name] = (
        time.monotonic() + PROBE_TTL_SECONDS,
        Availability(name=name, available=True, source="observed"),
    )


def cached(name: str) -> Availability | None:
    entry = _cache.get(name)
    if entry is None:
        return None
    expires, value = entry
    if time.monotonic() >= expires:
        del _cache[name]
        return None
    return value


def needs_probe(config: ProviderConfig) -> bool:
    """Whether this provider's credential leaves its availability unknown.

    An entry declaring no key is either a local server or an unauthenticated
    one; both can be absent while looking perfectly configured. An entry with a
    key has already told us something, and asking the network to confirm it on
    every health poll costs more than it returns.
    """
    return not config.api_key_ref and not config.api_key_env


async def probe(config: ProviderConfig) -> Availability:
    """One cheap request to the endpoint, cached for `PROBE_TTL_SECONDS`."""
    known = cached(config.name)
    if known is not None:
        return known

    lock = _locks.setdefault(config.name, asyncio.Lock())
    async with lock:
        # A second caller that queued behind the probe gets its answer rather
        # than making the same request again.
        known = cached(config.name)
        if known is not None:
            return known
        result = await _probe_now(config)
        _cache[config.name] = (time.monotonic() + PROBE_TTL_SECONDS, result)
        return result


async def _probe_now(config: ProviderConfig) -> Availability:
    import httpx

    base = (config.base_url or "").rstrip("/")
    if not base:
        # Nothing to probe against; the adapter's own default will have to do.
        return Availability(name=config.name, available=True)

    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
            await client.get(f"{base}/models")
    except Exception as exc:
        return Availability(
            name=config.name,
            available=False,
            reason=f"nothing answered at {base} ({type(exc).__name__})",
        )
    # Any status at all means something is listening. A 401 or a 404 is the
    # endpoint disagreeing with the request, which is not the same failure as
    # the endpoint not being there, and is not this function's question.
    return Availability(name=config.name, available=True)


async def ping(config: ProviderConfig) -> Availability:
    """A fresh liveness check the user asked for, cache and key-gate ignored.

    `probe` answers the picker's passive question and only runs for providers
    whose credential says nothing (`needs_probe`); a Ping button is the opposite
    -- a person pressing it means "check this one now, whatever you remember and
    whatever kind of provider it is". So the cache is dropped first and the
    endpoint is hit directly. Any status answering counts as reachable; a
    key-bearing provider's 401 still proves something is there. The fresh result
    is remembered like any other probe, so the picker's badge updates with it.
    """
    forget(config.name)
    result = await _probe_now(config)
    _cache[config.name] = (time.monotonic() + PROBE_TTL_SECONDS, result)
    return result


async def survey(configs: dict[str, ProviderConfig]) -> dict[str, Availability]:
    """Availability for every configured provider, probing only where needed."""
    probes = {name: cfg for name, cfg in configs.items() if needs_probe(cfg)}
    results: dict[str, Availability] = {}

    for name in configs:
        if name not in probes:
            results[name] = cached(name) or Availability(
                name=name, available=True, source="observed"
            )

    if probes:
        answered = await asyncio.gather(
            *(probe(cfg) for cfg in probes.values()), return_exceptions=True
        )
        for name, value in zip(probes, answered, strict=True):
            results[name] = (
                value
                if isinstance(value, Availability)
                else Availability(name=name, available=False, reason=str(value))
            )
    return results
