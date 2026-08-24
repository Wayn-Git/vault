"""CLI actions for MCP, kept out of cli.py so the API can reuse them."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
import webbrowser
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

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
from psok.mcp.oauth import (
    PENDING,
    REDIRECT_URI,
    PendingAuthorization,
    forget,
    has_tokens,
    token_ref,
)
from psok.secrets import delete_secret, get_secret, set_secret
from psok.security.confirmation import ConfirmationService, auto_approve
from psok.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# Stands in for the address a server demands before it will build an
# authorization URL, when the whole point is that the user has not chosen one
# yet. It never reaches the provider: the hint carrying it is stripped before
# the browser opens, and the account is whatever they pick.
ACCOUNT_TO_BE_CHOSEN = "pending@psok.local"

# How long a server that owns its own OAuth is kept running for the user to
# finish in the browser, and how often its credential store is checked. Matched
# to the loopback callback's wait so the two sign-in shapes give a person the
# same amount of time.
AUTH_SESSION_TIMEOUT_SECONDS = 300.0
AUTH_POLL_SECONDS = 2.0

# Servers held open purely for a sign-in in progress, and the tasks that own
# them. Separate from the live registry's manager: this one exists only until
# the flow lands, and must not be mistaken for a connection anyone can use.
_AUTH_SESSIONS: dict[str, MCPManager] = {}
_AUTH_TASKS: dict[str, asyncio.Task] = {}


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


def entry_for(config: ServerConfig) -> cat.CatalogueEntry | None:
    """The catalogue entry a configured server came from, if any."""
    return cat.get(config.catalogue_id or config.name)


def auth_kind(config: ServerConfig) -> str:
    """Who runs this server's sign-in: PSOK, the server itself, or nobody.

    `client.py`'s `_transport` builds PSOK's OAuth provider for remote
    transports only. A stdio server therefore never sees it, however its config
    is flagged -- it runs its own flow in its own process. Conflating the two
    is what let a Google client id be stored in fields nothing downstream reads
    while the interface reported the connector as signed in.

    Returns "oauth" (PSOK drives it), "setup" (the server drives it, once it
    has credentials), or "none".
    """
    entry = entry_for(config)
    if config.is_remote and config.oauth:
        return "oauth"
    if entry is not None and entry.auth is cat.AuthKind.SETUP:
        return "setup"
    return "none"


def _reject_implausible_client_id(name: str, client_id: str) -> None:
    """Refuse a value that cannot be an OAuth client id.

    Every provider PSOK supports issues an opaque token here -- never an email
    address, never something with a space in it. Storing one anyway replaced a
    working Google client with the string `dadad@gmail.com` and left the
    connector reporting itself configured, so this is a real failure mode
    rather than a hypothetical one.
    """
    if "@" in client_id or client_id != client_id.strip() or " " in client_id:
        raise ValueError(
            f"'{client_id}' is not an OAuth client id for '{name}'. A client id is the"
            " opaque identifier the provider issued when you registered the app"
            " (GitHub: Ov23li…, Google: …apps.googleusercontent.com) -- not an email"
            " address or an account name."
        )


def _write_credentials_file(
    name: str, entry: cat.CatalogueEntry, client_id: str, client_secret: str | None
) -> None:
    """Put the client where a server that reads a JSON file will find it.

    Same rule as `client_id_env`: credentials go where the server actually
    looks. The medium differs because the server decided so -- this one reads no
    environment at all.

    ADR-0012 says PSOK's secrets live in the keychain, and they still do: the
    secret is stored there first and this file is written from it, so the
    keychain stays the source of truth and re-entering the client rewrites the
    file. The file itself is unavoidable -- the server has no other input -- so
    it is written 0600 and the sign-in tokens the server later adds to it stay
    under the same mode.
    """
    path = Path(entry.credentials_file or "").expanduser()
    keys = entry.credentials_file_keys
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except ValueError:
            existing = {}

    if client_secret:
        set_secret(f"psok-mcp/{name}.client_secret", client_secret)
    else:
        client_secret = get_secret(f"psok-mcp/{name}.client_secret")

    existing[keys["client_id"]] = client_id
    if client_secret and "client_secret" in keys:
        existing[keys["client_secret"]] = client_secret
    if "redirect_uri" in keys:
        existing.setdefault(keys["redirect_uri"], "http://127.0.0.1:8888/callback")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2))
    path.chmod(0o600)


def set_oauth_client(name: str, client_id: str, client_secret: str | None = None) -> ServerConfig:
    """Attach a hand-registered OAuth client to a server.

    Where the credentials belong depends on who runs the flow. PSOK's OAuth
    provider is built for remote transports only, so a stdio server's client id
    and secret go into the environment its process reads -- the catalogue entry
    names the two variables. Secrets go to the keychain either way; mcp.yaml
    keeps only a reference.
    """
    servers = load_servers()
    config = servers.get(name)
    if config is None:
        raise ValueError(f"no server named '{name}' in mcp.yaml")
    _reject_implausible_client_id(name, client_id)

    if config.transport is Transport.STDIO:
        entry = entry_for(config)
        if entry is not None and entry.credentials_file:
            _write_credentials_file(name, entry, client_id, client_secret)
            return load_servers()[name]
        if entry is None or not entry.client_id_env:
            raise ValueError(
                f"'{name}' runs over stdio and PSOK does not run its sign-in, so there is"
                " nowhere for an OAuth client to go. Set whatever variables the server"
                " documents as environment credentials instead."
            )
        # `oauth: true` on a stdio server is a claim `_transport` never honours.
        config.oauth = False
        config.oauth_client_id = None
        config.oauth_client_secret_ref = None
        add_server(config)
        # Connectors that share an account share the client that authorizes it.
        # One Google client covers all nine Google applications, so asking for
        # it once per connector would be asking for the same thing nine times
        # and leaving eight of them broken until you did.
        for target in [name, *shares_account_with(name)]:
            target_entry = entry_for(load_servers()[target])
            if target_entry is None or not target_entry.client_id_env:
                continue
            set_env(target, target_entry.client_id_env, client_id, secret=False)
            if client_secret and target_entry.client_secret_env:
                set_env(target, target_entry.client_secret_env, client_secret, secret=True)
        return load_servers()[name]

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


def _accounts_of(config: ServerConfig) -> list[Path]:
    """Every signed-in account this server's own store holds."""
    entry = entry_for(config)
    found = _account_files(_credentials_dir(config), entry.account_files if entry else "*@*")
    if entry is None or not entry.account_key:
        return found
    # The file is there before anyone signs in, because the client credentials
    # share it. Only the key written by a completed sign-in settles it.
    return [path for path in found if _json_key_present(path, entry.account_key)]


