"""Credential resolution. Secrets live in the OS keychain only (ADR-0012).

Nothing in this module ever writes a secret value to the database, a config file
or a log line. Callers pass a reference ("psok/openai") and get a value back at
call time; the value is never cached on disk.
"""

from __future__ import annotations

import os
import re

SERVICE = "psok"

# Redaction for the audit log. Any argument or result field whose *name* matches
# looks credential-shaped, plus value patterns for tokens that leak by accident.
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|authorization|bearer|credential|cookie)",
    re.IGNORECASE,
)
_SECRET_VALUE_RES = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bey[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}", re.IGNORECASE),
]

REDACTED = "[redacted]"


class CredentialError(RuntimeError):
    pass


def _keyring():
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise CredentialError("keyring is not installed; cannot resolve credentials") from exc
    return keyring


def get_secret(ref: str) -> str | None:
    """Resolve a keychain reference like 'psok/openai' to its value."""
    service, _, username = ref.partition("/")
    if not username:
        service, username = SERVICE, ref
    try:
        return _keyring().get_password(service, username)
    except Exception:
        return None


def set_secret(ref: str, value: str) -> None:
    service, _, username = ref.partition("/")
    if not username:
        service, username = SERVICE, ref
    _keyring().set_password(service, username, value)


def delete_secret(ref: str) -> None:
    service, _, username = ref.partition("/")
    if not username:
        service, username = SERVICE, ref
    try:
        _keyring().delete_password(service, username)
    except Exception:
        pass


def resolve_api_key(*, ref: str | None = None, env: str | None = None) -> str | None:
    """Resolve a provider key: keychain reference first, env var as fallback."""
    if ref:
        value = get_secret(ref)
        if value:
            return value
    if env:
        return os.environ.get(env)
    return None


def redact(value):
    """Deep-redact credential-shaped data before it reaches the audit log."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _SECRET_KEY_RE.search(str(k)):
                # Redact the leaf, but keep walking containers: a key like
                # "authorization_notes" holding a dict is structure worth
                # auditing, and blanking it loses the record for no gain.
                out[k] = REDACTED if not isinstance(v, (dict, list, tuple)) else redact(v)
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for pattern in _SECRET_VALUE_RES:
            value = pattern.sub(REDACTED, value)
        return value
    return value
