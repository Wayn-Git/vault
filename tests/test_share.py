"""The share endpoint: one credential, one capability.

A token here lets a phone send PSOK a link. It must do that and nothing else,
and it must not exist at all until someone asks for it -- an endpoint that
answers 401 rather than 404 is an endpoint worth guessing at.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import share
from backend.api.main import app
from backend.library.store import LibraryStore


@pytest.fixture
def client(db):
    share._failures.clear()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def captures(monkeypatch):
    """Capture without the network, so these tests are about the gate."""
    logged: list[str] = []

    async def capture(self, url, **kwargs):
        from backend.library.service import Captured

        logged.append(url)
        return Captured({"id": len(logged), "title": url})

    monkeypatch.setattr("backend.library.service.LibraryService.capture_url", capture)
    return logged


def test_the_endpoint_does_not_exist_until_a_token_does(client, captures):
    """404, not 401. Off means absent.

    Mutation check: return 401 when no token is configured.
    """
    assert client.get("/api/share").json() == {"enabled": False}

    response = client.post("/api/share/capture", json={"url": "https://example.com/a"})
    assert response.status_code == 404
    assert captures == []


def test_a_wrong_token_captures_nothing(client, captures):
    client.post("/api/share/token")

    response = client.post(
        "/api/share/capture",
        json={"url": "https://example.com/a"},
        headers={"Authorization": "Bearer not-the-token"},
    )
    assert response.status_code == 401
    assert captures == []
    assert LibraryStore().list() == []


def test_a_missing_or_malformed_header_is_refused(client, captures):
    client.post("/api/share/token")

    for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"}):
        assert client.post(
            "/api/share/capture", json={"url": "https://example.com/a"}, headers=headers
        ).status_code == 401
    assert captures == []


def test_the_right_token_logs_the_link(client, captures):
    token = client.post("/api/share/token").json()["token"]

    response = client.post(
        "/api/share/capture",
        json={"url": "https://example.com/a"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    assert captures == ["https://example.com/a"]
    # Capture only: the response says what was logged and nothing about the
    # machine it was logged on.
    assert set(response.json()) == {"id", "title", "already_logged"}


def test_the_token_is_shown_once_and_never_read_back(client):
    """It goes to the keychain. Nothing hands it to a browser again -- rotating
    is the only way to get a value, and that is a new one.
    """
    first = client.post("/api/share/token").json()["token"]

    assert client.get("/api/share").json() == {"enabled": True}
    assert "token" not in client.get("/api/share").json()

    second = client.post("/api/share/token").json()["token"]
    assert second != first
    assert not share.check(first), "rotating must invalidate the old token"


def test_revoking_closes_the_door(client, captures):
    token = client.post("/api/share/token").json()["token"]
    client.delete("/api/share/token")

    response = client.post(
        "/api/share/capture",
        json={"url": "https://example.com/a"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert captures == []


def test_repeated_failures_stop_being_answered(client, captures):
    """A 256-bit token is not guessable, but an endpoint that answers a
    thousand times a second is still worth not offering.

    Mutation check: remove the failure window from `share.check`.
    """
    client.post("/api/share/token")
    for _ in range(share.MAX_FAILURES + 1):
        client.post(
            "/api/share/capture",
            json={"url": "https://example.com/a"},
            headers={"Authorization": "Bearer wrong"},
        )

    assert len(share._failures) >= share.MAX_FAILURES
    assert share.check("wrong") is False
    assert captures == []


def test_the_throttle_is_deliberately_fail_closed(client):
    """While the window is open, even the right token is refused.

    That is the trade, stated rather than discovered: one person's phone
    retrying with a stale token locks capture for five minutes, and the
    alternative -- letting the correct token through -- is an oracle telling an
    attacker which of their guesses was close.
    """
    token = client.post("/api/share/token").json()["token"]
    for _ in range(share.MAX_FAILURES):
        share.check("wrong")

    assert share.check(token) is False