def _json_key_present(path: Path, key: str) -> bool:
    try:
        return bool(json.loads(path.read_text()).get(key))
    except (OSError, ValueError):
        return False


def _credentials_dir(config: ServerConfig) -> Path | None:
    entry = entry_for(config)
    if entry is None or not entry.credentials_path:
        return None
    return Path(entry.credentials_path).expanduser()


def _account_files(directory: Path | None, pattern: str = "*@*") -> list[Path]:
    """The credential files that stand for a signed-in account, and no others.

    A server keeps more than accounts in its store: an abandoned sign-in leaves
    `oauth_states.json` behind, and counting that as an account reported the
    connector signed in "as oauth_states" when nobody had finished signing in at
    all. What an account looks like is the server's business, so the catalogue
    entry says -- Google names its files by address, LinkedIn keeps a browser
    profile, Microsoft To Do keeps one token cache file.
    """
    if directory is None:
        return []
    # A single-file store is its own account: a token cache is one file, not a
    # directory of them, and treating it as a directory found nothing.
    if directory.is_file():
        return [directory]
    if not directory.is_dir():
        return []
    return sorted((p for p in directory.glob(pattern) if p.is_file()), key=lambda p: p.stem)


def shares_account_with(name: str) -> list[str]:
    """Other configured connectors that sign in as the same account.

    The nine Google applications are one Google account reached nine ways. The
    interface has to say so, or switching Gmail on after connecting Calendar
    looks like it needs its own sign-in and offers a button that would do
    nothing new.
    """
    config = load_servers().get(name)
    entry = entry_for(config) if config else None
    if entry is None or not entry.shares_account_with:
        return []
    return sorted(
        other
        for other, config in load_servers().items()
        if other != name
        and (lambda e: e is not None and e.shares_account_with == entry.shares_account_with)(
            entry_for(config)
        )
    )


