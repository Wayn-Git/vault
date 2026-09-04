"""The HTTP surface the browser talks to: static serving and connector setup.

Both are paths a person walks through rather than functions the agent calls, so
they are tested here as requests rather than as units.
"""

from __future__ import annotations

import pytest
from conftest import GOOGLE_SECRET
from fastapi.testclient import TestClient

from backend.api.main import _DIST, app
from backend.mcp import commands as mcp
from backend.mcp.config import KEYCHAIN_PREFIX, config_path, load_servers
from backend.secrets import get_secret

pytestmark = pytest.mark.usefixtures("psok_home")


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def stdio_server():
    """A stdio server to configure, added the way the interface adds one."""
    return mcp.add_custom(name="envtest", transport="stdio", command="true", args=[])


# --------------------------------------------------------------- single page


needs_build = pytest.mark.skipif(
    not (_DIST / "index.html").is_file(),
    reason="frontend/dist is only present once `npm run build` has run",
)


@needs_build
def test_the_built_interface_is_served_by_the_api(client):
    """One process is the whole product: `psok serve` and open a browser."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<div id=\"root\">" in response.text


@needs_build
def test_a_deep_link_returns_the_single_page_rather_than_a_404(client):
    assert client.get("/anything/the/router/owns").status_code == 200


@needs_build
def test_an_unknown_api_path_is_a_json_404_not_the_single_page(client):
    """The catch-all sits below every route, so a mistyped endpoint would
    otherwise return HTML with a 200 and surface as a JSON parse error in the
    interface -- pointing at the wrong thing entirely."""
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"].startswith("no such endpoint")


# ------------------------------------------------- connector environment vars


def test_a_secret_environment_variable_is_stored_outside_mcp_yaml(client, stdio_server):
    """Google Workspace takes its OAuth client through the environment. The
    value belongs in the keychain; mcp.yaml gets a reference (ADR-0012)."""
    response = client.post(
        "/api/mcp/servers/envtest/env",
        json={"key": "GOOGLE_OAUTH_CLIENT_SECRET", "value": GOOGLE_SECRET, "secret": True},
    )
    assert response.status_code == 200
    assert response.json()["stored"] == "keychain"

    stored = load_servers()["envtest"].env["GOOGLE_OAUTH_CLIENT_SECRET"]
    assert stored.startswith(KEYCHAIN_PREFIX)
    assert GOOGLE_SECRET not in config_path().read_text()
    assert get_secret(stored[len(KEYCHAIN_PREFIX):]) == GOOGLE_SECRET


def test_a_plain_environment_variable_is_written_to_mcp_yaml(client, stdio_server):
    client.post(
        "/api/mcp/servers/envtest/env",
        json={"key": "WORKSPACE_MCP_PORT", "value": "8765", "secret": False},
    )
    assert load_servers()["envtest"].env["WORKSPACE_MCP_PORT"] == "8765"


def test_the_server_list_names_variables_but_never_returns_their_values(client, stdio_server):
    client.post(
        "/api/mcp/servers/envtest/env",
        json={"key": "GOOGLE_OAUTH_CLIENT_SECRET", "value": GOOGLE_SECRET, "secret": True},
    )
    row = next(s for s in client.get("/api/mcp/servers").json() if s["name"] == "envtest")
    assert row["env"] == {"GOOGLE_OAUTH_CLIENT_SECRET": True}
    assert GOOGLE_SECRET not in client.get("/api/mcp/servers").text


def test_unsetting_forgets_the_variable_and_its_keychain_entry(client, stdio_server):
    client.post(
        "/api/mcp/servers/envtest/env",
        json={"key": "GOOGLE_OAUTH_CLIENT_SECRET", "value": GOOGLE_SECRET, "secret": True},
    )
    ref = load_servers()["envtest"].env["GOOGLE_OAUTH_CLIENT_SECRET"][len(KEYCHAIN_PREFIX):]

    path = "/api/mcp/servers/envtest/env/GOOGLE_OAUTH_CLIENT_SECRET"
    assert client.delete(path).status_code == 200
    assert "GOOGLE_OAUTH_CLIENT_SECRET" not in load_servers()["envtest"].env
    assert get_secret(ref) is None

    # Removing what is not there is a 404, not a silent success.
    assert client.delete(path).status_code == 404


def test_a_bogus_variable_name_is_rejected(client, stdio_server):
    """The name goes into a YAML mapping and then into a subprocess environment,
    so it has to look like one."""
    response = client.post(
        "/api/mcp/servers/envtest/env",
        json={"key": "not a var name", "value": "x", "secret": False},
    )
    assert response.status_code == 400
    assert load_servers()["envtest"].env == {}


def test_configuring_an_unknown_server_is_a_404(client):
    response = client.post(
        "/api/mcp/servers/nosuch/env",
        json={"key": "A", "value": "b", "secret": False},
    )
    assert response.status_code == 404


# ------------------------------------------------------- standing approvals


def test_standing_approvals_can_be_read_back_and_revoked(client):
    """"Don't ask again" is a grant. A grant nobody can list is one nobody can
    notice, and one nobody can take back."""
    from backend.db.repositories import ConfirmationPreferenceRepository

    repo = ConfirmationPreferenceRepository()
    repo.remember("run_shell_command:read-only", "allow", "high")

    listed = client.get("/api/confirmations/preferences").json()
    assert [row["operation_key"] for row in listed] == ["run_shell_command:read-only"]
    assert listed[0]["decision"] == "allow"

    revoke = "/api/confirmations/preferences/run_shell_command:read-only"
    assert client.delete(revoke).status_code == 200
    assert repo.get("run_shell_command:read-only") is None
    assert client.get("/api/confirmations/preferences").json() == []


def test_revoking_something_never_approved_is_a_404(client):
    assert client.delete("/api/confirmations/preferences/never_approved").status_code == 404


def test_the_preferences_route_is_not_read_as_a_pending_request_id(client):
    """It shares a prefix with the pending-confirmation endpoints, and FastAPI
    matches in declaration order."""
    response = client.get("/api/confirmations/preferences")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# --------------------------------------------------- which turn is suspended


async def test_a_prompt_says_which_conversation_it_suspended():
    """Pending prompts are process-wide. Without the conversation on them, an
    interface recovering one after a reload raised another conversation's
    prompt over the transcript being read -- and blocked the page behind a
    decision about a tool call whose context was not on screen."""
    import asyncio

    from backend.security.confirmation import ConfirmationService
    from backend.tools.base import RiskLevel, Tool, ToolContext

    seen = []

    async def approve(request):
        seen.append(request)
        return True

    service = ConfirmationService(callback=approve)
    tool = Tool(
        name="write_file",
        description="write a file",
        parameters={"type": "object", "properties": {}},
        handler=None,
        risk=RiskLevel.MEDIUM,
    )
    events: asyncio.Queue = asyncio.Queue()
    context = ToolContext(conversation_id="conv-42", events=events)

    await service.check(tool, {"path": "notes.md"}, context)

    assert seen[0].conversation_id == "conv-42"
    kind, payload = events.get_nowait()
    assert kind == "confirmation_required"
    assert payload["conversation_id"] == "conv-42"


# --------------------------------------------------------------- deployment
#
# What a split deployment needs from the API: something cheap to wake a stopped
# container with, and a way to store a key on a host that has no keychain.


def test_ping_is_cheap_and_does_not_survey_providers(psok_home, monkeypatch):
    """The interface fires this before React mounts, to start a stopped
    container booting. `/api/health` surveys every provider over the network,
    so using that would make a cold start wait for a boot *and* a round of
    probes -- and a probe against a provider that is down takes its full
    timeout.

    Mutation check: point the interface's wake-up at `/api/health`, or give
    `ping` any work to do, and this fails.
    """
    from fastapi.testclient import TestClient

    from backend.api.main import app
    from backend.runtime import availability

    def refuse(*_a, **_k):
        raise AssertionError("ping must not survey providers")

    monkeypatch.setattr(availability, "survey", refuse)

    with TestClient(app) as client:
        response = client.get("/api/ping")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_a_key_can_be_stored_on_a_host_with_no_keychain(psok_home, monkeypatch, tmp_path):
    """A container has no OS keychain, so `keyring` raises on the first write.
    That escaped the route as a 500 with a traceback, which is how adding a key
    to a deployed instance failed without saying why.

    Mutation check: drop `PSOK_SECRETS_FILE` from `_store`, and this 503s.
    """
    from fastapi.testclient import TestClient

    from backend import secrets
    from backend.api.main import app

    store = tmp_path / "secrets.json"
    monkeypatch.setenv("PSOK_SECRETS_FILE", str(store))
    # The conftest fixture patches `_keyring`; take it back out so this exercises
    # the branch a real container takes.
    monkeypatch.setattr(secrets, "_keyring", _no_keychain)

    with TestClient(app) as client:
        response = client.post(
            "/api/providers", json={"name": "groq", "api_key": "gsk_" + "x" * 20}
        )
    assert response.status_code == 200, response.text
    assert secrets.get_secret("psok/groq") == "gsk_" + "x" * 20
    # Owner only. A key readable by every process on the box is not storage.
    assert store.stat().st_mode & 0o077 == 0


def test_without_that_variable_the_answer_names_it(psok_home, monkeypatch):
    """Not a 500, and not a silent downgrade to a file nobody asked for: the
    error says which environment variable turns file storage on.

    Mutation check: let `set_secret` raise `NoKeyringError` through.
    """
    from fastapi.testclient import TestClient

    from backend import secrets
    from backend.api.main import app

    monkeypatch.delenv("PSOK_SECRETS_FILE", raising=False)
    monkeypatch.setattr(secrets, "_keyring", _no_keychain)

    with TestClient(app) as client:
        response = client.post(
            "/api/providers", json={"name": "groq", "api_key": "gsk_" + "x" * 20}
        )
    assert response.status_code == 503, response.text
    assert "PSOK_SECRETS_FILE" in response.json()["detail"]


def _no_keychain():
    class Dead:
        @staticmethod
        def get_password(*_a):
            raise RuntimeError("no keyring backend")

        @staticmethod
        def set_password(*_a):
            raise RuntimeError("no keyring backend")

        @staticmethod
        def delete_password(*_a):
            raise RuntimeError("no keyring backend")

    return Dead


def test_every_preset_says_which_environment_variable_carries_its_key(psok_home):
    """Without it a deployed PSOK could be given a key only by hand-editing
    providers.yaml on a disk nobody has a shell on.

    Mutation check: drop `api_key_env` from `entry_for`.
    """
    from backend.provider_catalogue import PROVIDER_PRESETS, entry_for

    for preset in PROVIDER_PRESETS:
        entry = entry_for(preset)
        if preset.local:
            assert "api_key_env" not in entry, f"{preset.slug} needs no key"
            continue
        assert entry["api_key_env"], preset.slug
        assert entry["api_key_env"].isupper(), preset.slug
