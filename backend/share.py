"""The share token: one credential, for one capture-only endpoint.

`POST /api/share/capture` exists so a phone can send PSOK a link. Everything
about it is narrowed deliberately, because the rest of this API has no
authentication at all and is not meant to (ADR-0001):

* It can create a library item from a URL. It cannot read, list, delete, run a
  tool, or reach anything else.
* It does not exist until a token is generated. With no token the route answers
  404, exactly as an unknown path does -- an endpoint that announces itself with
  a 401 is an endpoint worth guessing at.
* The token lives in the OS keychain like every other secret here, never in the
  config file and never in the database.
* Comparison is constant time, and repeated failures from one address are
  slowed down.

**A token here does not make a public deployment safe.** Every other `/api`
route stays unauthenticated. Exposing PSOK to the internet means putting a proxy
in front of it that publishes this one path and nothing else; see
`docs/deployment.md`. `psok doctor` says so when the server is bound to an
address that is not loopback.
"""

from __future__ import annotations

import hmac
import logging
import secrets as stdlib_secrets
import time

from backend.secrets import SERVICE, delete_secret, get_secret, set_secret

log = logging.getLogger(__name__)

REF = f"{SERVICE}/share-token"
TOKEN_BYTES = 32

#: Failed attempts allowed inside the window before the endpoint stops
#: answering. Generous for a typo, useless for guessing a 256-bit token.
MAX_FAILURES = 10
FAILURE_WINDOW_SECONDS = 300.0

_failures: list[float] = []


def current() -> str | None:
    """The stored token, or None because sharing has never been switched on."""
    try:
        return get_secret(REF)
    except Exception as exc:  # a container with no keychain, and no file store
        log.warning("share token unavailable: %s", exc)
        return None


def enabled() -> bool:
    return bool(current())


def rotate() -> str:
    """Generate a new token, replacing any existing one. Returns it once."""
    token = stdlib_secrets.token_urlsafe(TOKEN_BYTES)
    set_secret(REF, token)
    _failures.clear()
    return token


def revoke() -> None:
    delete_secret(REF)
    _failures.clear()


def _throttled(now: float) -> bool:
    while _failures and now - _failures[0] > FAILURE_WINDOW_SECONDS:
        _failures.pop(0)
    return len(_failures) >= MAX_FAILURES


def check(presented: str | None) -> bool:
    """True when this token is the stored one. Constant time, and rate limited."""
    token = current()
    if not token:
        return False
    now = time.monotonic()
    if _throttled(now):
        log.warning("share capture refused: too many failed tokens")
        return False
    ok = bool(presented) and hmac.compare_digest(presented or "", token)
    if not ok:
        _failures.append(now)
        log.warning("share capture refused: token did not match")
    return ok


def bearer(header: str | None) -> str | None:
    """The token out of an Authorization header, if it is a bearer one."""
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None
