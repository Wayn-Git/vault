"""Credential resolution. Secrets live in the OS keychain (ADR-0012).

Nothing in this module ever writes a secret value to the database, a config file
or a log line. Callers pass a reference ("psok/openai") and get a value back at
call time; the value is never cached on disk.

**The one exception is deliberate, opt-in, and named.** A container has no OS
keychain -- `keyring` raises `NoKeyringError` on the first write, which reached
the browser as an unexplained 500 when someone added a key to a deployed
instance. Setting `PSOK_SECRETS_FILE` to a path moves storage to that file,
owner-readable only. It is not encrypted and does not pretend to be: it is worth
exactly what the filesystem under it is worth, which on a single-tenant instance
with a private disk is the same thing the SQLite database is already worth.

Nothing falls back to it on its own. A silent downgrade from "the OS keychain"
to "a file" is the kind of thing that is true for a year before anybody notices,
so it happens only when the environment variable says to, and the error you get
without it names the variable.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

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


class _FileStore:
    """`PSOK_SECRETS_FILE`, for a host with no keychain to offer.

    Same three methods as `keyring`, so `_store()` can hand back either without
    the callers knowing which. Written 0600 and created 0600 -- not after the
    fact, or there is a window where the file exists and is world-readable.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict[str, str]:
        try:
            loaded = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _write(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Through a temporary file so a crash mid-write cannot leave a truncated
        # store behind -- that would read as "every key was deleted".
        scratch = self.path.with_name(f"{self.path.name}.tmp")
        handle = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "w") as out:
            json.dump(data, out)
        os.replace(scratch, self.path)

    def get_password(self, service: str, username: str) -> str | None:
        return self._read().get(f"{service}/{username}")

    def set_password(self, service: str, username: str, value: str) -> None:
        data = self._read()
        data[f"{service}/{username}"] = value
        self._write(data)

    def delete_password(self, service: str, username: str) -> None:
        data = self._read()
        if data.pop(f"{service}/{username}", None) is not None:
            self._write(data)


def _store():
    """Where secrets go. The OS keychain unless the environment says otherwise."""
    configured = os.environ.get("PSOK_SECRETS_FILE", "").strip()
    return _FileStore(Path(configured).expanduser()) if configured else _keyring()


#: What to tell someone whose host cannot store a key. The error `keyring` raises
#: is about installing a backend, which is the wrong advice on a container.
_NO_STORE = (
    "this host has no OS keychain, so there is nowhere to put the key."
    " Set PSOK_SECRETS_FILE to a path on a private disk (PSOK will keep keys"
    " there, readable only by this user), or give the provider its key through"
    " the environment variable named in providers.yaml."
)


def get_secret(ref: str) -> str | None:
    """Resolve a keychain reference like 'psok/openai' to its value."""
    service, _, username = ref.partition("/")
    if not username:
        service, username = SERVICE, ref
    try:
        return _store().get_password(service, username)
    except Exception:
        return None


def set_secret(ref: str, value: str) -> None:
    service, _, username = ref.partition("/")
    if not username:
        service, username = SERVICE, ref
    try:
        _store().set_password(service, username, value)
    except CredentialError:
        raise
    except Exception as exc:
        # `NoKeyringError` here used to escape as a 500 with a traceback, which
        # is how adding a key to a deployed instance failed without saying why.
        raise CredentialError(_NO_STORE) from exc


def delete_secret(ref: str) -> None:
    service, _, username = ref.partition("/")
    if not username:
        service, username = SERVICE, ref
    try:
        _store().delete_password(service, username)
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
