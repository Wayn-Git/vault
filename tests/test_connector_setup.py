"""Phase 4: connectors that do not offer what they cannot do, and say what they need.

The bug this phase started from: a Google connector that had never completed
OAuth put fifteen Gmail tools in front of the model, the model called one, got
`Connection closed`, invented a service outage and handed the work back.
"""

from __future__ import annotations

import pytest

from psok.mcp import guidance
from psok.mcp.lifecycle import state_of
from psok.security.confirmation import ConfirmationService, auto_approve
from psok.tools.base import RiskLevel, Tool, ToolContext, ToolResult, ToolSource
from psok.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def _forget_sign_in_cache():
    guidance.forget()
    yield
    guidance.forget()


def _server_tool(name: str, server: str) -> Tool:
    async def handler(args, ctx):
        return ToolResult.ok("ran")

    return Tool(
        name=name,
        description="d",
        parameters={"type": "object", "properties": {}},
        handler=handler,
        risk=RiskLevel.LOW,
        source=ToolSource.MCP,
        server_name=server,
    )


# --- 4.1: tools of a connector nobody signed in to are withheld -------------


async def test_tools_of_an_unsigned_connector_are_not_offered(db, monkeypatch):
    """`connected` is not `signed in`. A stdio server registers its tools long
    before an account is attached, and every one of them would fail.

    Mutation check: drop the `unsigned` union from `_disabled_connectors`.
    """
    from psok.agent.director import Director

    registry = ToolRegistry(ConfirmationService(auto_approve))
    registry.register(_server_tool("gmail_search", "google-gmail"))
    registry.register(_server_tool("fetch_url", "fetch"))

    monkeypatch.setattr(guidance, "unsigned_connectors", lambda: frozenset({"google-gmail"}))

    director = Director(registry, stream=False, memory=False)
    hidden = director._disabled_connectors("conv-1")

    assert "google-gmail" in hidden
    assert "fetch" not in hidden, "a connector with nothing to sign in to still works"

    offered = {schema.name for schema in registry.schemas(hidden_servers=hidden)}
    assert offered == {"fetch_url"}


async def test_a_connector_with_no_account_to_attach_is_not_hidden(db, monkeypatch):
    """`is_signed_in` returns None where there is nothing to sign in to, which
    is not False. Treating the two alike would hide the fetch connector.

    Mutation check: use `is not True` instead of `is False` in `unsigned_connectors`.
    """
    from psok.mcp import commands as mcp

    configs = {
        "fetch": type("C", (), {"name": "fetch", "enabled": True})(),
        "gmail": type("C", (), {"name": "gmail", "enabled": True})(),
    }
    monkeypatch.setattr("psok.mcp.config.load_servers", lambda: configs)
    monkeypatch.setattr(
        mcp, "is_signed_in", lambda c: None if c.name == "fetch" else False
    )
    guidance.forget()

    assert guidance.unsigned_connectors() == frozenset({"gmail"})


async def test_calling_a_withheld_tool_returns_an_instruction_not_an_error(db, monkeypatch):
    """Withholding the schema is not enough: a model can name a tool it saw in
    an earlier turn, and the connection is shared with every conversation.

    Mutation check: delete the `_unsigned_connectors()` guard in `dispatch`.
    """
    registry = ToolRegistry(ConfirmationService(auto_approve))
    registry.register(_server_tool("gmail_search", "google-gmail"))
    monkeypatch.setattr(
        "psok.tools.registry._unsigned_connectors", lambda: frozenset({"google-gmail"})
    )

    result = await registry.dispatch("gmail_search", {}, ToolContext(conversation_id="c"))

    assert result.is_error
    assert "google-gmail" in result.content
    assert "Connect" in result.content and "Connectors" in result.content
    assert "Do not retry" in result.content


# --- 4.2: a failure the model can act on ------------------------------------


def test_every_connector_failure_names_the_screen_and_the_button():
    """`BASE_PROMPT`'s "errors are information" is true and too general to act
    on. A raw exception string names no connector, no screen and no button."""
    for message in (
        guidance.sign_in_instruction("google-gmail"),
        guidance.not_connected_instruction("google-gmail"),
        guidance.dropped_instruction("google-gmail", "pipe closed"),
    ):
        assert "google-gmail" in message
        assert "Connectors" in message
        assert "Do not retry" in message, "retrying is what spent the iteration budget"