def sign_out(name: str) -> list[str]:
    """Forget the signed-in account, so the next sign-in reaches the chooser.

    Switching a connector off only stops its process; the account it was signed
    in as survives in storage, which is why reconnecting used to succeed
    silently as whoever signed in first, with no way to change account short of
    deleting keychain entries by hand. Signing out clears both stores: PSOK's
    own tokens, and -- for a server that runs its own flow -- the credential
    files that server keeps.

    The registered *client* is deliberately cleared too: `seed_preregistered_client`
    puts it back from mcp.yaml on the next connect, so this costs nothing and
    stops a stale registration shadowing a re-entered one.
    """
    config = load_servers().get(name)
    if config is None:
        raise ValueError(f"no server named '{name}' in mcp.yaml")

    cleared: list[str] = []
    # Whatever an earlier sign-in reported is now about the account being
    # forgotten, so it must not be left on screen next to a "signed out" row.
    PENDING.pop(name, None)
    if has_tokens(name):
        cleared.append("the stored access token")
    forget(name)

    directory = _credentials_dir(config)
    if directory is not None and directory.exists():
        accounts = _accounts_of(config)
        if directory.is_file():
            directory.unlink()
        else:
            # Everything else in there is flow bookkeeping for a sign-in that is
            # now being abandoned, so it goes too rather than being left to
            # confuse the next one. A browser profile keeps its state in
            # subdirectories, so those go with it.
            shutil.rmtree(directory, ignore_errors=True)
        if accounts:
            noun = "account" if len(accounts) == 1 else "accounts"
            cleared.append(f"{len(accounts)} signed-in {noun} held by the server itself")
    return cleared


def _authorization_url_in(text: str) -> str | None:
    match = re.search(r"https?://\S+", text or "")
    if match is None:
        return None
    return match.group(0).rstrip(").,'\"")


def always_ask_which_account(url: str) -> str:
    """Make the provider show its account chooser rather than assuming.

    An authorization URL without this reuses whichever account the browser is
    already signed into, silently -- so someone with two Google accounts gets
    the wrong one with no chooser and no way to tell which they got. `consent`
    goes with it because skipping the consent screen also skips issuing a
    refresh token on Google, leaving a connection that dies in an hour.

    `login_hint` goes, for the same reason: it pre-selects an account, and the
    address it carries is one PSOK had to invent to satisfy a required argument
    rather than one the user chose. Google verifies the account actually picked
    and the credential is stored under that, so dropping the hint is what makes
    "choose your account on Google's page" true.
    """
    parsed = urlparse(url)
    if parsed.hostname not in ("accounts.google.com", "www.google.com"):
        return url
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.pop("login_hint", None)
    query["prompt"] = ["select_account consent"]
    query.setdefault("access_type", ["offline"])
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _auth_arguments(connection, entry: cat.CatalogueEntry, config: ServerConfig,
                    account_hint: str | None) -> dict[str, str]:
    """Only the arguments this server's sign-in tool actually declares.

    These were hardcoded to Google's shape -- `service_name` and
    `user_google_email` -- which is fine for the one server they were written
    for and wrong for every other. Microsoft To Do's `sign_in` takes no
    arguments at all, and handing it Google's would be sending a Google address
    to Microsoft.

    Where an address *is* required, the server uses it only as a `login_hint`,
    which `always_ask_which_account` then strips: nothing is ever stored under
    it, because the callback saves under the account the provider verifies.
    """
    declared = {}
    for tool in getattr(connection, "tools", []):
        if tool.name == entry.auth_tool:
            declared = (tool.input_schema or {}).get("properties") or {}
            break

    candidates = {
        "service_name": entry.title,
        "user_google_email": account_hint or account(config.name) or ACCOUNT_TO_BE_CHOSEN,
    }
    return {key: value for key, value in candidates.items() if key in declared}


