"""OAuth 2.1 for remote MCP servers.

The MCP SDK's OAuthClientProvider already implements the hard parts: protected
resource metadata discovery (RFC 9728), authorization server metadata (RFC 8414),
dynamic client registration (RFC 7591), PKCE, and token refresh. PSOK supplies
the three pieces the SDK deliberately leaves to the host application:

  storage           where tokens live -- the OS keychain, never a file (ADR-0012)
  redirect_handler  how the user reaches the provider's real login page
  callback_handler  how the authorization code comes back

Not every provider supports dynamic registration -- GitHub, for instance,
advertises PKCE but no registration endpoint -- so pre-registered client
credentials can be seeded into storage, which makes the SDK skip registration.
"""

from __future__ import annotations

import asyncio
import threading
import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx2
from mcp.client.auth import OAuthClientProvider
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

from backend.mcp.config import ServerConfig
from backend.secrets import delete_secret, get_secret, set_secret

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 33418
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}/oauth/callback"
CLIENT_NAME = "PSOK"

# How long a person gets to finish at the provider. Every deadline in the
# sign-in path is derived from this one so none of them can be shorter than it
# by accident -- a connect deadline that expired first is what abandoned
# sign-ins the user was still completing.
CALLBACK_TIMEOUT_SECONDS = 300.0

# How long an authorization *link* is worth offering. A published URL carries a
# state the provider will only accept for a while: PSOK's own flow stops
# listening at CALLBACK_TIMEOUT_SECONDS, and a server running its own flow
# (workspace-mcp) expires its state after ten minutes. Past this the link is
# dead, and offering it produces "Invalid or expired OAuth state parameter" --
# the provider is right to refuse it, so PSOK must stop presenting it as
# something to click.
AUTHORIZATION_LINK_TTL_SECONDS = 300.0


class AuthorizationDenied(RuntimeError):
    """The provider came back without a code: cancelled, denied, or refused."""

_SUCCESS_PAGE = b"""<!doctype html><meta charset="utf-8">
<title>PSOK - connected</title>
<style>body{font-family:system-ui,sans-serif;display:grid;place-items:center;height:100vh;
margin:0;background:#0f1115;color:#e6e8eb}div{text-align:center}h1{font-weight:600;font-size:1.3rem}
p{color:#9aa3ad}</style>
<div><h1>Connected</h1><p>You can close this tab and return to PSOK.</p></div>"""

_FAILURE_PAGE = b"""<!doctype html><meta charset="utf-8">
<title>PSOK - authorization failed</title>
<style>body{font-family:system-ui,sans-serif;display:grid;place-items:center;height:100vh;
margin:0;background:#0f1115;color:#e6e8eb}div{text-align:center}h1{font-weight:600;font-size:1.3rem}
p{color:#9aa3ad}</style>
<div><h1>Authorization failed</h1><p>Return to PSOK for details.</p></div>"""


def token_ref(server_name: str) -> str:
    return f"psok-mcp/{server_name}.tokens"


def client_ref(server_name: str) -> str:
    return f"psok-mcp/{server_name}.client"


def has_stored_token(server_name: str) -> bool:
    """Whether a sign-in has already happened for this server.

    Used to decide, *before* connecting, whether starting it would open a
    browser. An unattended caller -- a scheduled run, a background sync, the
    server warming connectors at boot -- must never begin an interactive flow:
    nobody is there to finish it, and the connect blocks for the full
    `auth_timeout_seconds` while holding the one callback port every other
    sign-in needs.
    """
    return bool(get_secret(token_ref(server_name)))


