"""MCP config, namespacing, result normalization, OAuth storage and SSRF.

Tests that need a real server are marked `network` and skipped by default; the
live end-to-end proof lives in test_mcp_live.py.
"""

from __future__ import annotations

import pytest

from psok.mcp import catalogue as cat
from psok.mcp import commands as mcp_commands
from psok.mcp.config import ServerConfig, Source, Transport, add_server, load_servers, remove_server
from psok.mcp.manager import MCPManager, normalize_result
from psok.mcp.oauth import REDIRECT_URI, KeychainTokenStorage, client_metadata
from psok.mcp.ssrf import UnsafeURL, check_url
from psok.security.confirmation import ConfirmationService, auto_approve
from psok.tools.base import RiskLevel, ToolSource
from psok.tools.registry import ToolRegistry, mcp_tool_key

# ------------------------------------------------------------------- config


def test_config_roundtrip_without_leaking_secrets(psok_home):
    add_server(
        ServerConfig(
            name="example",
            transport=Transport.STREAMABLE_HTTP,
            url="https://example.com/mcp",
            oauth=True,
            oauth_client_id="client-123",
            oauth_client_secret_ref="psok-mcp/example.client_secret",
        )
    )
    text = (psok_home / "config" / "mcp.yaml").read_text()
    assert "client-123" in text, "a client id is not a secret and belongs in config"
    assert "psok-mcp/example.client_secret" in text, "only the reference is stored"

    loaded = load_servers()["example"]
    assert loaded.oauth and loaded.url == "https://example.com/mcp"
    assert remove_server("example") and "example" not in load_servers()


def test_stdio_server_requires_a_command(psok_home):
    with pytest.raises(ValueError, match="needs a command"):
        ServerConfig(name="x", transport=Transport.STDIO).validate()


def test_remote_server_requires_a_url(psok_home):
    with pytest.raises(ValueError, match="needs a url"):
        ServerConfig(name="x", transport=Transport.SSE).validate()


def test_env_interpolation(psok_home, monkeypatch):
    monkeypatch.setenv("PSOK_TEST_TOKEN", "abc123")
    config = ServerConfig(
        name="x",
        transport=Transport.STREAMABLE_HTTP,
        url="https://example.com",
        headers={"X-Token": "${PSOK_TEST_TOKEN}"},
    )
    assert config.resolved_headers()["X-Token"] == "abc123"


def test_api_key_resolves_from_the_keychain(psok_home):
    from psok.secrets import set_secret

    set_secret("psok-test/apikey", "sekrit")
    config = ServerConfig(
        name="x",
        transport=Transport.STREAMABLE_HTTP,
        url="https://example.com",
        api_key_ref="psok-test/apikey",
    )
    assert config.resolved_headers()["Authorization"] == "Bearer sekrit"


# ---------------------------------------------------------------- catalogue


def test_catalogue_covers_the_requested_categories():
    ids = set(cat.CATALOGUE_BY_ID)
    assert {"playwright", "github", "google-workspace"} <= ids
    categories = {e.category for e in cat.CATALOGUE}
    assert {"Browser", "Development", "Google"} <= categories


def test_catalogue_entries_are_well_formed():
    for entry in cat.CATALOGUE:
        assert entry.description and entry.homepage
        if entry.transport is Transport.STDIO:
            assert entry.command, f"{entry.id} needs a command"
        else:
            assert entry.url, f"{entry.id} needs a url"
        if entry.auth is cat.AuthKind.SETUP:
            assert entry.setup_hint, f"{entry.id} claims setup but explains nothing"


def test_adding_from_catalogue_marks_it_bundled(psok_home):
    config = mcp_commands.add_from_catalogue("playwright")
    assert config.source is Source.BUNDLED
    assert config.catalogue_id == "playwright"
    assert load_servers()["playwright"].command == "npx"


def test_unknown_catalogue_id_lists_alternatives(psok_home):
    with pytest.raises(ValueError, match="playwright"):
        mcp_commands.add_from_catalogue("not-a-real-server")


def test_github_needs_a_hand_registered_client():
    """GitHub advertises PKCE but publishes no registration endpoint."""
    assert "github" in mcp_commands.REGISTRATION_HELP
    assert REDIRECT_URI in mcp_commands.REGISTRATION_HELP["github"]


def test_setting_an_oauth_client_keeps_the_secret_out_of_config(psok_home):
    mcp_commands.add_from_catalogue("github")
    mcp_commands.set_oauth_client("github", "Iv1.abc", "super-secret")

    text = (psok_home / "config" / "mcp.yaml").read_text()
    assert "super-secret" not in text
    assert "Iv1.abc" in text

    from psok.secrets import get_secret

    assert get_secret("psok-mcp/github.client_secret") == "super-secret"