async def test_an_oauth_failure_does_not_send_a_browser_user_to_the_terminal(monkeypatch):
    """It used to answer `psok mcp login <name>`. The user is in a browser and
    the button is two clicks away.

    Mutation check: restore the `psok mcp login` string in `_make_handler`.
    """
    from psok.mcp.client import OAuthRequired
    from psok.mcp.manager import MCPManager

    class _NeedsAuth:
        connected = True
        tools: list = []

        def __init__(self):
            from psok.mcp.client import CircuitBreaker

            self.breaker = CircuitBreaker()

        async def call(self, *_a, **_k):
            raise OAuthRequired("nope")

    manager = MCPManager(ToolRegistry())
    manager.connections["google-gmail"] = _NeedsAuth()

    result = await manager._make_handler("google-gmail", "search")({}, ToolContext())

    assert result.is_error
    assert "psok mcp login" not in result.content
    assert "Connect" in result.content


# --- 4.3: one state per connector -------------------------------------------


def _row(name="x", **kw):
    base = {"name": name, "enabled": True, "signed_in": None, "missing_credentials": []}
    base.update(kw)
    return base


def test_a_sign_in_in_flight_outranks_every_other_fact():
    """Mid sign-in a connector is also not connected and also has no account.
    Reporting either at that moment tells someone looking at a consent page that
    the thing they are doing is not happening.

    Mutation check: move the `pending` checks below the `signed_in` check.
    """
    state = state_of(
        _row(signed_in=False),
        pending={"status": "waiting"},
        live={"connected": False},
    )
    assert state.state == "authenticating"
    assert state.action is None, "the only correct thing to do is wait"


def test_missing_credentials_are_named_not_counted():
    state = state_of(_row(missing_credentials=["GOOGLE_OAUTH_CLIENT_SECRET"]))
    assert state.state == "setup"
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in state.detail
    assert state.action == "credentials"


def test_running_without_an_account_is_its_own_state_not_ready():
    """This is the grouping bug: 122 tools live beside a Sign in button."""
    state = state_of(_row(signed_in=False), live={"connected": True, "tools": 122})
    assert state.state == "sign_in"
    assert state.ready is False


def test_not_started_yet_is_not_the_same_as_failed():
    """On a freshly booted server every connector rendered as broken."""
    assert state_of(_row(), live={}, reconciled=False).state == "starting"
    assert state_of(_row(), live={}, reconciled=True).state == "failed"


def test_microsoft_todo_is_not_ready_until_its_first_pull():
    """Signed in with tools live and an empty Tasks page reads as the sync being
    broken rather than as never having been asked to run."""
    live = {"connected": True, "tools": 16}
    assert state_of(_row("microsoft-todo"), live=live, synced=False).state == "syncing"
    assert state_of(_row("microsoft-todo"), live=live, synced=True).state == "ready"
    # Only the connectors that mirror something. Everything else is ready when
    # it is connected.
    assert state_of(_row("fetch"), live=live, synced=False).state == "ready"


def test_a_failure_is_led_with_what_to_do_about_it():
    state = state_of(_row(), live={"connected": False, "error": "[Errno 111] Connection refused"})
    assert state.state == "failed"
    assert "Nothing answered" in state.detail
    assert "Errno 111" in state.detail, "the raw text is the only diagnostic there is"
    assert state.action == "retry"


def test_one_tool_is_not_one_tools():
    assert state_of(_row(), live={"connected": True, "tools": 1}).detail == "Ready, 1 tool."


# --- the HTTP surface -------------------------------------------------------


@pytest.fixture
def client(psok_home):
    from fastapi.testclient import TestClient

    from psok.api.main import app

    with TestClient(app) as c:
        yield c


def test_every_connector_row_carries_its_state(client, psok_home):
    """Computed on the server so the screen, the CLI and the agent loop cannot
    reach different conclusions from the same five fields."""
    from psok.mcp import commands as mcp

    mcp.add_custom(name="probe", transport="stdio", command="true", args=[])
    rows = client.get("/api/mcp/servers").json()

    row = next(r for r in rows if r["name"] == "probe")
    assert set(row["lifecycle"]) == {"state", "detail", "action", "ready"}
    assert row["lifecycle"]["state"] == "starting", "nothing has asked it to run yet"


# --- 4.4: collapsing the Google connectors ----------------------------------


def _google_servers(*services: str):
    from psok.mcp import commands as mcp

    for service in services:
        mcp.add_from_catalogue(f"google-{service}")


def test_the_merge_plans_before_it_touches_anything(psok_home):
    """Nothing here runs on startup or as a side effect. A migration that
    touches a working sign-in is a decision the account's owner takes."""
    from psok.mcp.config import config_path
    from psok.mcp.migrations import plan_google_merge

    _google_servers("gmail", "calendar", "drive")
    before = config_path().read_text()

    plan = plan_google_merge()

    assert sorted(plan.sources) == ["google-calendar", "google-drive", "google-gmail"]
    assert plan.tools == ["gmail", "calendar", "drive"], "catalogue order, not file order"
    assert config_path().read_text() == before, "planning must not write"