async def _server_side_login(
    config: ServerConfig, entry: cat.CatalogueEntry, account_hint: str | None
) -> str:
    """Sign in to a server that owns its own OAuth flow.

    Connecting such a server proves only that its process started. The account
    lives inside it, reached by the tool the catalogue names, and that tool
    answers with the provider's authorization URL -- which is the thing the
    user actually has to visit. Surfacing it through PENDING puts it on the
    same banner every other pending sign-in uses.

    **The server has to stay running until the user is done.** It is the thing
    the provider redirects back to: `workspace-mcp` binds its own
    `localhost:8765/oauth2callback` listener lazily, inside its own process, and
    Microsoft To Do polls Microsoft for the device code from inside its own
    process too. Shutting the manager down when this function returned killed
    both -- Google's redirect then reached a port nothing held ("Unable to
    connect to localhost:8765") and To Do's code could never complete. So
    ownership of the manager passes to `_watch_server_side_login`, which tears
    it down when the sign-in lands, times out, or the server is asked to stop.
    """
    await end_auth_session(config.name)
    manager = _manager(open_browser=False)
    try:
        await manager.connect_server(config)
        connection = manager.connections.get(config.name)
        if connection is None:
            await manager.shutdown()
            return f"'{config.name}' did not start, so its sign-in could not begin"

        raw = await connection.call(
            entry.auth_tool or "", _auth_arguments(connection, entry, config, account_hint)
        )

        from psok.mcp.manager import normalize_result

        result = normalize_result(raw)
        url = _authorization_url_in(result.content)
        if url is None:
            await manager.shutdown()
            return (
                f"'{config.name}' did not return a sign-in link. It said: "
                f"{result.content.strip()[:400]}"
            )
        url = always_ask_which_account(url)

        PENDING[config.name] = PendingAuthorization(
            server_name=config.name, authorization_url=url
        )
        webbrowser.open(url)

        _AUTH_SESSIONS[config.name] = manager
        _AUTH_TASKS[config.name] = asyncio.create_task(
            _watch_server_side_login(config, entry),
            name=f"mcp-auth:{config.name}",
        )
        # A device-code flow answers with a code as well as a URL, and the code
        # is useless if it is not shown -- so the server's own words are passed
        # through rather than replaced with a summary that drops them.
        return f"opened {entry.title}'s sign-in page.\n\n{result.content.strip()[:600]}"
    except Exception as exc:
        await manager.shutdown()
        PENDING.pop(config.name, None)
        return f"could not start sign-in for '{config.name}': {exc}"


async def _watch_server_side_login(config: ServerConfig, entry: cat.CatalogueEntry) -> None:
    """Hold the server open until its own sign-in finishes, then let it go.

    Polling the credential store is the only signal available: the flow happens
    entirely inside the server's process and it does not report back.
    """
    deadline = time.monotonic() + AUTH_SESSION_TIMEOUT_SECONDS
    outcome, message = "failed", f"{entry.title} sign-in was not completed in time"
    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(AUTH_POLL_SECONDS)
            fresh = load_servers().get(config.name)
            if fresh is None:
                outcome, message = "failed", f"'{config.name}' was removed during sign-in"
                break
            if is_signed_in(fresh):
                who = account(config.name)
                outcome = "done"
                message = f"signed in to {entry.title}" + (f" as {who}" if who else "")
                break
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # a broken poll must not leave the process running
        outcome, message = "failed", f"sign-in for '{config.name}' failed: {exc}"
        log.debug("auth watch for %s failed", config.name, exc_info=True)
    finally:
        if (pending := PENDING.get(config.name)) is not None:
            pending.finish(outcome, message)
        _AUTH_TASKS.pop(config.name, None)
        manager = _AUTH_SESSIONS.pop(config.name, None)
        if manager is not None:
            await manager.shutdown()


async def end_auth_session(name: str) -> None:
    """Stop any sign-in already in flight for this server.

    Two concurrent sign-ins to the same server are two processes racing for one
    callback port, and the loser composes a redirect URI the provider will
    reject. The most recent request wins.
    """
    task = _AUTH_TASKS.pop(name, None)
    if task is not None and not task.done():
        task.cancel()
        with suppress(BaseException):
            await task
    manager = _AUTH_SESSIONS.pop(name, None)
    if manager is not None:
        await manager.shutdown()


