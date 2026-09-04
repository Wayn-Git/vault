"""Phase 4: connectors that do not offer what they cannot do, and say what they need.

The bug this phase started from: a Google connector that had never completed
OAuth put fifteen Gmail tools in front of the model, the model called one, got
`Connection closed`, invented a service outage and handed the work back.
"""

from __future__ import annotations

import pytest

from backend.mcp import guidance
from backend.mcp.lifecycle import state_of
from backend.security.confirmation import ConfirmationService, auto_approve
from backend.tools.base import RiskLevel, Tool, ToolContext, ToolResult, ToolSource
from backend.tools.registry import ToolRegistry


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
    from backend.agent.director import Director

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
    from backend.mcp import commands as mcp

    configs = {
        "fetch": type("C", (), {"name": "fetch", "enabled": True})(),
        "gmail": type("C", (), {"name": "gmail", "enabled": True})(),
    }
    monkeypatch.setattr("backend.mcp.config.load_servers", lambda: configs)
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
        "backend.tools.registry._unsigned_connectors", lambda: frozenset({"google-gmail"})
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
    from backend.mcp.client import OAuthRequired
    from backend.mcp.manager import MCPManager

    class _NeedsAuth:
        connected = True
        tools: list = []

        def __init__(self):
            from backend.mcp.client import CircuitBreaker

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

    from backend.api.main import app

    with TestClient(app) as c:
        yield c


def test_every_connector_row_carries_its_state(client, psok_home):
    """Computed on the server so the screen, the CLI and the agent loop cannot
    reach different conclusions from the same five fields."""
    from backend.mcp import commands as mcp

    mcp.add_custom(name="probe", transport="stdio", command="true", args=[])
    rows = client.get("/api/mcp/servers").json()

    row = next(r for r in rows if r["name"] == "probe")
    assert set(row["lifecycle"]) == {"state", "detail", "action", "ready"}
    assert row["lifecycle"]["state"] == "starting", "nothing has asked it to run yet"


# --- 4.4: collapsing the Google connectors ----------------------------------


def _google_servers(*services: str):
    from backend.mcp import commands as mcp

    for service in services:
        mcp.add_from_catalogue(f"google-{service}")


def test_the_merge_plans_before_it_touches_anything(psok_home):
    """Nothing here runs on startup or as a side effect. A migration that
    touches a working sign-in is a decision the account's owner takes."""
    from backend.mcp.config import config_path
    from backend.mcp.migrations import plan_google_merge

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
    from backend.mcp.config import load_servers
    from backend.mcp.migrations import apply_google_merge

    _google_servers("gmail", "calendar")
    apply_google_merge()

    merged = load_servers()["google-workspace"]
    assert merged.args == ["workspace-mcp", "--single-user", "--tools", "gmail", "calendar"]


def test_the_merge_keeps_the_credentials_directory_and_the_env(psok_home):
    """The whole reason this is safe: every entry points at the same
    `~/.google_workspace_mcp/credentials`, and so does the merged one."""
    from backend.mcp import commands as mcp
    from backend.mcp.config import load_servers
    from backend.mcp.migrations import apply_google_merge

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
    from backend.mcp.migrations import apply_google_merge

    _google_servers("gmail", "calendar")
    _, backup = apply_google_merge()

    assert backup is not None and backup.exists()
    assert "google-gmail" in backup.read_text()


def test_merging_twice_is_not_an_error(psok_home):
    from backend.mcp.migrations import apply_google_merge, plan_google_merge

    _google_servers("gmail")
    apply_google_merge()

    plan = plan_google_merge()
    assert plan.already_merged
    assert "already exists" in plan.describe()

    again, backup = apply_google_merge()
    assert again.already_merged and backup is None, "a no-op must not take a backup"


def test_nothing_to_merge_says_so(psok_home):
    from backend.mcp.migrations import plan_google_merge

    plan = plan_google_merge()
    assert plan.is_noop
    assert "nothing to merge" in plan.describe()


def test_the_merged_connector_is_switched_on_if_any_source_was(psok_home):
    """Leaving the old rows behind is not cosmetic: `reconcile` reads them, and
    a row for a connector no longer in mcp.yaml is what left `google-workspace`
    listed as enabled while not existing."""
    from backend.capabilities import CapabilityService, Kind
    from backend.mcp.migrations import apply_google_merge

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
    from backend.api import main as api

    ran: list[str] = []

    async def fake_sync(_manager):
        ran.append("microsoft-todo")

        class _Report:
            def summary(self):
                return "pulled 3 tasks"

        return _Report()

    monkeypatch.setattr("backend.sync.microsoft_todo.sync", fake_sync)
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
    from backend.api import main as api

    async def refuse(_manager):
        raise RuntimeError("microsoft-todo is not signed in")

    monkeypatch.setattr("backend.sync.microsoft_todo.sync", refuse)
    monkeypatch.setattr(api, "_manager_with", lambda name: _noop())

    await api._first_sync("microsoft-todo")  # must not raise