class KeychainTokenStorage:
    """TokenStorage backed by the OS keychain (ADR-0012).

    The SDK calls this; nothing here ever writes a token to the database, a log,
    or mcp.yaml.
    """

    def __init__(self, server_name: str):
        self.server_name = server_name

    async def get_tokens(self) -> OAuthToken | None:
        raw = get_secret(token_ref(self.server_name))
        if not raw:
            return None
        try:
            return OAuthToken.model_validate_json(raw)
        except ValueError:
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        set_secret(token_ref(self.server_name), tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = get_secret(client_ref(self.server_name))
        if not raw:
            return None
        try:
            return OAuthClientInformationFull.model_validate_json(raw)
        except ValueError:
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        set_secret(client_ref(self.server_name), client_info.model_dump_json())

    def clear(self) -> None:
        delete_secret(token_ref(self.server_name))
        delete_secret(client_ref(self.server_name))


@dataclass
class PendingAuthorization:
    """One authorization, surfaced so a UI can show the link and the outcome.

    Sign-in outlives the request that started it -- a user reading a consent
    screen takes as long as it takes -- so this is also how the flow reports
    that it finished. `status` walks `waiting -> done | failed` and stays on
    the terminal value until the interface has seen it, which is what lets the
    login endpoint answer immediately instead of holding a connection open for
    five minutes.
    """

    server_name: str
    authorization_url: str
    state: str | None = None
    status: str = "waiting"
    message: str | None = None
    finished_at: str | None = None
    started_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    ttl_seconds: float = AUTHORIZATION_LINK_TTL_SECONDS
    # A device-code flow hands the user a short code to type at the provider.
    # Without it the sign-in cannot be completed at all -- the page asks for a
    # code the user was never shown. Microsoft To Do is the one that does this.
    user_code: str | None = None
    # The server's own wording, kept verbatim as the fallback: whatever it said
    # is more reliable than a summary that might drop the part that mattered.
    instructions: str | None = None

    def finish(self, status: str, message: str | None = None) -> None:
        self.status = status
        self.message = message
        self.finished_at = datetime.now(UTC).isoformat(timespec="seconds")

    def age(self, now: datetime | None = None) -> float:
        started = datetime.fromisoformat(self.started_at)
        return ((now or datetime.now(UTC)) - started).total_seconds()

    @property
    def live(self) -> bool:
        """Whether this link is still worth offering.

        A `waiting` entry that has outlived its state is not waiting for
        anything: the provider will refuse the code it comes back with. Saying
        so is the difference between "sign in again" and a link that fails with
        an error about a parameter the user has never heard of.
        """
        return self.status == "waiting" and self.age() < self.ttl_seconds

    def expire(self) -> None:
        self.finish(
            "expired",
            "the sign-in link timed out before it was used. Start it again.",
        )


# Authorizations this process started, keyed by server name, so the API can
# list them. A finished one is kept until something acknowledges it.
PENDING: dict[str, PendingAuthorization] = {}

# How long a finished authorization stays listed. Long enough that an interface
# polling every few seconds cannot miss the outcome, short enough that it does
# not read as a sign-in still in progress.
FINISHED_TTL_SECONDS = 120.0


def prune_finished(now: datetime | None = None) -> None:
    """Expire dead links, then drop outcomes that have had time to be seen.

    A `waiting` entry is not evidence that anything is still waiting -- the
    process behind it may have been shut down, or its state may simply have
    aged out. Marking it `expired` here is what stops the interface offering a
    link that can only fail.
    """
    moment = now or datetime.now(UTC)
    for pending in list(PENDING.values()):
        if pending.status == "waiting" and not pending.live:
            pending.expire()
    for name, pending in list(PENDING.items()):
        if pending.status == "waiting" or not pending.finished_at:
            continue
        if (moment - datetime.fromisoformat(pending.finished_at)).total_seconds() > (
            FINISHED_TTL_SECONDS
        ):
            del PENDING[name]


class _CallbackHandler(BaseHTTPRequestHandler):
    """One request on the loopback callback.

    The result is written onto the *server* rather than onto the class. It used
    to be a class attribute, which made it process-global: two sign-ins running
    at once wrote into the same slot, and each flow's `result = None` reset
    could erase a redirect the other was about to read. State validation would
    then reject a code that was perfectly valid, for the wrong flow.
    """

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path != "/oauth/callback":
            # Not the redirect. Browsers ask for /favicon.ico unprompted, and
            # answering 404 is right -- but this must not count as the callback,
            # or an unrelated request ends a sign-in that has not happened yet.
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        code = (params.get("code") or [None])[0]
        self.server.callback_result = {  # type: ignore[attr-defined]
            "code": code,
            "state": (params.get("state") or [None])[0],
            "iss": (params.get("iss") or [None])[0],
            "error": (params.get("error") or [None])[0],
            "error_description": (params.get("error_description") or [None])[0],
        }
        body = _SUCCESS_PAGE if code else _FAILURE_PAGE
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # The page carries a code in its URL. Nothing should keep a copy.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # keep the terminal clean
        return


class CallbackPortUnavailable(RuntimeError):
    """The fixed loopback callback port is already in use.

    The port cannot simply be changed: it is baked into the redirect URI the
    user registered with the provider, so the honest response is to say what is
    holding it rather than to fail with a bare OSError.
    """


async def _wait_for_callback(timeout: float = CALLBACK_TIMEOUT_SECONDS) -> AuthorizationCodeResult:
    """Hold the loopback callback open until the provider redirects back.

    Three things this has to get right, each of which was wrong:

    **Serve until the redirect arrives, not until the first request.** A single
    `handle_request()` is consumed by whatever knocks first -- a browser asking
    for `/favicon.ico` is enough -- and the real callback then finds nothing
    listening. Requests that are not the callback are answered 404 and the
    server keeps waiting.

    **Keep the result with the server, not with the class.** Two sign-ins at
    once shared one slot, so each could read the other's redirect.

    **Give the port back the moment the wait ends.** The port is fixed, because
    it is baked into the redirect URI registered with the provider, so a wait
    that lingers after the user has given up blocks every retry until it
    expires -- which is what turned one abandoned sign-in into five minutes of
    "another PSOK sign-in may already be in progress".
    """
    try:
        server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler)
    except OSError as exc:
        raise CallbackPortUnavailable(
            f"cannot listen on {CALLBACK_HOST}:{CALLBACK_PORT} for the OAuth redirect"
            f" ({exc}). Another PSOK sign-in may already be in progress, or another"
            f" program holds the port. Close it and try again."
        ) from exc

    server.callback_result = None  # type: ignore[attr-defined]
    # Short, so the serving thread notices `stop` promptly rather than sitting
    # in accept() for the whole timeout after the wait has been abandoned.
    server.timeout = 0.5

    loop = asyncio.get_running_loop()
    done: asyncio.Future = loop.create_future()
    stop = threading.Event()

    def serve() -> None:
        try:
            while not stop.is_set():
                # Returns on timeout with nothing served, which is the tick that
                # lets `stop` be seen.
                server.handle_request()
                if getattr(server, "callback_result", None) is not None:
                    break
        finally:
            server.server_close()
            if not done.done():
                loop.call_soon_threadsafe(
                    lambda: None if done.done() else done.set_result(True)
                )

    thread = threading.Thread(target=serve, daemon=True, name="psok-oauth-callback")
    thread.start()
    try:
        await asyncio.wait_for(asyncio.shield(done), timeout=timeout)
    except (TimeoutError, asyncio.CancelledError) as exc:
        stop.set()
        # Joined, so the next sign-in finds the port free rather than racing a
        # thread that is still shutting down.
        await asyncio.to_thread(thread.join, 3.0)
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise TimeoutError("timed out waiting for the authorization callback") from exc
    finally:
        stop.set()

    result = getattr(server, "callback_result", None)
    if not result or not result.get("code"):
        detail = (result or {}).get("error_description") or (result or {}).get("error")
        raise AuthorizationDenied(f"authorization was not granted: {detail or 'no code returned'}")
    return AuthorizationCodeResult(
        code=result["code"], state=result.get("state"), iss=result.get("iss")
    )


