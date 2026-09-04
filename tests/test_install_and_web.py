"""Installing skills, reading the web, and taking a file from the browser.

These are the three things the interface could not do before: it could list
skills but not add one, reach the web only through a connector, and accept a
file only as a path the user typed from memory.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.skills.install import SkillInstallError, install_text, remove, to_raw_url
from backend.skills.loader import scan

pytestmark = pytest.mark.usefixtures("psok_home")

SKILL = """---
name: note-taker
description: Take notes the way the user likes them.
version: 1.0.0
---

# Note taker

Write it down.
"""


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ skills


def test_a_skill_installs_under_the_name_it_declares(psok_home):
    skill = install_text(SKILL)
    assert skill.name == "note-taker"
    assert skill.path == psok_home / "skills" / "note-taker" / "SKILL.md"
    assert [s.name for s in scan()[0]] == ["note-taker"]


def test_a_file_that_is_not_a_skill_leaves_nothing_behind(psok_home):
    """Staged and parsed before it is placed: a download that turns out not to
    be a skill must not leave a directory the loader can only report as broken."""
    with pytest.raises(SkillInstallError):
        install_text("# just a readme\n")
    assert not (psok_home / "skills").exists() or list((psok_home / "skills").iterdir()) == []


def test_installing_over_a_working_skill_needs_saying_so(psok_home):
    install_text(SKILL)
    with pytest.raises(SkillInstallError, match="already installed"):
        install_text(SKILL.replace("Take notes", "Take different notes"))

    install_text(SKILL.replace("Take notes", "Take different notes"), overwrite=True)
    assert "different" in scan()[0][0].description


def test_a_github_page_url_is_rewritten_to_the_raw_file():
    """What a person copies out of the address bar is the HTML page, which is
    not the skill."""
    assert to_raw_url("https://github.com/o/r/blob/main/skills/x/SKILL.md") == (
        "https://raw.githubusercontent.com/o/r/main/skills/x/SKILL.md"
    )
    # Anything else is passed through untouched.
    assert to_raw_url("https://example.com/SKILL.md") == "https://example.com/SKILL.md"


def test_removing_refuses_anything_that_is_not_a_plain_name(psok_home):
    """The name arrives from an HTTP path; `../` would be a delete anywhere."""
    install_text(SKILL)
    with pytest.raises(SkillInstallError):
        remove("../../etc")
    assert (psok_home / "skills" / "note-taker").is_dir()

    assert remove("note-taker") is True
    assert not (psok_home / "skills" / "note-taker").exists()


def test_installing_from_a_url_that_resolves_locally_is_refused(client):
    """The SSRF guard the MCP transports use applies here too: a URL is a URL."""
    response = client.post("/api/skills/install", json={"url": "http://127.0.0.1:8000/SKILL.md"})
    assert response.status_code == 400
    assert "private" in response.json()["detail"] or "loopback" in response.json()["detail"]


def test_removing_a_skill_over_http(client, psok_home):
    install_text(SKILL)
    assert client.delete("/api/skills/note-taker").status_code == 200
    assert client.delete("/api/skills/note-taker").status_code == 404


# ------------------------------------------------------------- attachments


def test_a_dropped_file_becomes_a_path_the_tools_can_read(client, psok_home):
    """The browser has no idea where a file is on disk and PSOK's tools work on
    paths, so the file is written into the PSOK home and the path comes back."""
    response = client.post(
        "/api/attachments",
        files={"file": ("notes.txt", b"remember the milk", "text/plain")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "notes.txt"
    from pathlib import Path

    landed = Path(body["path"])
    assert landed.read_text() == "remember the milk"
    assert landed.is_relative_to(psok_home / "attachments")


def test_an_upload_cannot_escape_the_attachments_directory(client, psok_home):
    response = client.post(
        "/api/attachments",
        files={"file": ("../../evil.sh", b"rm -rf /", "text/plain")},
    )
    assert response.status_code == 200
    from pathlib import Path

    landed = Path(response.json()["path"])
    assert landed.name == "evil.sh"
    # Resolved, not lexical: `.../attachments/<id>/../../evil.sh` starts with
    # the attachments directory as a string while pointing outside it.
    assert landed.resolve().is_relative_to((psok_home / "attachments").resolve())
    assert landed.resolve().read_bytes() == b"rm -rf /"


def test_an_oversized_upload_is_rejected_and_not_kept(client, psok_home, monkeypatch):
    monkeypatch.setattr("backend.api.main.MAX_ATTACHMENT_BYTES", 16)
    response = client.post(
        "/api/attachments",
        files={"file": ("big.bin", b"x" * 1024, "application/octet-stream")},
    )
    assert response.status_code == 413
    assert list((psok_home / "attachments").iterdir()) == []


# ------------------------------------------------------------------- tools


def test_the_tool_list_names_its_sources(client):
    rows = client.get("/api/tools").json()
    names = {row["name"] for row in rows}
    assert {"run_shell_command", "search_web", "fetch_url"} <= names
    assert all(row["source"] == "builtin" for row in rows)


async def test_search_results_are_parsed_out_of_the_result_page(monkeypatch):
    """The endpoint returns HTML, not JSON, so the parsing is the contract --
    and it has to fail loudly rather than returning an empty list."""
    import httpx

    from backend.tools.base import ToolContext
    from backend.tools.builtin.web import search_web

    page = """
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">
        First <b>hit</b>
      </a>
      <a class="result__snippet">A snippet about it</a>
    </div>
    """

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, headers=None):
            return httpx.Response(200, text=page, request=httpx.Request("GET", url))

    monkeypatch.setattr("backend.tools.builtin.web.httpx.AsyncClient", lambda **kw: FakeClient())

    result = await search_web({"query": "anything"}, ToolContext())
    assert not result.is_error
    assert "First hit" in result.content
    assert "https://example.com/a" in result.content
    assert "duckduckgo.com/l/" not in result.content


async def test_fetching_a_private_address_is_refused():
    from backend.tools.base import ToolContext
    from backend.tools.builtin.web import fetch_url

    result = await fetch_url({"url": "http://169.254.169.254/latest/meta-data/"}, ToolContext())
    assert result.is_error


# ------------------------------------------------------------------- tasks


def test_tasks_created_by_the_agent_are_readable_without_a_model_call(client, db):
    from backend.db.repositories import TaskRepository

    TaskRepository().create("Study system design in LLMs", priority="medium")
    rows = client.get("/api/tasks").json()
    assert [row["title"] for row in rows] == ["Study system design in LLMs"]


# ------------------------------------------------------------ the directory


async def test_the_catalogue_reads_names_and_descriptions_from_the_real_files(monkeypatch):
    """Cards carry the name and description out of each SKILL.md rather than a
    hand-written title, which would drift the moment the source changed."""
    import httpx

    from backend.skills import catalogue as cat

    tree = {"tree": [{"path": "skills/note-taker/SKILL.md"}, {"path": "README.md"}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, headers=None):
            request = httpx.Request("GET", url)
            if "api.github.com" in url:
                return httpx.Response(200, json=tree, request=request)
            return httpx.Response(200, text=SKILL, request=request)

    monkeypatch.setattr(cat, "_cache", {})
    monkeypatch.setattr(cat.httpx, "AsyncClient", lambda **kw: FakeClient())

    result = await cat.fetch(force=True)
    assert result.error is None
    assert [(s.name, s.publisher) for s in result.skills] == [("note-taker", "Anthropic")]
    assert result.skills[0].description.startswith("Take notes")
    assert result.skills[0].url.endswith("skills/note-taker/SKILL.md")


async def test_a_source_that_cannot_be_read_says_so_rather_than_inventing_one(monkeypatch):
    import httpx

    from backend.skills import catalogue as cat

    class Broken:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, headers=None):
            raise httpx.ConnectError("no network")

    monkeypatch.setattr(cat, "_cache", {})
    monkeypatch.setattr(cat.httpx, "AsyncClient", lambda **kw: Broken())

    result = await cat.fetch(force=True)
    assert result.skills == []
    assert "ConnectError" in (result.error or "")


def test_the_catalogue_endpoint_marks_what_is_already_installed(client, monkeypatch):
    from backend.skills import catalogue as cat

    entry = cat.CatalogueSkill(
        id="anthropic/note-taker",
        name="note-taker",
        description="Take notes.",
        publisher="Anthropic",
        source="anthropic",
        url="https://example.com/SKILL.md",
        path="skills/note-taker/SKILL.md",
    )

    async def fake_fetch(*, force=False):
        return cat.Catalogue(skills=[entry])

    monkeypatch.setattr("backend.skills.catalogue.fetch", fake_fetch)

    assert client.get("/api/skills/catalogue").json()["skills"][0]["installed"] is False
    install_text(SKILL)
    assert client.get("/api/skills/catalogue").json()["skills"][0]["installed"] is True
