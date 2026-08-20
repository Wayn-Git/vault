from __future__ import annotations

import pytest

from psok.db import connection


@pytest.fixture(autouse=True)
def psok_home(tmp_path, monkeypatch):
    """Isolate every test in its own PSOK home so nothing touches the real one."""
    home = tmp_path / "psok-home"
    home.mkdir()
    monkeypatch.setenv("PSOK_HOME", str(home))
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
