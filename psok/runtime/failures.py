"""How a provider failed, as a value rather than a sentence.

Every provider failure used to be one `ProviderHTTPError` carrying a formatted
string, so nothing downstream could tell "retry this" from "wrong model name"
from "the key is dead". The one existing consumer resorted to
`if "unreachable" in str(exc)`, which is the shape of the problem: a caller that
needs to branch on a failure has to re-parse prose the raiser already knew the
structure of.

Two decisions come off a failure and they are not the same decision:

* **Retry** -- ask the *same* provider again. Worth doing when the failure is
  about this moment (a dropped connection, a 503, a rate limit that clears).
* **Fall back** -- ask a *different* provider. Worth doing whenever this
  provider cannot answer right now, including when it is out of credit: a
  billing problem is permanent for this provider and irrelevant to the next one.
  Not worth doing when the request itself is wrong, because the next provider
  will reject it too, only slower.

That second case is why a 404 stops the chain: a model name that does not exist
at provider A almost certainly does not exist at provider B either, and burning
the fallback on it turns one fast failure into several slow ones.
"""

from __future__ import annotations

from enum import StrEnum

# Substrings that mean "this account cannot pay for the request". They are worth
# separating from an ordinary 429 because the two look alike over HTTP -- both
# arrive as "too many requests" -- and only one of them clears by waiting.
# Retrying a billing failure spends the whole retry budget to learn nothing.
QUOTA_MARKERS = (
    "insufficient quota",
    "insufficient_quota",
    "exceeded your current quota",
    "out of credits",
    "credit balance is too low",
    "billing",
    "payment required",
    "quota exceeded",
    "spending limit",
)


class FailureKind(StrEnum):
    """Why a provider call failed, at the granularity callers actually branch on."""

    RETRYABLE = "retryable"
    """Transient and specific to this attempt: 408, 409, 425, a dropped socket."""

    RATE_LIMITED = "rate_limited"
    """429 that should clear on its own. Honours Retry-After."""

    NON_RETRYABLE_RATE_LIMIT = "non_retryable_rate_limit"
    """429/402 caused by exhausted quota or credit. Waiting will not fix it."""

    UPSTREAM_UNHEALTHY = "upstream_unhealthy"
    """5xx. The provider is up enough to answer and not well enough to serve."""

    UNREACHABLE = "unreachable"
    """Nothing answered: connection refused, DNS failure, timeout before bytes."""

    NON_RETRYABLE = "non_retryable"
    """The request is wrong: bad key, unknown model, malformed payload."""


#: Failures worth asking the same provider again.
RETRY_KINDS = frozenset(
    {
        FailureKind.RETRYABLE,
        FailureKind.RATE_LIMITED,
        FailureKind.UPSTREAM_UNHEALTHY,
        FailureKind.UNREACHABLE,
    }
)

#: Failures worth asking a different provider. Everything except "the request
#: itself is wrong" -- see the module docstring for why 404 stops here.
FALLBACK_KINDS = RETRY_KINDS | {FailureKind.NON_RETRYABLE_RATE_LIMIT}


def looks_like_quota(body: str | None) -> bool:
    return bool(body) and any(marker in body.lower() for marker in QUOTA_MARKERS)


def classify_status(status: int, body: str | None = None) -> FailureKind:
    """Map an HTTP status plus the provider's own error body to a failure kind.

    The body matters: a 429 is the only status that means two different things
    depending on what the provider wrote in it.
    """
    if status == 429:
        return (
            FailureKind.NON_RETRYABLE_RATE_LIMIT
            if looks_like_quota(body)
            else FailureKind.RATE_LIMITED
        )
    if status == 402:
        return FailureKind.NON_RETRYABLE_RATE_LIMIT
    if status >= 500:
        return FailureKind.UPSTREAM_UNHEALTHY
    if status in (408, 409, 425):
        return FailureKind.RETRYABLE
    if status >= 400:
        # A 403 sometimes carries a quota message rather than a permissions one.
        if looks_like_quota(body):
            return FailureKind.NON_RETRYABLE_RATE_LIMIT
        return FailureKind.NON_RETRYABLE
    return FailureKind.NON_RETRYABLE


# Error *frames* -- the ones that arrive inside an already-200 stream -- name
# themselves rather than carrying a status. Both wire formats use a small closed
# vocabulary, so the names map directly; anything unlisted is treated as a bad
# request, which is the conservative reading (it stops rather than retries).
STREAM_ERROR_KINDS: dict[str, FailureKind] = {
    "overloaded_error": FailureKind.UPSTREAM_UNHEALTHY,
    "api_error": FailureKind.UPSTREAM_UNHEALTHY,
    "server_error": FailureKind.UPSTREAM_UNHEALTHY,
    "internal_server_error": FailureKind.UPSTREAM_UNHEALTHY,
    "service_unavailable": FailureKind.UPSTREAM_UNHEALTHY,
    "rate_limit_error": FailureKind.RATE_LIMITED,
    "rate_limit_exceeded": FailureKind.RATE_LIMITED,
    "timeout": FailureKind.RETRYABLE,
    "insufficient_quota": FailureKind.NON_RETRYABLE_RATE_LIMIT,
    "context_length_exceeded": FailureKind.NON_RETRYABLE,
    "invalid_request_error": FailureKind.NON_RETRYABLE,
    "authentication_error": FailureKind.NON_RETRYABLE,
    "permission_error": FailureKind.NON_RETRYABLE,
    "not_found_error": FailureKind.NON_RETRYABLE,
}


def classify_stream_error(error: object) -> FailureKind:
    """Classify an error frame delivered inside a 200 stream."""
    if isinstance(error, dict):
        for key in ("type", "code"):
            name = error.get(key)
            if isinstance(name, str) and name in STREAM_ERROR_KINDS:
                return STREAM_ERROR_KINDS[name]
        status = error.get("status") or error.get("status_code")
        if isinstance(status, int):
            return classify_status(status, str(error.get("message") or ""))
    text = error if isinstance(error, str) else str(error)
    if looks_like_quota(text):
        return FailureKind.NON_RETRYABLE_RATE_LIMIT
    return FailureKind.NON_RETRYABLE


def should_retry(kind: FailureKind) -> bool:
    return kind in RETRY_KINDS


def should_fall_back(kind: FailureKind) -> bool:
    return kind in FALLBACK_KINDS
