from __future__ import annotations

import pytest

from psok.db import connection


class _MemoryKeyring:
    """A keyring that lives and dies with one test.

    Isolating PSOK_HOME alone left every credential path pointed at the
    developer's real OS keychain: a test asserting a connector was not signed
    in passed or failed depending on whether the person running it happened to
    have signed into that connector, and a test that stored a secret wrote it
    into their login keyring for good. Both are fixed by never reaching the
    real backend from a test.
    """

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, value: str) -> None:
        self.store[(service, username)] = value

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)


@pytest.fixture(autouse=True)
def psok_home(tmp_path, monkeypatch):
    """Isolate every test in its own PSOK home so nothing touches the real one."""
    home = tmp_path / "psok-home"
    home.mkdir()
    monkeypatch.setenv("PSOK_HOME", str(home))

    from psok import secrets

    # One backend for the whole test: a fresh instance per call would lose
    # every secret between the set and the get.
    keyring = _MemoryKeyring()
    monkeypatch.setattr(secrets, "_keyring", lambda: keyring)
    connection.reset_connection()
    yield home
    connection.reset_connection()


@pytest.fixture
def db(psok_home):
    return connection.get_connection()


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    return root