def test_merging_grants_only_the_services_that_were_configured(psok_home):
    """Merging three connectors must not silently hand the model five.

    Mutation check: use `GOOGLE_MERGED_TOOLS` instead of `plan.tools` in
    `apply_google_merge`.
    """
    from psok.mcp.config import load_servers
    from psok.mcp.migrations import apply_google_merge

    _google_servers("gmail", "calendar")
    apply_google_merge()

    merged = load_servers()["google-workspace"]
    assert merged.args == ["workspace-mcp", "--single-user", "--tools", "gmail", "calendar"]


def test_the_merge_keeps_the_credentials_directory_and_the_env(psok_home):
    """The whole reason this is safe: every entry points at the same
    `~/.google_workspace_mcp/credentials`, and so does the merged one."""
    from psok.mcp import commands as mcp
    from psok.mcp.config import load_servers
    from psok.mcp.migrations import apply_google_merge

    _google_servers("gmail", "calendar", "drive", "docs", "sheets")
    before = load_servers()["google-gmail"]
    apply_google_merge()

    servers = load_servers()
    merged = servers["google-workspace"]
    assert not [n for n in servers if n.startswith("google-") and n != "google-workspace"]
    assert merged.env == before.env, "the OAuth client and the port move across unchanged"

    entry = mcp.entry_for(merged)
    assert entry is not None
    assert entry.credentials_path == "~/.google_workspace_mcp/credentials"


def test_the_previous_config_is_kept(psok_home):
    """The way back. A migration with no backup is one nobody should run."""
    from psok.mcp.migrations import apply_google_merge

    _google_servers("gmail", "calendar")
    _, backup = apply_google_merge()

    assert backup is not None and backup.exists()
    assert "google-gmail" in backup.read_text()


def test_merging_twice_is_not_an_error(psok_home):
    from psok.mcp.migrations import apply_google_merge, plan_google_merge

    _google_servers("gmail")
    apply_google_merge()

    plan = plan_google_merge()
    assert plan.already_merged
    assert "already exists" in plan.describe()

    again, backup = apply_google_merge()
    assert again.already_merged and backup is None, "a no-op must not take a backup"


def test_nothing_to_merge_says_so(psok_home):
    from psok.mcp.migrations import plan_google_merge

    plan = plan_google_merge()
    assert plan.is_noop
    assert "nothing to merge" in plan.describe()


def test_the_merged_connector_is_switched_on_if_any_source_was(psok_home):
    """Leaving the old rows behind is not cosmetic: `reconcile` reads them, and
    a row for a connector no longer in mcp.yaml is what left `google-workspace`
    listed as enabled while not existing."""
    from psok.capabilities import CapabilityService, Kind
    from psok.mcp.migrations import apply_google_merge

    _google_servers("gmail", "calendar")
    service = CapabilityService()
    service.set_enabled(Kind.CONNECTOR, "google-gmail", True)

    apply_google_merge()

    assert service.is_enabled(Kind.CONNECTOR, "google-workspace")
    assert service.switched_off(Kind.CONNECTOR, "google-gmail") is False
    assert service._get("global", Kind.CONNECTOR, "google-gmail") is None, "stale row removed"


# --- 4.3, the last step: adding runs the first sync too ---------------------


async def test_adding_a_connector_runs_its_first_sync(psok_home, monkeypatch):
    """Phase 4.3 asked for adding a connector to run its *whole* setup,
    "including a first sync for microsoft-todo". Signed in with tools live and
    an empty Tasks page reads as the sync being broken rather than as never
    having been asked to run.

    Mutation check: delete the `_first_sync` call from `_start_after_add`.
    """
    from psok.api import main as api

    ran: list[str] = []

    async def fake_sync(_manager):
        ran.append("microsoft-todo")

        class _Report:
            def summary(self):
                return "pulled 3 tasks"

        return _Report()

    monkeypatch.setattr("psok.sync.microsoft_todo.sync", fake_sync)
    monkeypatch.setattr(api, "_manager_with", lambda name: _noop())

    await api._first_sync("microsoft-todo")
    assert ran == ["microsoft-todo"]

    # Every other connector has nothing to pull, and must not pay for a sync.
    ran.clear()
    await api._first_sync("google-gmail")
    assert ran == []


async def _noop():
    return None


async def test_a_first_sync_that_cannot_run_yet_is_not_a_failure(psok_home, monkeypatch):
    """Right after adding it, "not signed in" is the expected state on the way
    through -- not a reason to fail the add."""
    from psok.api import main as api

    async def refuse(_manager):
        raise RuntimeError("microsoft-todo is not signed in")

    monkeypatch.setattr("psok.sync.microsoft_todo.sync", refuse)
    monkeypatch.setattr(api, "_manager_with", lambda name: _noop())

    await api._first_sync("microsoft-todo")  # must not raise