# --------------------------------------------------------------------- ssrf


@pytest.mark.parametrize("url", ["http://127.0.0.1/mcp", "http://localhost:8000/mcp"])
def test_loopback_blocked_unless_opted_in(url):
    with pytest.raises(UnsafeURL):
        check_url(url)
    check_url(url, allow_local=True)  # explicit opt-in is fine


def test_non_http_schemes_rejected():
    with pytest.raises(UnsafeURL, match="scheme"):
        check_url("file:///etc/passwd")


# ---------------------------------------------------------- tool namespacing


def test_composite_keys_disambiguate_servers():
    assert mcp_tool_key("search", "notes") == "search__mcp__notes"
    assert mcp_tool_key("search", "notes") != mcp_tool_key("search", "mail")


class _FakeConnection:
    def __init__(self, tools):
        from psok.mcp.client import CircuitBreaker, DiscoveredTool

        self.tools = [
            DiscoveredTool(name=n, description=f"does {n}", input_schema={"type": "object"})
            for n in tools
        ]
        self.breaker = CircuitBreaker()
        self.connected = True


def test_registered_mcp_tools_are_never_low_risk(psok_home):
    """PSOK cannot inspect what an external server does, so it does not assume safety."""
    registry = ToolRegistry(ConfirmationService(auto_approve))
    manager = MCPManager(registry)
    config = ServerConfig(name="notes", transport=Transport.STDIO, command="x")

    count = manager._register_tools(config, _FakeConnection(["search", "write"]))
    assert count == 2

    tool = registry.get("search__mcp__notes")
    assert tool is not None
    assert tool.risk is not RiskLevel.LOW
    assert tool.source is ToolSource.MCP
    assert tool.server_name == "notes"


def test_unregister_removes_only_that_servers_tools(psok_home):
    registry = ToolRegistry(ConfirmationService(auto_approve))
    manager = MCPManager(registry)
    manager._register_tools(
        ServerConfig(name="a", transport=Transport.STDIO, command="x"), _FakeConnection(["t"])
    )
    manager._register_tools(
        ServerConfig(name="b", transport=Transport.STDIO, command="x"), _FakeConnection(["t"])
    )
    assert len(registry.list()) == 2

    registry.unregister_server("a")
    remaining = [t.name for t in registry.list()]
    assert remaining == ["t__mcp__b"]


# ------------------------------------------------------- result normalization


class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Result:
    def __init__(self, content, is_error=False, structured_content=None):
        self.content = content
        self.is_error = is_error
        self.structured_content = structured_content


def test_text_blocks_flatten():
    out = normalize_result(
        _Result([_Block(type="text", text="hello"), _Block(type="text", text="world")])
    )
    assert out.content == "hello\nworld" and not out.is_error


def test_images_become_artifacts_not_inline_text():
    """Base64 image data must not be pasted into the model's context."""
    out = normalize_result(
        _Result([_Block(type="image", data="AAAABBBB" * 100, mime_type="image/png")])
    )
    assert "AAAABBBB" not in out.content
    assert out.artifacts and out.artifacts[0]["type"] == "image"
    assert out.artifacts[0]["mime_type"] == "image/png"


def test_error_flag_is_carried_through():
    assert normalize_result(_Result([_Block(type="text", text="nope")], is_error=True)).is_error


def test_empty_result_still_says_something():
    assert normalize_result(_Result([])).content == "(no content returned)"


# --------------------------------------------------------------------- oauth


async def test_tokens_round_trip_through_the_keychain(psok_home):
    from mcp.shared.auth import OAuthToken

    storage = KeychainTokenStorage("test-server")
    assert await storage.get_tokens() is None

    await storage.set_tokens(OAuthToken(access_token="tok-abc", token_type="Bearer"))
    assert (await storage.get_tokens()).access_token == "tok-abc"

    storage.clear()
    assert await storage.get_tokens() is None


def test_client_metadata_uses_the_loopback_redirect():
    meta = client_metadata(
        ServerConfig(
            name="x",
            transport=Transport.STREAMABLE_HTTP,
            url="https://e.com",
            oauth=True,
            oauth_scopes=["repo", "read:org"],
        )
    )
    assert str(meta.redirect_uris[0]) == REDIRECT_URI
    assert meta.scope == "repo read:org"
    assert "authorization_code" in meta.grant_types