def client_metadata(config: ServerConfig) -> OAuthClientMetadata:
    scope = " ".join(config.oauth_scopes) if config.oauth_scopes else None
    return OAuthClientMetadata(
        client_name=CLIENT_NAME,
        redirect_uris=[REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
        scope=scope,
    )


async def seed_preregistered_client(config: ServerConfig) -> None:
    """Seed a client the user registered themselves, so the SDK skips registration.

    Needed for providers like GitHub that support PKCE but publish no dynamic
    registration endpoint.
    """
    if not config.oauth_client_id:
        return
    storage = KeychainTokenStorage(config.name)
    if await storage.get_client_info():
        return

    secret = get_secret(config.oauth_client_secret_ref) if config.oauth_client_secret_ref else None
    info = OAuthClientInformationFull(
        client_id=config.oauth_client_id,
        client_secret=secret,
        client_name=CLIENT_NAME,
        redirect_uris=[REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="client_secret_post" if secret else "none",
        scope=" ".join(config.oauth_scopes) if config.oauth_scopes else None,
    )
    await storage.set_client_info(info)


class SignInRequired(RuntimeError):
    """The flow reached the point of needing a person, and nobody is there.

    Raised only on a non-interactive connect. A stored token is not enough to
    know this will not happen -- an expired one whose refresh is rejected sends
    the SDK straight back into a full authorization -- so the refusal has to sit
    at the moment the browser would have opened, not at the decision to try.
    """


def build_auth_provider(
    config: ServerConfig,
    *,
    open_browser: bool = True,
    on_authorization_url=None,
    awaiting_user: asyncio.Event | None = None,
    interactive: bool = True,
) -> OAuthClientProvider:
    """Wire the SDK's OAuth client to PSOK's keychain and loopback callback.

    `awaiting_user` is set the moment the flow starts waiting on a person. The
    connect deadline reads it to tell "this server is not answering" apart from
    "this human is still reading the consent screen" -- two failures that look
    identical from the outside and want opposite responses.

    `interactive=False` refuses at that same moment instead. Without it a
    background connect with a stale token sat on the callback for the full
    `auth_timeout_seconds` -- five minutes, holding the one loopback port every
    other sign-in needs, for a browser nobody had opened.
    """
    storage = KeychainTokenStorage(config.name)

    async def redirect_handler(authorization_url: str) -> None:
        if not interactive:
            raise SignInRequired(
                f"'{config.name}' needs signing in again. Open it in Connectors"
                " and press Connect."
            )
        pending = PendingAuthorization(
            server_name=config.name,
            authorization_url=authorization_url,
            state=(parse_qs(urlparse(authorization_url).query).get("state") or [None])[0],
            # The link is only worth offering for as long as this flow is still
            # listening for it.
            ttl_seconds=config.auth_timeout_seconds,
        )
        # Replaces whatever was here. A previous attempt's link is dead the
        # moment a new one is issued -- its state will never be accepted again
        # -- and leaving it listed is how a user ends up clicking the older of
        # two links and being told the state is invalid.
        PENDING[config.name] = pending
        if awaiting_user is not None:
            awaiting_user.set()
        if on_authorization_url is not None:
            await on_authorization_url(authorization_url)
        if open_browser:
            webbrowser.open(authorization_url)

    async def callback_handler() -> AuthorizationCodeResult:
        if not interactive:
            raise SignInRequired(
                f"'{config.name}' needs signing in again. Open it in Connectors"
                " and press Connect."
            )
        try:
            result = await _wait_for_callback(timeout=config.auth_timeout_seconds)
        except TimeoutError:
            if (pending := PENDING.get(config.name)) is not None:
                pending.expire()
            raise
        except AuthorizationDenied as exc:
            # Cancelled or refused at the provider. A distinct outcome from a
            # failure: there is nothing wrong and nothing to debug, the user
            # simply said no.
            if (pending := PENDING.get(config.name)) is not None:
                pending.finish("cancelled", str(exc))
            raise
        except Exception:
            # Leave the record behind saying what happened; the login task
            # replaces the message with the classified cause it can see.
            if (pending := PENDING.get(config.name)) is not None:
                pending.finish("failed", "authorization did not complete")
            raise
        finally:
            if awaiting_user is not None:
                awaiting_user.clear()
        return result

    return OAuthClientProvider(
        server_url=config.url or "",
        client_metadata=client_metadata(config),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


async def _prefer_json_accept(request: httpx2.Request) -> None:
    """Ask for a JSON response body wherever a request doesn't already say otherwise.

    The MCP SDK's OAuth token-exchange and refresh requests carry a
    Content-Type but no Accept header (see mcp/client/auth/oauth2.py's
    `_build_token_request` / `_build_refresh_request`). Per RFC 6749 the token
    endpoint's response format when Accept is unspecified is up to the
    provider, and GitHub's answer is `application/x-www-form-urlencoded`
    (`access_token=...&token_type=bearer&...`) rather than JSON, which fails
    `OAuthToken.model_validate_json`. Every genuine MCP protocol request
    already sets its own explicit "accept" header (see
    streamable_http.py's `_prepare_headers`), so this only ever fills a gap
    left by the OAuth flow -- it never overrides an existing Accept header.
    """
    if "accept" not in request.headers:
        request.headers["accept"] = "application/json"


def mcp_http_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx2.Timeout | None = None,
    auth: httpx2.Auth | None = None,
) -> httpx2.AsyncClient:
    """create_mcp_http_client, plus the Accept-header fix-up above when OAuth is in play."""
    client = create_mcp_http_client(headers=headers, timeout=timeout, auth=auth)
    if auth is not None:
        client.event_hooks["request"].append(_prefer_json_accept)
    return client


def has_tokens(server_name: str) -> bool:
    return bool(get_secret(token_ref(server_name)))


def forget(server_name: str) -> None:
    KeychainTokenStorage(server_name).clear()
