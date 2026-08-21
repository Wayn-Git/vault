"""CLI actions for MCP, kept out of cli.py so the API can reuse them."""

from __future__ import annotations

import asyncio

from psok.mcp import catalogue as cat
from psok.mcp.client import OAuthRegistrationUnsupported, OAuthRequired
from psok.mcp.config import (
    KEYCHAIN_PREFIX,
    ServerConfig,
    Transport,
    add_server,
    load_servers,
    remove_server,
)
from psok.mcp.manager import MCPManager
from psok.mcp.oauth import REDIRECT_URI, forget, has_tokens
from psok.secrets import delete_secret, set_secret
from psok.security.confirmation import ConfirmationService, auto_approve
from psok.tools.registry import ToolRegistry


def _manager(open_browser: bool = True) -> MCPManager:
    registry = ToolRegistry(ConfirmationService(auto_approve))
    return MCPManager(registry, open_browser=open_browser)


def list_catalogue() -> list[dict]:
    installed = set(load_servers())
    out = []
    for entry in cat.CATALOGUE:
        out.append(
            {
                "id": entry.id,
                "title": entry.title,
                "description": entry.description,
                "category": entry.category,
                "auth": str(entry.auth),
                "transport": str(entry.transport),
                "requires": entry.requires,
                "setup_hint": entry.setup_hint,
                "homepage": entry.homepage,
                "installed": entry.id in installed,
            }
        )
    return out


def add_from_catalogue(entry_id: str, name: str | None = None) -> ServerConfig:
    entry = cat.get(entry_id)
    if entry is None:
        known = ", ".join(sorted(cat.CATALOGUE_BY_ID))
        raise ValueError(f"unknown catalogue entry '{entry_id}'. Available: {known}")
    config = entry.to_server_config(name)
    add_server(config)
    return config


def add_custom(
    name: str,
    transport: str,
    *,
    command: str | None = None,
    args: list[str] | None = None,
    url: str | None = None,
    oauth: bool = False,
    api_key_ref: str | None = None,
    allow_local: bool = False,
) -> ServerConfig:
    config = ServerConfig(
        name=name,
        transport=Transport(transport),
        command=command,
        args=args or [],
        url=url,
        oauth=oauth,
        api_key_ref=api_key_ref,
        allow_local=allow_local,
    )
    add_server(config)
    return config


def remove(name: str) -> bool:
    forget(name)
    return remove_server(name)


# Providers that expect a hand-registered OAuth app rather than dynamic registration.
REGISTRATION_HELP = {
    "github": (
        "GitHub does not support automatic app registration, so register one once:\n"
        "  1. https://github.com/settings/developers -> New OAuth App\n"
        f"  2. Authorization callback URL: {REDIRECT_URI}\n"
        "  3. Generate a client secret\n"
        "  4. psok mcp auth github --client-id <id> --client-secret <secret>\n"
        "  5. psok mcp login github"
    )
}


def registration_help(name: str, catalogue_id: str | None = None) -> str:
    return REGISTRATION_HELP.get(catalogue_id or name, "")


def set_oauth_client(name: str, client_id: str, client_secret: str | None = None) -> ServerConfig:
    """Attach a hand-registered OAuth client to a server.

    The secret goes to the keychain; only its reference is written to mcp.yaml.
    """
    servers = load_servers()
    config = servers.get(name)
    if config is None:
        raise ValueError(f"no server named '{name}' in mcp.yaml")

    config.oauth = True
    config.oauth_client_id = client_id
    if client_secret:
        ref = f"psok-mcp/{name}.client_secret"
        set_secret(ref, client_secret)
        config.oauth_client_secret_ref = ref

    # A previously registered client or stale token must not shadow the new one.
    forget(name)
    add_server(config)
    return config


def set_env(name: str, key: str, value: str, *, secret: bool = False) -> ServerConfig:
    """Set one environment variable for a stdio server.

    With `secret`, the value goes to the OS keychain and mcp.yaml keeps only a
    `keychain:` reference -- the same rule every other credential in PSOK
    follows, extended to the servers that take theirs through the environment
    (ADR-0012).
    """
    servers = load_servers()
    config = servers.get(name)
    if config is None:
        raise ValueError(f"no server named '{name}' in mcp.yaml")

    if secret:
        ref = f"psok-mcp/{name}.env.{key}"
        set_secret(ref, value)
        config.env[key] = f"{KEYCHAIN_PREFIX}{ref}"
    else:
        config.env[key] = value

    add_server(config)
    return config


def unset_env(name: str, key: str) -> bool:
    """Forget one environment variable, and its keychain entry if it had one.

    Setting a variable is not enough on its own: a value typed into the wrong
    key leaves a stdio server being handed something it does not understand,
    with no way back except editing mcp.yaml by hand.
    """
    servers = load_servers()
    config = servers.get(name)
    if config is None:
        raise ValueError(f"no server named '{name}' in mcp.yaml")
    value = config.env.pop(key, None)
    if value is None:
        return False
    if isinstance(value, str) and value.startswith(KEYCHAIN_PREFIX):
        delete_secret(value[len(KEYCHAIN_PREFIX):])
    add_server(config)
    return True


async def connect_and_report(name: str | None = None, *, open_browser: bool = True) -> dict:
    """Connect one server or all of them, returning tool counts or error strings."""
    manager = _manager(open_browser)
    servers = load_servers()
    try:
        if name:
            config = servers.get(name)
            if config is None:
                return {name: f"no server named '{name}' in mcp.yaml"}
            try:
                return {name: await manager.connect_server(config)}
            except Exception as exc:
                return {name: str(exc)}
        return await manager.connect_all()
    finally:
        await manager.shutdown()


async def login(name: str) -> str:
    """Run the OAuth flow by connecting; the SDK triggers it on the 401."""
    servers = load_servers()
    config = servers.get(name)
    if config is None:
        return f"no server named '{name}' in mcp.yaml"
    if not config.oauth:
        return f"'{name}' is not configured for OAuth"

    manager = _manager(open_browser=True)
    try:
        count = await manager.connect_server(config)
        return f"authorized '{name}' and discovered {count} tools"
    except OAuthRegistrationUnsupported as exc:
        help_text = registration_help(name, config.catalogue_id)
        return f"{exc}\n\n{help_text}" if help_text else str(exc)
    except OAuthRequired as exc:
        return f"authorization did not complete for '{name}': {exc}"
    except Exception as exc:
        return f"could not connect '{name}': {exc}"
    finally:
        await manager.shutdown()


def status() -> list[dict]:
    out = []
    for name, config in load_servers().items():
        out.append(
            {
                "name": name,
                "transport": str(config.transport),
                "enabled": config.enabled,
                "oauth": config.oauth,
                "authorized": has_tokens(name) if config.oauth else None,
                "source": str(config.source),
                "target": config.url or f"{config.command} {' '.join(config.args)}".strip(),
                # Key names and whether each is held in the keychain. Values
                # never leave the machine's config -- a token pasted into the
                # wrong field must not come back out over HTTP.
                "env": {
                    key: str(value).startswith(KEYCHAIN_PREFIX)
                    for key, value in config.env.items()
                },
            }
        )
    return out


def run(coro):
    return asyncio.run(coro)