async def test_preregistered_client_is_seeded_so_registration_is_skipped(psok_home):
    from psok.mcp.oauth import seed_preregistered_client
    from psok.secrets import set_secret

    set_secret("psok-mcp/gh.client_secret", "shh")
    config = ServerConfig(
        name="gh",
        transport=Transport.STREAMABLE_HTTP,
        url="https://api.githubcopilot.com/mcp/",
        oauth=True,
        oauth_client_id="Iv1.abc",
        oauth_client_secret_ref="psok-mcp/gh.client_secret",
    )
    await seed_preregistered_client(config)

    info = await KeychainTokenStorage("gh").get_client_info()
    assert info is not None and info.client_id == "Iv1.abc"
    assert info.client_secret == "shh"


# ------------------------------------------------------------- error surface


def test_registration_404_becomes_actionable_guidance(psok_home):
    from psok.mcp.client import MCPConnection, OAuthRegistrationUnsupported

    connection = MCPConnection(
        ServerConfig(name="github", transport=Transport.STREAMABLE_HTTP, url="https://x/mcp")
    )
    classified = connection._classify("OAuthRegistrationError: Registration failed: 404 not found")
    assert isinstance(classified, OAuthRegistrationUnsupported)
    assert "psok mcp auth github" in str(classified)


def test_nested_exception_groups_are_unwrapped_to_the_real_cause(psok_home):
    from psok.mcp.client import MCPConnection

    connection = MCPConnection(ServerConfig(name="x", transport=Transport.STDIO, command="true"))
    nested = ExceptionGroup("outer", [ExceptionGroup("inner", [ValueError("the actual problem")])])
    described = connection._describe(nested)
    assert "the actual problem" in described
    assert "unhandled errors" not in described


async def test_circuit_breaker_opens_then_recovers(psok_home):
    from psok.mcp.client import CircuitBreaker

    breaker = CircuitBreaker(max_failures=2, cooldown_seconds=0.05)
    breaker.record_failure()
    assert not breaker.is_open
    breaker.record_failure()
    assert breaker.is_open

    import asyncio

    await asyncio.sleep(0.06)
    assert not breaker.is_open, "the breaker must close again after its cooldown"


# ------------------------------------------------------ env-held credentials


def test_an_env_secret_lives_in_the_keychain_not_the_config(psok_home):
    """A stdio server that takes its credentials through the environment -- the
    Google one, for instance -- had nowhere to put them but mcp.yaml. Every
    other credential in PSOK is a keychain reference; these are too now."""
    from psok.mcp.commands import add_custom, set_env
    from psok.mcp.config import config_path, load_servers
    from psok.secrets import delete_secret

    ref = "psok-mcp/google.env.GOOGLE_OAUTH_CLIENT_SECRET"
    try:
        add_custom("google", "stdio", command="uvx", args=["workspace-mcp"])
        set_env("google", "GOOGLE_OAUTH_CLIENT_SECRET", "s3cret-value", secret=True)
        set_env("google", "GOOGLE_OAUTH_CLIENT_ID", "1234.apps.googleusercontent.com")

        on_disk = config_path().read_text()
        assert "s3cret-value" not in on_disk, "the secret must never be written to mcp.yaml"
        assert f"keychain:{ref}" in on_disk
        assert "1234.apps.googleusercontent.com" in on_disk, "a public id is not a secret"

        env = load_servers()["google"].resolved_env()
        assert env["GOOGLE_OAUTH_CLIENT_SECRET"] == "s3cret-value", "resolved at spawn time"
        assert env["GOOGLE_OAUTH_CLIENT_ID"] == "1234.apps.googleusercontent.com"
    finally:
        delete_secret(ref)  # the keychain outlives the tmp_path home


def test_a_missing_env_secret_is_reported_not_passed_as_a_reference(psok_home, monkeypatch):
    """Passing the literal string 'keychain:...' as a credential would make the
    server fail with something unrecognisable."""
    from psok.mcp.commands import add_custom
    from psok.mcp.config import add_server, load_servers

    monkeypatch.setattr("psok.secrets.get_secret", lambda ref: None)
    add_custom("google", "stdio", command="uvx")
    config = load_servers()["google"]
    config.env["TOKEN"] = "keychain:psok-mcp/google.env.TOKEN"
    add_server(config)

    assert "TOKEN" not in load_servers()["google"].resolved_env()


def test_env_still_interpolates_from_the_environment(psok_home, monkeypatch):
    from psok.mcp.commands import add_custom, set_env
    from psok.mcp.config import load_servers

    monkeypatch.setenv("PSOK_TEST_REGION", "eu-west-1")
    add_custom("thing", "stdio", command="run")
    set_env("thing", "REGION", "${PSOK_TEST_REGION}")

    assert load_servers()["thing"].resolved_env()["REGION"] == "eu-west-1"