async def _command_login(config: ServerConfig, entry: cat.CatalogueEntry) -> str:
    """Sign in to a server whose flow is a command rather than a tool.

    LinkedIn opens a browser for `--login`; Spotify ships a second binary that
    prints an authorization URL and waits on its own loopback callback. Neither
    exposes a tool to call, so without this they could only be signed into by
    hand in a terminal -- and PSOK's Connect button would have to either lie or
    do nothing.

    The URL is published through PENDING like every other pending sign-in, so a
    browser that did not open on its own is still one click away.
    """
    command = entry.auth_command or config.command
    if not command:
        return f"'{config.name}' has no command to sign in with"

    process = await asyncio.create_subprocess_exec(
        command,
        *entry.auth_command_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, **config.resolved_env()},
    )

    seen: list[str] = []
    published: str | None = None
    try:
        assert process.stdout is not None
        while True:
            raw = await process.stdout.readline()
            if not raw:
                break
            line = raw.decode(errors="replace").rstrip()
            seen.append(line)
            if published is None and (url := _authorization_url_in(line)):
                published = url
                PENDING[config.name] = PendingAuthorization(
                    server_name=config.name, authorization_url=url
                )
                webbrowser.open(url)
        await process.wait()
    finally:
        if process.returncode is None:
            process.kill()

    if is_signed_in(load_servers()[config.name]):
        return _finish(config.name, "done", f"signed in to {entry.title}")
    tail = "\n".join(seen[-8:]).strip()
    return _finish(
        config.name,
        "failed",
        f"sign-in to {entry.title} did not complete." + (f" It said:\n{tail}" if tail else ""),
    )


async def login(
    name: str,
    *,
    force: bool = False,
    account_hint: str | None = None,
    manager: MCPManager | None = None,
) -> str:
    """Take the user to the provider's own login page and finish the handshake.

    `force` signs out first. Without it a provider that still holds a session
    hands back the same account without ever showing its chooser, which makes
    "switch account" impossible from inside PSOK.

    `manager` is the live one, where there is one. Signing in through a
    throwaway manager stored the token and then shut the connection down, so
    the interface -- which reads what is *running*, not what is stored -- kept
    listing a freshly signed-in connector under "added, not running". Passing
    the live manager makes signing in mean "and now use it", which is what the
    button says.
    """
    servers = load_servers()
    config = servers.get(name)
    if config is None:
        return f"no server named '{name}' in mcp.yaml"

    kind = auth_kind(config)
    if kind == "none":
        return f"'{name}' needs no account — it has nothing to sign in to"

    if force:
        sign_out(name)

    entry = entry_for(config)
    if kind == "setup":
        if entry is not None and entry.auth_command_args:
            return await _command_login(config, entry)
        if entry is None or not entry.auth_tool:
            return (
                f"'{name}' signs in on its own when a tool first needs it. Give it the"
                " credentials it documents, then run any of its tools."
            )
        return await _server_side_login(config, entry, account_hint)

    live = manager is not None
    connector = manager or _manager(open_browser=True)
    if live:
        # A previous failure must not make the user's own retry a no-op.
        connector.forget_error(name)
        connector.open_browser = True
    try:
        count = await connector.connect_server(config)
    except OAuthRegistrationUnsupported as exc:
        help_text = registration_help(name, config.catalogue_id)
        return _finish(name, "failed", f"{exc}\n\n{help_text}" if help_text else str(exc))
    except OAuthRequired as exc:
        return _finish(name, "failed", f"authorization did not complete for '{name}': {exc}")
    except Exception as exc:
        return _finish(name, "failed", f"could not connect '{name}': {exc}")
    finally:
        if live:
            connector.open_browser = False
        else:
            await connector.shutdown()

    # Connecting is not the same as authorizing: a server that needs no token
    # for `tools/list` would otherwise report a sign-in that never happened.
    if not has_tokens(name):
        return _finish(
            name,
            "done",
            f"connected '{name}' and discovered {count} tools, but no token was stored",
        )
    return _finish(name, "done", f"signed in to '{name}' and discovered {count} tools")


def report_login_failure(name: str, message: str) -> None:
    """Publish a sign-in failure that happened outside `login`'s own handling."""
    _finish(name, "failed", message)


def _finish(name: str, status: str, message: str) -> str:
    """Record the outcome where a polling interface can see it, and return it.

    Sign-in can outlive the request that asked for it, so the answer cannot only
    be a return value.
    """
    pending = PENDING.get(name)
    if pending is None:
        pending = PendingAuthorization(server_name=name, authorization_url="")
        PENDING[name] = pending
    pending.finish(status, message)
    return message


