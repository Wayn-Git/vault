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
  provider cannot answer right now.

**Nearly everything falls back**, including a 404, a bad key, and a malformed
request. This was not always true here: an earlier version of this module kept
a plain "the request is wrong" 4xx (`NON_RETRYABLE`) out of `FALLBACK_KINDS`,
reasoning that "a model name that does not exist at provider A almost certainly
does not exist at provider B either." That reasoning does not hold against what
`backend.runtime.chain.build_chain` actually does: every fallback link carries
*that provider's own configured `default_model`*, never the model string that
just failed. So a dead model id, a revoked key, or a malformed field on
provider A says nothing about provider B, because B is never asked about A's
model, A's key, or A's field -- it is asked about its own. Measured live: NVIDIA
retired a model id mid-session (`410 Gone ... reached its end of life`), which
is exactly a 4xx that has nothing to do with any other provider, and the old
policy let it kill the whole turn while two perfectly healthy providers sat
unused in the same chain.

The one thing that still does not repeat across providers is a *bodyless* 404 --
NVIDIA's NIM gateway returns one when the node has not loaded the model yet,
which a retry against the *same* provider fixes; see `classify_status`.
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

#: Failures worth asking a different provider. Every kind, including
#: NON_RETRYABLE -- see the module docstring for why a dead model id or a bad
#: key at provider A says nothing about provider B once `build_chain` is read
#: correctly: a fallback link is never asked to retry A's model or A's key, it
#: is asked about its own. The remaining bound on cost is `AttemptBudget` and
#: `MAX_FALLBACK_LINKS` (backend/runtime/chain.py), not this set -- a request
#: that really is wrong everywhere still only costs two extra fast round trips
#: before the turn gives up, not an unbounded retry storm.
FALLBACK_KINDS = RETRY_KINDS | {
    FailureKind.NON_RETRYABLE_RATE_LIMIT,
    FailureKind.NON_RETRYABLE,
}


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
    if status in (402, 413):
        # 413 here is not "the request is malformed" -- it is Groq's shape for
        # "this request alone exceeds the account's tokens-per-minute ceiling",
        # which retrying the same provider cannot fix (the request does not get
        # smaller) but a different provider very well might answer. This used to
        # fall through to the generic `>= 400` branch below and only became
        # fallback-worthy because Groq's error body happens to contain the word
        # "billing" in a promotional URL -- explicit here so it does not silently
        # become NON_RETRYABLE (no fallback at all) the day that copy changes.
        return FailureKind.NON_RETRYABLE_RATE_LIMIT
    if status >= 500:
        return FailureKind.UPSTREAM_UNHEALTHY
    if status in (408, 409, 425):
        return FailureKind.RETRYABLE
    if status == 404 and not (body and body.strip()):
        # A *bodyless* 404. NVIDIA's NIM gateway returns this when the node a
        # request landed on has not loaded the model yet -- transient and
        # per-request, so retrying lands on a warm node and succeeds (measured
        # ~50% bodyless-404 on nemotron, cleared by one retry). A genuine
        # "model not found" is a different 404: it carries a JSON error body
        # naming the model, matches the `>= 400` branch below, and stays fatal
        # -- so this does not reopen the "burn the fallback on a bad model name"
        # problem the module docstring describes. Only the empty-bodied,
        # information-free 404 is treated as a blip.
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
    # An error frame arriving *inside* a 200 stream is a different animal from a
    # 4xx at the door: the request already passed auth, routing and validation
    # to open the stream, so a break part-way through is almost always the
    # provider faltering mid-generation, not a malformed request. NVIDIA's NIM
    # emits bare `Error in input stream` frames this way, ~intermittently, and
    # the old default (NON_RETRYABLE) turned each into a dead turn with no
    # retry. Treat an unrecognised mid-stream error as transient so the same
    # provider is asked again -- the conservative reading costs a dead turn,
    # this costs at worst one wasted retry.
    return FailureKind.UPSTREAM_UNHEALTHY


def should_retry(kind: FailureKind) -> bool:
    return kind in RETRY_KINDS


def should_fall_back(kind: FailureKind) -> bool:
    return kind in FALLBACK_KINDS
