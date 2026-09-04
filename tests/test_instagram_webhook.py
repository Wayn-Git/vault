"""The webhook: what it accepts, what it refuses, and how fast it answers.

This endpoint is the one part of PSOK meant to be reachable from the internet,
and Meta will not send it a bearer token -- so the HMAC signature is the whole of
its authentication. Most of what is asserted here is about that.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.config import allow_sender, save_instagram
from backend.instagram import signature
from backend.instagram.store import InstagramEventStore

APP_SECRET = "an-app-secret"
VERIFY_TOKEN = "a-verify-token"
WEBHOOK = "/api/instagram/webhook"


def reel_body(*, mid: str = "m_abc", sender: str = "555", when: int | None = None) -> bytes:
    """One direct-message reel share, in the shape Meta actually sends."""
    import time

    return json.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "id": "17841400000000000",
                    "time": int(when if when is not None else time.time()),
                    "messaging": [
                        {
                            "sender": {"id": sender},
                            "recipient": {"id": "17841400000000000"},
                            "timestamp": int((when if when is not None else time.time()) * 1000),
                            "message": {
                                "mid": mid,
                                "attachments": [
                                    {
                                        "type": "ig_reel",
                                        "payload": {
                                            "title": "pour over ratios",
                                            "url": "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=1",
                                            "video_id": "9",
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()


def sign(raw: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def configured(db):
    """Credentials stored and capture switched on -- the working state."""
    signature._failures.clear()
    signature.set_credentials(
        app_secret=APP_SECRET, verify_token=VERIFY_TOKEN, access_token="an-access-token"
    )
    save_instagram({"enabled": True, "owner_ig_id": "17841400000000000"})
    allow_sender("555")


def test_the_webhook_does_not_exist_until_instagram_is_set_up(client):
    """404, not 401 or 403. An endpoint that answers differently when it is
    switched off is an endpoint worth probing for.

    Mutation check: raise 403 when unconfigured.
    """
    raw = reel_body()
    response = client.post(WEBHOOK, content=raw, headers={"x-hub-signature-256": sign(raw)})
    assert response.status_code == 404
    assert InstagramEventStore().recent() == []


def test_the_handshake_echoes_the_challenge_as_bare_text(client, configured):
    """Meta wants the challenge back, and only the challenge. Returning JSON --
    `"1158201444"`, with quotes -- is the commonest reason verification fails,
    and it fails with a message that does not say so.

    Mutation check: return the challenge as JSON.
    """
    response = client.get(
        WEBHOOK,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "1158201444",
        },
    )
    assert response.status_code == 200
    assert response.text == "1158201444"
    assert '"' not in response.text
    assert response.headers["content-type"].startswith("text/plain")


def test_a_wrong_verify_token_gets_nothing(client, configured):
    response = client.get(
        WEBHOOK,
        params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"},
    )
    assert response.status_code == 403


def test_an_unsigned_delivery_queues_nothing(client, configured):
    assert client.post(WEBHOOK, content=reel_body()).status_code == 403
    assert InstagramEventStore().recent() == []


def test_a_signature_over_different_bytes_is_refused(client, configured):
    """The test that pins raw-body verification.

    A parsed model re-serialised is not byte-identical to what Meta signed --
    key order, unicode escaping and float formatting all differ. This fails the
    moment somebody declares a Pydantic model as the route parameter, because
    FastAPI would then hand the handler a body it had already re-encoded.

    Mutation check: verify against `json.dumps(json.loads(raw))`.
    """
    raw = reel_body()
    reordered = json.dumps(json.loads(raw), sort_keys=True).encode()
    assert reordered != raw

    response = client.post(
        WEBHOOK, content=raw, headers={"x-hub-signature-256": sign(reordered)}
    )
    assert response.status_code == 403
    assert InstagramEventStore().recent() == []


def test_meta_retrying_a_delivery_records_it_once(client, configured):
    """Meta re-delivers anything it did not see a 200 for. Two deliveries of one
    reel must not become two rows, and the retry must still get a 200 so the
    retrying stops.

    Mutation check: drop the UNIQUE index on delivery_key.
    """
    raw = reel_body()
    headers = {"x-hub-signature-256": sign(raw)}

    first = client.post(WEBHOOK, content=raw, headers=headers)
    second = client.post(WEBHOOK, content=raw, headers=headers)

    assert first.status_code == 200 and first.json()["events"] == 1
    assert second.status_code == 200 and second.json()["events"] == 0
    assert len(InstagramEventStore().recent()) == 1


def test_a_body_that_cannot_be_read_is_answered_with_200(client, configured):
    """A body Meta signed and PSOK cannot parse will not parse next time either.
    A 4xx here makes Meta retry it for hours.

    Mutation check: raise 400 on a ValidationError.
    """
    raw = b'{"object": "instagram", "entry": "not a list"}'
    response = client.post(WEBHOOK, content=raw, headers={"x-hub-signature-256": sign(raw)})
    assert response.status_code == 200
    assert response.json()["status"] == "unreadable"


def test_a_body_over_the_cap_is_refused(client, configured):
    raw = b'{"object":"instagram","entry":[]}' + b" " * (signature.MAX_BODY_BYTES + 10)
    response = client.post(WEBHOOK, content=raw, headers={"x-hub-signature-256": sign(raw)})
    assert response.status_code == 413


def test_a_stale_delivery_is_not_acted_on(client, configured):
    """A captured body resent a week later is a replay. The unique key is the
    real control; this is the belt to its braces."""
    raw = reel_body(when=1)
    response = client.post(WEBHOOK, content=raw, headers={"x-hub-signature-256": sign(raw)})
    assert response.status_code == 200
    assert response.json()["events"] == 0
    assert InstagramEventStore().recent() == []


def test_the_delivery_is_written_down_before_anything_slow_happens(client, configured, monkeypatch):
    """Meta wants a 200 in seconds, so the acknowledgement means "written down"
    and never "done". Ingest exploding must not reach the response.

    Mutation check: process the event inline in the route.
    """
    async def explode(self, event):
        raise AssertionError("no work belongs on the webhook's own request")

    monkeypatch.setattr("backend.instagram.service.IngestService.process", explode)

    raw = reel_body()
    response = client.post(WEBHOOK, content=raw, headers={"x-hub-signature-256": sign(raw)})

    assert response.status_code == 200
    assert InstagramEventStore().recent()[0]["status"] == "queued"


def test_repeated_bad_signatures_stop_being_answered(client, configured):
    """A 256-bit secret is not guessable, but an endpoint that answers a thousand
    times a second is still worth not offering.

    Mutation check: remove the failure window from verify_signature.
    """
    raw = reel_body()
    for _ in range(signature.MAX_FAILURES + 1):
        client.post(WEBHOOK, content=raw, headers={"x-hub-signature-256": sign(raw, "wrong")})

    # Even a correct signature is refused while the window is open. Deliberate:
    # letting it through would be an oracle telling an attacker they were close.
    assert client.post(
        WEBHOOK, content=raw, headers={"x-hub-signature-256": sign(raw)}
    ).status_code == 403


def test_capture_cannot_be_switched_on_without_credentials(client, db):
    response = client.patch("/api/instagram/settings", json={"enabled": True})
    assert response.status_code == 400
    assert "app secret" in response.json()["detail"]


def test_the_status_never_returns_a_credential(client, configured):
    body = client.get("/api/instagram").json()
    assert body["credentials"] == {
        "app_secret": True,
        "verify_token": True,
        "access_token": True,
    }
    assert APP_SECRET not in json.dumps(body)
    assert VERIFY_TOKEN not in json.dumps(body)


def test_an_event_listing_does_not_hand_out_the_raw_payload(client, configured):
    """The payload is kept for reprocessing and carries whatever Instagram sent."""
    raw = reel_body()
    client.post(WEBHOOK, content=raw, headers={"x-hub-signature-256": sign(raw)})

    rows = client.get("/api/instagram/events").json()
    assert rows and "payload" not in rows[0]