# ------------------------------------------------- a sign-in with a shelf life


def test_a_grant_about_to_lapse_is_announced_before_it_does():
    """Google expires a test user's consent seven days after it is given. The
    grant, not the token -- so the refresh token stops working too and the
    connector goes from working to signed-out with nothing in between, which is
    most of what "the OAuth is unstable" means on this machine.

    Nothing on this side can extend it while publishing is blocked, so the row
    says how long is left and offers the one action that helps.

    Mutation check: return None unconditionally from `_ageing_grant`.
    """
    from backend.mcp.lifecycle import state_of

    def row(age):
        return {
            "name": "google-gmail",
            "enabled": True,
            "signed_in": True,
            "grant_age_days": age,
            "grant_lifetime_days": 7,
        }

    live = {"connected": True, "tools": 15}

    fresh = state_of(row(1), live=live)
    assert fresh.state == "ready" and fresh.action is None, "silent for most of its life"

    warned = state_of(row(6), live=live)
    assert warned.ready is True, "still usable: this is a warning, not a failure"
    assert warned.action == "sign_in"
    assert "expires in 1 day" in warned.detail

    lapsed = state_of(row(9), live=live)
    assert "probably lapsed" in lapsed.detail
    assert lapsed.action == "sign_in"

    unlimited = state_of(
        {"name": "github", "enabled": True, "signed_in": True, "grant_age_days": 400},
        live=live,
    )
    assert unlimited.action is None, "a connector with no declared lifetime never warns"


def test_two_accounts_in_a_single_user_store_are_reported():
    """`MCP_SINGLE_USER_MODE` means the server picks one of the accounts in its
    credentials directory and PSOK cannot tell which. Two Google accounts were
    sitting in that directory on the machine this was written on, and every
    tool call was answering for whichever one the server chose.

    Mutation check: drop the `accounts > 1` branch from `state_of`.
    """
    from backend.mcp.lifecycle import state_of

    state = state_of(
        {"name": "google-gmail", "enabled": True, "signed_in": True, "accounts": 2},
        live={"connected": True, "tools": 15},
    )
    assert state.ready is True
    assert "2 accounts" in state.detail
    assert state.action == "sign_in"


def test_a_browser_profile_is_not_six_accounts(psok_home, tmp_path, monkeypatch):
    """LinkedIn's credential store is a browser profile directory, so counting
    its files reported six LinkedIn accounts on a machine with one -- and the
    row then offered to "settle which one" a single sign-in was using.

    `account_from_filename` is the catalogue's existing answer to "does a
    filename here name a person", and the count reads the same field the labels
    do, so the two cannot disagree about one directory.

    Mutation check: count `_accounts_of` unconditionally in `account_count`.
    """
    from backend.mcp import catalogue as cat
    from backend.mcp import commands
    from backend.mcp.config import ServerConfig, Transport

    profile = tmp_path / "profile"
    profile.mkdir()
    for name in ("Cookies", "History", "Preferences", "Local State", "a@b.com", "Cache"):
        (profile / name).write_text("x")

    linkedin = cat.get("linkedin")
    assert linkedin is not None and linkedin.account_from_filename is False
    monkeypatch.setattr(commands, "_credentials_dir", lambda config: profile)

    config = ServerConfig(
        name="linkedin", transport=Transport.STDIO, command="x", catalogue_id="linkedin"
    )
    assert commands.account_count(config) == 1, "one profile is one account, not six files"

    # Google names its credential files by address, so there each file is a
    # person and two of them really is an ambiguity worth reporting.
    google = ServerConfig(
        name="google-gmail", transport=Transport.STDIO, command="x", catalogue_id="google-gmail"
    )
    monkeypatch.setattr(commands, "_accounts_of", lambda config: [profile, profile])
    assert commands.account_count(google) == 2


# --------------------------------------------------- ready is read off the registry
#
# A connector reported "failed to start" while the agent was calling its tools.
# `state_of` checked the error string before it checked anything else, and the
# manager reported an error string that nothing ever cleared, so one transient
# spawn, discovery or OAuth failure was permanent as far as every screen was
# concerned. The fix is that tools in the `ToolRegistry` are the ground truth.


def _manager_with(tool_count: int, *, connected: bool = True):
    """A manager holding `tool_count` registered tools for one server."""
    from backend.mcp.manager import MCPManager
    from backend.security.confirmation import ConfirmationService, auto_approve
    from backend.tools.base import RiskLevel, Tool, ToolResult, ToolSource
    from backend.tools.registry import ToolRegistry, mcp_tool_key

    async def handler(args, ctx):
        return ToolResult.ok("ok")

    registry = ToolRegistry(ConfirmationService(auto_approve))
    manager = MCPManager(registry, open_browser=False)
    for n in range(tool_count):
        registry.register(
            Tool(
                name=mcp_tool_key(f"t{n}", "browser"),
                description="d",
                parameters={},
                handler=handler,
                risk=RiskLevel.LOW,
                source=ToolSource.MCP,
                server_name="browser",
            )
        )

    class _Session:
        def __init__(self) -> None:
            self.connected = connected
            self.tools = list(range(tool_count))

    if tool_count:
        import time as _time

        manager.ready_since["browser"] = _time.monotonic()
    if connected:
        manager.connections["browser"] = _Session()
    return manager


