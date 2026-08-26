"""The HTTP surface the browser talks to: static serving and connector setup.

Both are paths a person walks through rather than functions the agent calls, so
they are tested here as requests rather than as units.
"""

from __future__ import annotations

import pytest
from conftest import GOOGLE_SECRET
from fastapi.testclient import TestClient

from psok.api.main import _DIST, app
from psok.mcp import commands as mcp
from psok.mcp.config import KEYCHAIN_PREFIX, config_path, load_servers
from psok.secrets import get_secret

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
    from psok.db.repositories import ConfirmationPreferenceRepository

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

    from psok.security.confirmation import ConfirmationService
    from psok.tools.base import RiskLevel, Tool, ToolContext

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