def account(name: str) -> str | None:
    """Which account this connector is signed in as, where that is knowable.

    Nothing here guesses. A server that keeps its accounts as files names them
    by address; a provider with an identity endpoint is asked, using the token
    already stored. Anything else answers None, which the interface renders as
    "connected" rather than inventing a name -- the failure this replaces was
    the model filling the gap with `wayne@example.com`.
    """
    config = load_servers().get(name)
    if config is None:
        return None

    entry = entry_for(config)
    accounts = _accounts_of(config)
    if accounts:
        # Only where the filename really is the address. A browser profile or a
        # token cache says someone is signed in without saying who, and naming
        # the file as if it were an account is the same invention this exists to
        # prevent.
        if entry is not None and not entry.account_from_filename:
            return None
        return ", ".join(p.stem for p in accounts)

    if entry is None or not entry.identity_url:
        return None

    raw = get_secret(token_ref(name))
    if not raw:
        return None
    try:
        import json

        token = json.loads(raw).get("access_token")
    except ValueError:
        return None
    if not token:
        return None
    return _identity_of(entry.identity_url, entry.identity_field or "", token)


# Identity answers per access token. The Connectors page asks for every
# signed-in server's account on every load and polls while it is open, and each
# answer was a fresh blocking HTTP request with a five-second timeout -- so a
# slow provider stalled the whole listing, repeatedly, for a value that cannot
# change while the token does not.
_IDENTITY_CACHE: dict[tuple[str, str], str | None] = {}


def _identity_of(url: str, field: str, token: str) -> str | None:
    key = (url, token)
    if key in _IDENTITY_CACHE:
        return _IDENTITY_CACHE[key]
    try:
        import httpx2

        response = httpx2.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=5.0,
        )
        if response.status_code != 200:
            # Not cached: a 401 here usually means a token about to be
            # refreshed, and remembering it would outlive the reason for it.
            return None
        answer = response.json().get(field)
    except Exception as exc:  # identity is a nicety; never fail a listing over it
        log.debug("identity lookup for %s failed: %s", url, exc)
        return None
    _IDENTITY_CACHE[key] = answer
    return answer


def missing_credentials(config: ServerConfig) -> list[str]:
    """What this server needs before its sign-in can even begin."""
    entry = entry_for(config)
    if entry is None or auth_kind(config) != "setup":
        return []
    if entry.credentials_file:
        # A server reading a JSON file has nothing in `env` to check, so the
        # question is whether the client id has reached that file yet.
        path = Path(entry.credentials_file).expanduser()
        key = entry.credentials_file_keys.get("client_id", "clientId")
        return [] if _json_key_present(path, key) else ["a client id and secret"]
    wanted = [v for v in (entry.client_id_env, entry.client_secret_env) if v]
    return [key for key in wanted if key not in config.env]


def is_signed_in(config: ServerConfig) -> bool | None:
    """Whether an account is actually attached. None where there is none to attach.

    A stdio server's account is its own to hold, so the question is answered by
    its credential store rather than by PSOK's keychain -- reading the wrong one
    is what made a connector that had never seen a Google account report itself
    signed in.
    """
    kind = auth_kind(config)
    if kind == "none":
        return None
    if _credentials_dir(config) is not None:
        return bool(_accounts_of(config))
    if kind == "setup":
        return None
    return has_tokens(config.name)


def status(*, with_accounts: bool = False) -> list[dict]:
    out = []
    for name, config in load_servers().items():
        entry = entry_for(config)
        signed_in = is_signed_in(config)
        out.append(
            {
                "name": name,
                "title": entry.title if entry else name,
                "category": entry.category if entry else "Other",
                "description": config.description or (entry.description if entry else None),
                "requires": entry.requires if entry else None,
                "homepage": entry.homepage if entry else None,
                "setup_hint": entry.setup_hint if entry else None,
                "transport": str(config.transport),
                "enabled": config.enabled,
                "oauth": config.oauth,
                # How this connector signs in, and whether it has: the two facts
                # the interface needs to offer the right control.
                "auth_kind": auth_kind(config),
                "signed_in": signed_in,
                "missing_credentials": missing_credentials(config),
                # What to ask for before a server that runs its own flow can
                # start it, where it cannot start without being told.
                "account_hint_label": entry.account_hint_label if entry else None,
                "client_id_env": entry.client_id_env if entry else None,
                "shares_account_with": shares_account_with(name),
                "account": account(name) if with_accounts and signed_in else None,
                # Kept for older callers; `signed_in` is the one to read.
                "authorized": signed_in,
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