def test_a_registered_tool_outranks_a_recorded_error():
    """The ordering is the whole fix. A connector serving 122 tools must never
    describe itself as failed while it serves them.

    Mutation check: move the `live.get("ready")` branch in `state_of` back
    below the `error` check.
    """
    from backend.mcp.lifecycle import state_of

    manager = _manager_with(3)
    manager.errors["browser"] = "npx: spawn failed"

    reported = manager.state()["browser"]
    assert reported["ready"] is True
    assert reported["tools"] == 3, "counted from the registry, not from the connection"
    assert reported["error"] is None, "withheld while ready -- kept in `errors` for the log"
    assert manager.errors["browser"], "the string itself is not forgotten"

    state = state_of(_row("browser"), live=reported)
    assert state.state == "ready" and state.ready is True
    assert state.detail == "Ready, 3 tools."

    # And directly, with an error the caller did not suppress. `state_of` is
    # read by the CLI and by anything holding an older `live` dict, so the
    # ordering has to hold in the derivation and not only in the manager.
    both = state_of(
        _row("browser"), live={"connected": True, "tools": 3, "error": "npx: spawn failed"}
    )
    assert both.state == "ready", "tools present outrank an error string here too"
    assert both.detail == "Ready, 3 tools."


def test_one_transient_failure_does_not_demote_a_working_connector():
    """Two failures are a bad minute; three is a connector that is gone.

    Mutation check: set `DEMOTE_AFTER_FAILURES` to 1.
    """
    from backend.mcp.manager import DEMOTE_AFTER_FAILURES

    assert DEMOTE_AFTER_FAILURES == 3, "the threshold this test pins"

    manager = _manager_with(3)
    manager._hold_off("browser")
    assert manager.is_ready("browser") is True, "one refused DNS lookup is a bad minute"
    manager._hold_off("browser")
    assert manager.is_ready("browser") is True, "so is a second"

    manager._hold_off("browser")
    assert manager.is_ready("browser") is False, "the third consecutive failure demotes it"
    assert manager.state()["browser"]["error"] is None, "no error was recorded, only failures"


def test_tools_leaving_the_registry_demotes_it_at_once():
    """The cool-down forgives an error, not an empty registry: a connector with
    no tools cannot be used no matter how recently it could.

    Mutation check: drop the `registered_tool_count(name) <= 0` guard.
    """
    from backend.mcp.lifecycle import state_of

    manager = _manager_with(3)
    manager.registry.unregister_server("browser")

    assert manager.is_ready("browser") is False
    manager.errors["browser"] = "[Errno 111] Connection refused"
    assert state_of(_row("browser"), live=manager.state()["browser"]).state == "failed"


def test_a_dead_session_stays_ready_only_for_the_cool_down(monkeypatch):
    """A registration vouches for a connector for a while after its session
    goes, so a reconnect in flight does not flicker the row through "failed".

    Mutation check: return True unconditionally once tools are registered.
    """
    import backend.mcp.manager as manager_module

    manager = _manager_with(2, connected=False)
    assert manager.is_ready("browser") is True, "just registered"

    monkeypatch.setattr(
        manager_module.time,
        "monotonic",
        lambda: manager.ready_since["browser"] + manager_module.READY_COOLDOWN_SECONDS + 1,
    )
    assert manager.is_ready("browser") is False, "and no longer vouches for it after that"


async def test_connecting_an_already_connected_server_does_not_rebuild_it():
    """Reconcile runs at the head of every turn. Reconnecting unconditionally
    gave a working connector a fresh chance to fail transiently, every turn.

    Mutation check: remove the early return from `connect_server`.
    """
    from backend.mcp.config import ServerConfig, Transport

    manager = _manager_with(4)
    torn_down: list[str] = []

    async def record(name):
        torn_down.append(name)

    manager.disconnect_server = record
    config = ServerConfig(name="browser", transport=Transport.STDIO, command="x")

    assert await manager.connect_server(config, interactive=False) == 4
    assert torn_down == [], "an idempotent connect leaves the live session alone"

    from backend.mcp.client import MCPConnectionError

    with pytest.raises(MCPConnectionError):
        # `force` is what a person pressing Connect passes, and it must still
        # rebuild -- proven here by it getting far enough to tear the old one
        # down and then fail on a command that does not exist.
        await manager.connect_server(config, interactive=False, force=True)
    assert torn_down == ["browser"], "and force still means force"
