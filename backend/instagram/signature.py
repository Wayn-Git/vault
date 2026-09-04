"""Credentials for the Instagram webhook, and the two checks that guard it.

`backend/share.py` is the precedent and the rules are the same, for the same
reasons -- but the credential is not. Meta will not send a bearer token, so this
endpoint's authentication *is* the HMAC signature Meta puts on every delivery.
That is the whole of it: a body that verifies came from something holding the
app secret, and a body that does not is discarded before it is parsed.

Three secrets, all in the OS keychain, all write-only from the interface:

* **the app secret** signs deliveries and keys `appsecret_proof`
* **the verify token** is echoed back during the one-time handshake
* **the access token** is what calls the Graph API afterwards

Without all three the route does not exist -- 404, exactly as an unknown path
answers, because an endpoint that says 401 is an endpoint worth guessing at.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from backend.secrets import SERVICE, delete_secret, get_secret, set_secret

log = logging.getLogger(__name__)

APP_SECRET_REF = f"{SERVICE}/instagram-app-secret"
VERIFY_TOKEN_REF = f"{SERVICE}/instagram-verify-token"
ACCESS_TOKEN_REF = f"{SERVICE}/instagram-access-token"

#: Meta's deliveries are a few kilobytes. A quarter of a megabyte is far above
#: any real batch and far below anything worth reading into memory unchecked.
MAX_BODY_BYTES = 256 * 1024

#: How old an entry may be before it is treated as a replay. Defence in depth --
#: the unique delivery key is the real control -- but a captured body resent a
#: week later should not be acted on at all.
MAX_SKEW_SECONDS = 900

#: Signature failures tolerated in a window. Generous for a mistyped secret,
#: useless against anything else.
MAX_FAILURES = 10
FAILURE_WINDOW_SECONDS = 300.0

_failures: list[float] = []


def _secret(ref: str) -> str | None:
    try:
        return get_secret(ref)
    except Exception as exc:  # a container with no keychain and no file store
        log.warning("instagram credential unavailable: %s", exc)
        return None


def app_secret() -> str | None:
    return _secret(APP_SECRET_REF)


def verify_token() -> str | None:
    return _secret(VERIFY_TOKEN_REF)


def access_token() -> str | None:
    return _secret(ACCESS_TOKEN_REF)


def present() -> dict[str, bool]:
    """Which credentials are set. Never their values -- this reaches a browser."""
    return {
        "app_secret": bool(app_secret()),
        "verify_token": bool(verify_token()),
        "access_token": bool(access_token()),
    }


def configured() -> bool:
    """All three, because any two of them cannot complete a single delivery."""
    return all(present().values())


def set_credentials(
    *,
    app_secret: str | None = None,
    verify_token: str | None = None,
    access_token: str | None = None,
) -> None:
    """Store whatever was given. Omitted values are left alone, not cleared."""
    for ref, value in (
        (APP_SECRET_REF, app_secret),
        (VERIFY_TOKEN_REF, verify_token),
        (ACCESS_TOKEN_REF, access_token),
    ):
        if value is not None and value.strip():
            set_secret(ref, value.strip())
    _failures.clear()


def revoke() -> None:
    for ref in (APP_SECRET_REF, VERIFY_TOKEN_REF, ACCESS_TOKEN_REF):
        try:
            delete_secret(ref)
        except Exception as exc:
            log.warning("could not delete %s: %s", ref, exc)
    _failures.clear()


def verify_challenge(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    """The one-time handshake. Returns the challenge to echo, or None.

    The GET carries no signature -- only POSTs are signed -- so the verify token
    is the whole check here, and it is compared in constant time like any other
    shared secret.
    """
    stored = verify_token()
    if not stored or mode != "subscribe" or not challenge:
        return None
    if not hmac.compare_digest(token or "", stored):
        log.warning("instagram handshake refused: verify token did not match")
        return None
    return challenge


def _throttled(now: float) -> bool:
    while _failures and now - _failures[0] > FAILURE_WINDOW_SECONDS:
        _failures.pop(0)
    return len(_failures) >= MAX_FAILURES


def verify_signature(header: str | None, raw: bytes) -> bool:
    """Whether these exact bytes were signed with the app secret.

    `raw` has to be the body as it arrived. Re-serialising a parsed model is not
    byte-identical -- key order, unicode escaping and float formatting all differ
    -- so a signature computed over anything but the original bytes is a check
    that passes when it should fail and fails when it should pass.
    """
    secret = app_secret()
    if not secret:
        return False
    now = time.monotonic()
    if _throttled(now):
        log.warning("instagram webhook refused: too many bad signatures")
        return False

    scheme, _, digest = (header or "").partition("=")
    if scheme.strip().lower() != "sha256" or not digest:
        _failures.append(now)
        return False

    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    if hmac.compare_digest(digest.strip(), expected):
        return True
    _failures.append(now)
    log.warning("instagram webhook refused: signature did not match")
    return False


def appsecret_proof(token: str) -> str | None:
    """Graph's proof-of-secret, so a stolen access token alone is not enough."""
    secret = app_secret()
    if not secret:
        return None
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def is_stale(entry_time: int | None, *, now: float | None = None) -> bool:
    """Whether this entry is too old to act on. Missing times are accepted."""
    if not entry_time:
        return False
    return abs((now or time.time()) - entry_time) > MAX_SKEW_SECONDS
