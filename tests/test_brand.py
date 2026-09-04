"""The brand kit, and the one thing that makes it more than a settings page.

Storing a voice is worth nothing unless the model is told about it, so these
tests are mostly about `prompt_block`: when it is empty, when it is not, and
that what the API shows is exactly what the prompt injects.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import brand
from backend.agent.prompt import build_system_prompt
from backend.api.main import app


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c


def test_an_empty_profile_injects_nothing(db):
    """A <brand> of blank headings costs context on every turn and tells the
    model the user has no voice, which is worse than saying nothing at all.

    Mutation check: drop the `is_empty()` guard from `prompt_block`.
    """
    assert brand.prompt_block() == ""
    assert "<brand>" not in build_system_prompt()


def test_a_saved_voice_reaches_the_system_prompt(db):
    """The whole point. A voice stored and not injected is a stored voice.

    Mutation check: remove the brand block from `build_system_prompt`.
    """
    brand.save(brand.from_payload({"voice": "plain and dry", "dont": ["hype"]}))

    block = brand.prompt_block()
    assert "voice: plain and dry" in block
    assert "never: hype" in block
    assert block in build_system_prompt()


def test_switching_it_off_keeps_the_fields_and_drops_the_block(db):
    """Off means stored but not spent -- so the fields survive a round trip and
    the prompt gains nothing."""
    brand.save(brand.from_payload({"voice": "plain and dry", "enabled": False}))

    stored = brand.load()
    assert stored.voice == "plain and dry"
    assert brand.prompt_block() == ""


def test_a_broken_brand_profile_costs_the_voice_and_not_the_turn(db, monkeypatch):
    """Every optional block in the prompt is best-effort, and this is no
    different: a prompt that cannot be built is a turn that cannot happen.

    Mutation check: remove the try/except around the brand block.
    """
    def explode():
        raise RuntimeError("the table is gone")

    monkeypatch.setattr(brand, "prompt_block", explode)
    assert build_system_prompt()  # did not raise


def test_lists_accept_one_per_line_and_are_clamped(db):
    """The interface sends a textarea; a tool may send a list. Both arrive here,
    and neither may put a document in the system prompt."""
    saved = brand.save(
        brand.from_payload({"dont": "hype\n\n  exclamation marks  \n", "do": ["x"] * 50})
    )
    assert saved.dont == ("hype", "exclamation marks")
    assert len(saved.do) == brand.MAX_LIST_ITEMS


def test_the_api_shows_exactly_what_the_prompt_will_use(client):
    """`prompt_block` in the response is the literal text the model is handed.
    If the browser rendered its own preview instead, the two could disagree and
    nobody would find out.

    Mutation check: build `prompt_block` in the interface rather than here.
    """
    written = client.put(
        "/api/brand",
        json={"enabled": True, "voice": "dry", "palette": [{"name": "ink", "hex": "#0a0a0b"}]},
    )
    assert written.status_code == 200
    payload = written.json()

    assert payload["prompt_block"] == brand.prompt_block(brand.load())
    assert "palette: ink #0a0a0b" in payload["prompt_block"]
    assert client.get("/api/brand").json() == payload
