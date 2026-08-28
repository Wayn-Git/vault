"""Which provider answers when the chosen one cannot.

A turn used to end at the first provider failure: one `error` frame, the loop
returns, and whatever the user asked for is gone. That is the right behaviour
when the request is wrong and the wrong behaviour when the provider merely
happens to be down, which is most of the failures actually observed.

Three things this deliberately does *not* do:

* **It does not multiply the retry budget.** Four attempts per link across a
  chain of three is twelve attempts at a 120-second timeout, which is worse than
  failing. One budget is shared across the whole chain, and every remaining link
  is guaranteed at least one attempt out of it.
* **It does not fall back on a bad request.** A 404 for a model name means the
  same thing at the next provider, so the chain stops -- see
  `psok.runtime.failures`.
* **It does not fall back mid-answer.** Once deltas have reached the interface,
  a second provider would restart the answer under text the user is already
  reading. A failure after the first byte is a failure.

The order is providers.yaml's own order, which is the closest thing to a stated
preference that exists without inventing a setting. A `fallback:` key overrides
it for anyone who wants to be explicit:

    fallback:
      - groq
      - cerebras
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from psok.config import ProviderConfig, configured_providers, paths
from psok.runtime import availability
from psok.runtime.failures import FailureKind
from psok.runtime.http import MAX_RETRIES

#: How many providers may be tried after the chosen one. Two, because the
#: failure this exists for -- one provider down -- is fixed by the first
#: alternative, and a chain long enough to walk every configured provider spends
#: minutes proving the network is broken.
MAX_FALLBACK_LINKS = 2


@dataclass(frozen=True)
class Link:
    provider: str
    model: str

    def __str__(self) -> str:
        return f"{self.provider}/{self.model}"


class AttemptBudget:
    """One pool of attempts for the whole chain.

    `allowance` is what the current link may spend without starving the links
    behind it: every remaining one is reserved a single attempt, and the caller
    gets the rest. That is what keeps a three-provider chain bounded at the same
    order of wall clock as a one-provider turn rather than three times it.
    """

    def __init__(self, total: int = MAX_RETRIES + 1) -> None:
        self.total = max(1, total)
        self.spent = 0

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.spent)

    def allowance(self, links_after: int) -> int:
        """Attempts this link may make, leaving one for each link after it."""
        return max(1, self.remaining - max(0, links_after))

    def spend(self, attempts: int) -> None:
        self.spent += max(1, attempts)


def declared_order(path: Path | None = None) -> list[str] | None:
    """The user's `fallback:` list, if they wrote one."""
    p = path or paths().providers_yaml
    if not p.exists():
        return None
    raw = yaml.safe_load(p.read_text()) or {}
    order = raw.get("fallback")
    if not isinstance(order, list):
        return None
    names = [str(name) for name in order if name]
    return names or None


def _usable(name: str, config: ProviderConfig) -> bool:
    """Whether this provider is worth putting in a chain at all.

    A provider with no declared model cannot be substituted in without guessing
    a model name, and a guessed model name is the failure this whole phase
    exists to stop. A provider already known to be down is skipped for the same
    reason a picker stops offering it.
    """
    if not config.default_model:
        return False
    known = availability.cached(name)
    return known is None or known.available


def build_chain(
    provider: str,
    model: str,
    *,
    configs: dict[str, ProviderConfig] | None = None,
    order: list[str] | None = None,
    limit: int = MAX_FALLBACK_LINKS,
) -> list[Link]:
    """The chosen provider first, then the alternatives worth trying."""
    configured = configs if configs is not None else configured_providers()
    chain = [Link(provider=provider, model=model)]

    preferred = order if order is not None else declared_order()
    if preferred:
        candidates = [name for name in preferred if name in configured]
    else:
        candidates = list(configured)

    for name in candidates:
        if len(chain) > limit:
            break
        if name == provider:
            continue
        config = configured[name]
        if not _usable(name, config):
            continue
        chain.append(Link(provider=name, model=config.default_model or ""))
    return chain


def announcement(failed: Link, reason: str, using: Link) -> str:
    """One line, in the user's terms, saying what happened and what now.

    Decided with the user: visible, one line, no stack trace. The provider's own
    error body is already in the audit log; what belongs in the transcript is
    which provider answered, because that changes how the answer should be read.
    """
    return f"{failed.provider} {reason} — answering with {using} instead"


def reason_for(kind: FailureKind) -> str:
    """How a failure is described to the user, in five words or fewer.

    Deliberately not the provider's error body: that is a paragraph of JSON, it
    is already in the audit log, and the only thing the reader needs from it
    here is whether the answer they are about to get came from somewhere else.
    """
    return {
        FailureKind.UNREACHABLE: "was unreachable",
        FailureKind.UPSTREAM_UNHEALTHY: "returned a server error",
        FailureKind.RATE_LIMITED: "is rate limited",
        FailureKind.NON_RETRYABLE_RATE_LIMIT: "is out of quota",
        FailureKind.RETRYABLE: "failed",
    }.get(kind, "failed")
