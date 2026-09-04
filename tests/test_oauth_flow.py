"""The OAuth sign-in flow, end to end.

The bug these were written against was reported as
"Invalid or expired OAuth state parameter" -- a message from the *provider*,
which made it look like a Google problem. It was not. Five defects in PSOK
could each destroy or outlive a state that was minted correctly, and the
provider's refusal was the honest downstream consequence of every one.

Nothing here weakens state validation. The SDK compares state with
`secrets.compare_digest` and must go on doing so; these tests are about the
state surviving long enough to be compared.
"""

from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest
from conftest import GOOGLE_CLIENT_ID, GOOGLE_SECRET, GOOGLE_SECRET_ROTATED

from backend.mcp import catalogue as cat
from backend.mcp import commands as mcp_commands
from backend.mcp.config import load_servers
from backend.mcp.oauth import (
    AUTHORIZATION_LINK_TTL_SECONDS,
    CALLBACK_HOST,
    CALLBACK_PORT,
    PENDING,
    AuthorizationDenied,
    PendingAuthorization,
    prune_finished,
)


@pytest.fixture(autouse=True)
def clean_pending():
    PENDING.clear()
    yield
    PENDING.clear()


# --- the root cause: sign-out destroyed a sign-in in progress ---------------


def test_signing_out_preserves_another_flows_oauth_state(psok_home, monkeypatch):
    """The direct cause of "Invalid or expired OAuth state parameter".

    Nine Google connectors share one credentials directory, and
    `oauth_states.json` in it is workspace-mcp's CSRF store. Sign-out used to
    `rmtree` the directory, so signing out of Gmail -- or `login(force=True)`,
    which signs out first -- deleted the state a Calendar sign-in was about to
    have checked. The user finished a perfectly good login and was told their
    state was invalid.

    Mutation check: restore `shutil.rmtree(directory)` and this fails.
    """
    mcp_commands.add_from_catalogue("google-gmail")
    mcp_commands.add_from_catalogue("google-calendar")
    shared = psok_home / "google-credentials"
    shared.mkdir()
    for name in ("google-gmail", "google-calendar"):
        monkeypatch.setattr(cat.get(name), "credentials_path", str(shared), raising=False)

    # Calendar's sign-in is in flight: its state is in the shared store.
    (shared / "oauth_states.json").write_text(json.dumps({"abc123": {"session_id": "cal"}}))
    (shared / "someone@gmail.com.json").write_text("{}")

    mcp_commands.sign_out("google-gmail")

    assert not (shared / "someone@gmail.com.json").exists(), "the account must go"
    states = json.loads((shared / "oauth_states.json").read_text())
    assert "abc123" in states, "the other sign-in's state must survive"


def test_force_login_would_have_wiped_state_too(psok_home, monkeypatch):
    """`force` signs out first, so "switch account" had the same effect."""
    mcp_commands.add_from_catalogue("google-drive")
    shared = psok_home / "creds"
    shared.mkdir()
    monkeypatch.setattr(cat.get("google-drive"), "credentials_path", str(shared), raising=False)
    (shared / "oauth_states.json").write_text('{"live": {}}')

    mcp_commands.sign_out("google-drive")
    assert json.loads((shared / "oauth_states.json").read_text()) == {"live": {}}


def test_sign_out_still_clears_everything_that_is_not_in_flight(psok_home, monkeypatch):
    """The fix must not turn sign-out into a no-op."""
    mcp_commands.add_from_catalogue("linkedin")
    profile = psok_home / "profile"
    (profile / "Default" / "Storage").mkdir(parents=True)
    (profile / "Default" / "Storage" / "leveldb").write_bytes(b"x")
    (profile / "Cookies").write_bytes(b"session")
    monkeypatch.setattr(cat.get("linkedin"), "credentials_path", str(profile), raising=False)

    mcp_commands.sign_out("linkedin")

    assert not (profile / "Default").exists()
    assert not (profile / "Cookies").exists()
    assert mcp_commands.is_signed_in(load_servers()["linkedin"]) is False


# --- a published link must not outlive the state behind it ------------------


def test_a_stale_link_is_not_offered():
    """The screenshot's "2 sign-ins waiting" offered two links that could only fail.

    A `waiting` entry is not evidence anything is waiting: the state behind it
    expires (five minutes for PSOK's own flow, ten for workspace-mcp), and the
    process holding it may be long gone. Clicking one produced exactly the
    reported error.

    Mutation check: make `live` return `self.status == "waiting"` and this fails.
    """
    fresh = PendingAuthorization(server_name="github", authorization_url="https://x/")
    assert fresh.live is True

    stale = PendingAuthorization(server_name="google-calendar", authorization_url="https://y/")
    stale.started_at = (
        datetime.now(UTC) - timedelta(seconds=AUTHORIZATION_LINK_TTL_SECONDS + 30)
    ).isoformat(timespec="seconds")
    assert stale.live is False


def test_pruning_expires_a_dead_link_rather_than_leaving_it_waiting():
    stale = PendingAuthorization(server_name="google-docs", authorization_url="https://y/")
    stale.started_at = (datetime.now(UTC) - timedelta(hours=2)).isoformat(timespec="seconds")
    PENDING["google-docs"] = stale

    prune_finished()

    assert PENDING["google-docs"].status == "expired"
    assert "again" in PENDING["google-docs"].message
    assert PENDING["google-docs"].live is False


def test_a_finished_outcome_is_kept_briefly_then_dropped():
    done = PendingAuthorization(server_name="vercel", authorization_url="https://z/")
    done.finish("done", "signed in")
    PENDING["vercel"] = done

    prune_finished()
    assert "vercel" in PENDING, "the interface has to be able to see the outcome"

    done.finished_at = (datetime.now(UTC) - timedelta(minutes=10)).isoformat(timespec="seconds")
    prune_finished()
    assert "vercel" not in PENDING


def test_a_new_attempt_supersedes_the_previous_link():
    """Two live links for one server means the user can click the dead one."""
    first = PendingAuthorization(server_name="github", authorization_url="https://first/")
    PENDING["github"] = first
    PENDING["github"] = PendingAuthorization(
        server_name="github", authorization_url="https://second/"
    )

    assert len(PENDING) == 1
    assert PENDING["github"].authorization_url == "https://second/"


# --- the loopback callback --------------------------------------------------


def _get(path: str, timeout: float = 5.0) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed loopback URL
            f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{path}", timeout=timeout
        ) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.mark.asyncio
async def test_a_stray_request_does_not_consume_the_callback():
    """`handle_request()` served exactly one request, whatever it was.

    A browser asking for /favicon.ico ended the wait, and the real redirect then
    found nothing listening -- so the code was never exchanged and the sign-in
    failed for a reason nothing reported.

    Mutation check: replace the serve loop with a single `handle_request()` and
    this hangs until the timeout.
    """
    from backend.mcp.oauth import _wait_for_callback

    waiter = asyncio.create_task(_wait_for_callback(timeout=15.0))
    await asyncio.sleep(0.4)

    status, _ = await asyncio.to_thread(_get, "/favicon.ico")
    assert status == 404, "a stray request is answered, not treated as the callback"
    assert not waiter.done(), "and the wait carries on"

    await asyncio.to_thread(_get, "/oauth/callback?code=abc&state=xyz")
    result = await asyncio.wait_for(waiter, timeout=5)
    assert result.code == "abc"
    assert result.state == "xyz", "the state must survive the round trip untouched"


@pytest.mark.asyncio
async def test_the_callback_port_is_free_again_immediately_after_a_timeout():
    """An abandoned wait held the fixed port for its whole timeout.

    Every retry then failed with "another PSOK sign-in may already be in
    progress" -- so one abandoned attempt blocked sign-in for five minutes.

    Mutation check: drop the `stop` event and the join, and the second wait
    raises CallbackPortUnavailable.
    """
    from backend.mcp.oauth import _wait_for_callback

    with pytest.raises(TimeoutError):
        await _wait_for_callback(timeout=0.6)

    # Straight back in, on the same fixed port.
    retry = asyncio.create_task(_wait_for_callback(timeout=10.0))
    await asyncio.sleep(0.4)
    await asyncio.to_thread(_get, "/oauth/callback?code=second&state=s2")
    result = await asyncio.wait_for(retry, timeout=5)
    assert result.code == "second"


@pytest.mark.asyncio
async def test_a_denied_authorization_is_its_own_outcome():
    """Cancelling at the provider is not a failure to debug."""
    from backend.mcp.oauth import _wait_for_callback

    waiter = asyncio.create_task(_wait_for_callback(timeout=10.0))
    await asyncio.sleep(0.4)
    await asyncio.to_thread(_get, "/oauth/callback?error=access_denied&error_description=No")

    with pytest.raises(AuthorizationDenied) as caught:
        await asyncio.wait_for(waiter, timeout=5)
    assert "No" in str(caught.value)


@pytest.mark.asyncio
async def test_two_flows_cannot_read_each_others_redirect():
    """The result used to be a class attribute, shared by every flow at once.

    One flow's `result = None` reset could erase a redirect another was about to
    read, and each could consume the other's code -- which state validation then
    correctly rejected, for a code that was perfectly valid.

    Mutation check: put `callback_result` back on the class and the second wait
    sees the first's code.
    """
    from backend.mcp.oauth import _wait_for_callback

    first = asyncio.create_task(_wait_for_callback(timeout=10.0))
    await asyncio.sleep(0.4)
    await asyncio.to_thread(_get, "/oauth/callback?code=first&state=one")
    assert (await asyncio.wait_for(first, timeout=5)).code == "first"

    second = asyncio.create_task(_wait_for_callback(timeout=10.0))
    await asyncio.sleep(0.4)
    await asyncio.to_thread(_get, "/oauth/callback?code=second&state=two")
    result = await asyncio.wait_for(second, timeout=5)
    assert result.code == "second", "no leakage from the flow before it"
    assert result.state == "two"


@pytest.mark.asyncio
async def test_the_callback_page_is_not_cached():
    """The URL that renders it carries an authorization code."""
    from backend.mcp.oauth import _wait_for_callback

    waiter = asyncio.create_task(_wait_for_callback(timeout=10.0))
    await asyncio.sleep(0.4)

    def fetch() -> dict:
        with urllib.request.urlopen(  # noqa: S310 - fixed loopback URL
            f"http://{CALLBACK_HOST}:{CALLBACK_PORT}/oauth/callback?code=c&state=s", timeout=5
        ) as response:
            return dict(response.headers)

    headers = await asyncio.to_thread(fetch)
    await asyncio.wait_for(waiter, timeout=5)
    assert headers.get("Cache-Control") == "no-store"
    assert headers.get("Referrer-Policy") == "no-referrer"


# --- state validation is never bypassed -------------------------------------


def test_the_sdk_still_compares_state_in_constant_time():
    """The fix must not have made CSRF protection optional.

    If this file ever stops finding the comparison, state validation has been
    removed or moved and this flow is no longer protected.
    """
    import inspect

    from mcp.client.auth import oauth2

    source = inspect.getsource(oauth2)
    assert "compare_digest(result.state, state)" in source
    assert "State parameter mismatch" in source


def test_psok_never_logs_a_code_or_a_token():
    """The callback URL carries a code; the handler must stay quiet about it."""
    import inspect

    from backend.mcp import oauth

    source = inspect.getsource(oauth)
    assert "def log_message" in source, "the default handler logs every request line"
    # The one place a code could reach a log is the handler's own logging, and
    # http.server's default writes the whole request line -- query string
    # included, which is where the code is.
    handler = source[source.index("class _CallbackHandler") : source.index("class CallbackPort")]
    body = handler.split("def log_message")[1]
    statements = [line.strip() for line in body.splitlines()[1:] if line.strip()]
    assert statements[:1] == ["return"], "log_message must be a no-op"


# --- one provider cannot disturb another ------------------------------------


def test_each_server_has_its_own_pending_slot():
    PENDING["github"] = PendingAuthorization(server_name="github", authorization_url="https://g/")
    PENDING["vercel"] = PendingAuthorization(server_name="vercel", authorization_url="https://v/")
    PENDING["github"].finish("failed", "no client id")

    assert PENDING["vercel"].status == "waiting"
    assert PENDING["vercel"].live is True


def test_tokens_are_keyed_per_server():
    from backend.mcp.oauth import client_ref, token_ref

    assert token_ref("github") != token_ref("vercel")
    assert client_ref("github") != client_ref("vercel")


def test_the_link_ttl_matches_the_flow_that_issues_it(psok_home):
    """A link offered for longer than the flow listens is a link that fails."""
    from backend.mcp.oauth import CALLBACK_TIMEOUT_SECONDS

    mcp_commands.add_from_catalogue("github")
    config = load_servers()["github"]
    assert config.auth_timeout_seconds == CALLBACK_TIMEOUT_SECONDS
    assert AUTHORIZATION_LINK_TTL_SECONDS <= CALLBACK_TIMEOUT_SECONDS


def test_no_callback_threads_are_left_behind():
    """A leaked serving thread holds the port and blocks the next sign-in."""
    leaked = [t for t in threading.enumerate() if t.name == "psok-oauth-callback"]
    assert leaked == [], f"left running: {leaked}"


# --- the client credential itself -------------------------------------------

GOOGLE_SECRET = GOOGLE_SECRET


def test_one_google_secret_is_shared_rather_than_copied_nine_times(psok_home):
    """The catalogue promises "you only do this once — every Google app then
    shares it", and the storage did the opposite.

    Each connector kept its own keychain entry, so regenerating a secret and
    pasting it on the Calendar panel left the other eight on the old value.
    Calendar then worked and Gmail failed at token exchange with Google's
    `(invalid_client) The provided client secret is invalid` -- a stale copy of
    a credential the user believed they had already replaced.

    Mutation check: make `_sharing_account_with` return [] and the siblings are
    never written to, so only the connector that was edited has the credential.
    """
    for app in ("google-gmail", "google-calendar", "google-drive"):
        mcp_commands.add_from_catalogue(app)
    mcp_commands.add_from_catalogue("github")

    mcp_commands.set_env(
        "google-calendar", "GOOGLE_OAUTH_CLIENT_SECRET", GOOGLE_SECRET, secret=True
    )

    servers = load_servers()
    refs = {
        app: servers[app].env["GOOGLE_OAUTH_CLIENT_SECRET"]
        for app in ("google-gmail", "google-calendar", "google-drive")
    }
    assert len(set(refs.values())) == 1, f"one credential, one reference: {refs}"
    for app in refs:
        assert servers[app].resolved_env()["GOOGLE_OAUTH_CLIENT_SECRET"] == GOOGLE_SECRET

    # A connector with its own account is never written to by somebody else's.
    assert "GOOGLE_OAUTH_CLIENT_SECRET" not in servers["github"].env


def test_updating_the_shared_secret_reaches_every_sibling(psok_home):
    """The actual failure mode: rotate the secret, and the others stay stale.

    Propagation is what carries this: the connector being edited writes its
    reference onto every sibling, so the next read follows it. The group key in
    `env_secret_ref` is a naming choice on top of that -- one entry called
    `psok-mcp/google.env.…` rather than one arbitrarily named after whichever
    connector happened to be edited first -- and is deliberately not what makes
    this pass.
    """
    for app in ("google-gmail", "google-calendar"):
        mcp_commands.add_from_catalogue(app)

    mcp_commands.set_env(
        "google-gmail", "GOOGLE_OAUTH_CLIENT_SECRET", GOOGLE_SECRET, secret=True
    )
    rotated = GOOGLE_SECRET_ROTATED
    # `force` because a stored credential is not editable from a casual surface
    # -- see test_a_stored_credential_is_not_editable_from_the_connectors_menu.
    mcp_commands.set_env(
        "google-calendar", "GOOGLE_OAUTH_CLIENT_SECRET", rotated, secret=True, force=True
    )

    servers = load_servers()
    for app in ("google-gmail", "google-calendar"):
        assert servers[app].resolved_env()["GOOGLE_OAUTH_CLIENT_SECRET"] == rotated


@pytest.mark.parametrize(
    ("value", "because"),
    [
        ("", "empty"),
        ("   ", "whitespace only"),
        ("GOCSPX" + "-" + "abcdefghijklmnopqrstuvwxyz12 ", "trailing space from a copy"),
        (GOOGLE_CLIENT_ID, "the client id, not the secret"),
        ("GOCSPX" + "-" + "abcdefghijklmnopqrstuvwxyz1", "one character short"),
    ],
)
def test_a_credential_that_cannot_be_right_is_refused_at_entry(psok_home, value, because):
    """Caught on save, not five minutes later by the provider.

    The reported failure was a 34-character secret where Google issues 35 -- a
    clipped copy. Stored happily, it survived until the end of a sign-in and
    came back as `invalid_client` from a browser tab PSOK cannot see.

    Mutation check: delete the length and prefix checks and the last two cases
    are accepted.
    """
    mcp_commands.add_from_catalogue("google-gmail")
    with pytest.raises(ValueError):
        mcp_commands.set_env(
            "google-gmail", "GOOGLE_OAUTH_CLIENT_SECRET", value, secret=True
        )


def test_a_well_formed_secret_is_accepted(psok_home):
    """The check must reject only what is certainly wrong."""
    mcp_commands.add_from_catalogue("google-gmail")
    config = mcp_commands.set_env(
        "google-gmail", "GOOGLE_OAUTH_CLIENT_SECRET", GOOGLE_SECRET, secret=True
    )
    assert config.resolved_env()["GOOGLE_OAUTH_CLIENT_SECRET"] == GOOGLE_SECRET


def test_the_secret_is_never_written_to_the_config_file(psok_home):
    from backend.mcp.config import config_path

    mcp_commands.add_from_catalogue("google-gmail")
    mcp_commands.set_env(
        "google-gmail", "GOOGLE_OAUTH_CLIENT_SECRET", GOOGLE_SECRET, secret=True
    )
    assert GOOGLE_SECRET not in config_path().read_text()


@pytest.mark.asyncio
async def test_the_google_preflight_reads_the_providers_verdict(monkeypatch, psok_home):
    """`invalid_client` means the credentials are wrong; `invalid_grant` means
    they are right and only the deliberately-bogus code was bad.

    Google checks the client before the code, which is what makes a throwaway
    code a safe probe.
    """
    import httpx2

    mcp_commands.add_from_catalogue("google-calendar")
    mcp_commands.set_env(
        "google-calendar", "GOOGLE_OAUTH_CLIENT_ID", GOOGLE_CLIENT_ID
    )
    mcp_commands.set_env(
        "google-calendar", "GOOGLE_OAUTH_CLIENT_SECRET", GOOGLE_SECRET, secret=True
    )
    config = load_servers()["google-calendar"]

    def answer(body):
        async def post(self, *a, **k):
            class R:
                def json(self):
                    return body
            return R()
        monkeypatch.setattr(httpx2.AsyncClient, "post", post)

    answer({"error": "invalid_grant", "error_description": "Bad Request"})
    assert await mcp_commands.check_google_client(config) is None, "good client, bad code"

    answer(
        {"error": "invalid_client", "error_description": "The provided client secret is invalid."}
    )
    problem = await mcp_commands.check_google_client(config)
    assert problem is not None and "secret" in problem.lower()
    assert "console.cloud.google.com" in problem, "it has to say where to fix it"

    answer({"error": "invalid_client", "error_description": "The OAuth client was not found."})
    problem = await mcp_commands.check_google_client(config)
    assert problem is not None and "client id" in problem.lower()


@pytest.mark.asyncio
async def test_an_unreachable_google_never_blocks_a_sign_in(monkeypatch, psok_home):
    """A network problem is not a bad credential, and must not read as one."""
    import httpx2

    mcp_commands.add_from_catalogue("google-calendar")
    mcp_commands.set_env(
        "google-calendar", "GOOGLE_OAUTH_CLIENT_ID", GOOGLE_CLIENT_ID
    )
    mcp_commands.set_env(
        "google-calendar", "GOOGLE_OAUTH_CLIENT_SECRET", GOOGLE_SECRET, secret=True
    )

    async def boom(self, *a, **k):
        raise OSError("network unreachable")

    monkeypatch.setattr(httpx2.AsyncClient, "post", boom)
    config = load_servers()["google-calendar"]
    assert await mcp_commands.check_google_client(config) is None


@pytest.mark.asyncio
async def test_missing_credentials_are_named_before_anything_opens(psok_home):
    mcp_commands.add_from_catalogue("google-calendar")
    config = load_servers()["google-calendar"]
    config.env.pop("GOOGLE_OAUTH_CLIENT_SECRET", None)
    problem = await mcp_commands.check_google_client(config)
    assert problem is not None and "client secret" in problem


# --- abandoning and self-healing --------------------------------------------


def test_a_waiting_card_for_a_signed_in_connector_corrects_itself(psok_home, monkeypatch):
    """A card saying "finish signing in" for a connector that is already signed
    in is wrong, and the user cannot dismiss it.

    It happens whenever a sign-in lands by a route the watcher did not see.
    Mutation check: remove the self-heal from the authorizations endpoint and
    the entry stays `waiting`.
    """
    from fastapi.testclient import TestClient

    from backend.api.main import app

    mcp_commands.add_from_catalogue("microsoft-todo")
    cache = psok_home / "todo-cache.json"
    monkeypatch.setattr(
        cat.get("microsoft-todo"), "credentials_path", str(cache), raising=False
    )
    cache.write_text('{"accessToken": "x"}')  # signed in, by whatever route

    PENDING["microsoft-todo"] = PendingAuthorization(
        server_name="microsoft-todo", authorization_url="https://microsoft.com/devicelogin"
    )

    with TestClient(app) as client:
        rows = client.get("/api/mcp/authorizations").json()

    row = next(r for r in rows if r["server"] == "microsoft-todo")
    assert row["status"] == "done"


def test_cancelling_a_sign_in_clears_it(psok_home):
    """Closing the browser tab is how most abandoned sign-ins end, and nothing
    told PSOK -- so the card, and a whole subprocess behind it, stayed until the
    deadline passed."""
    from fastapi.testclient import TestClient

    from backend.api.main import app

    mcp_commands.add_from_catalogue("github")
    PENDING["github"] = PendingAuthorization(
        server_name="github", authorization_url="https://github.com/login/oauth/authorize"
    )

    with TestClient(app) as client:
        response = client.request("DELETE", "/api/mcp/servers/github/login")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert client.get("/api/mcp/authorizations").json() == []


def test_a_device_code_reaches_the_interface(psok_home):
    """The code has to survive as far as something that can render it."""
    from fastapi.testclient import TestClient

    from backend.api.main import app

    mcp_commands.add_from_catalogue("microsoft-todo")
    pending = PendingAuthorization(
        server_name="microsoft-todo",
        authorization_url="https://microsoft.com/devicelogin",
        user_code="A1B2C3D4",
        instructions="Open the page and enter the code A1B2C3D4",
    )
    PENDING["microsoft-todo"] = pending

    with TestClient(app) as client:
        row = next(
            r for r in client.get("/api/mcp/authorizations").json()
            if r["server"] == "microsoft-todo"
        )
    assert row["user_code"] == "A1B2C3D4"
    assert "A1B2C3D4" in row["instructions"]


# --- a working credential is not editable from a casual surface -------------


def test_a_stored_secret_is_not_editable_from_the_connectors_menu(psok_home):
    """One OAuth client backs every connector in an account group.

    Overwriting it is not a per-connector edit: it takes all of them down at
    once, and the only symptom is the provider refusing to exchange a token at
    the *end* of a sign-in -- a long way from the text field that caused it.
    Replacing one is a deliberate act and needs a deliberate surface.

    Mutation check: drop the `_guard_stored_credential` call from `set_env` and
    the second write is accepted.
    """
    mcp_commands.add_from_catalogue("google-gmail")
    mcp_commands.set_env(
        "google-gmail", "GOOGLE_OAUTH_CLIENT_SECRET", GOOGLE_SECRET, secret=True
    )

    replacement = "GOCSPX" + "-" + "999999999999999999999999zzzz"
    with pytest.raises(mcp_commands.CredentialLocked) as caught:
        mcp_commands.set_env(
            "google-gmail", "GOOGLE_OAUTH_CLIENT_SECRET", replacement, secret=True
        )
    assert "--force" in str(caught.value), "it has to say how to do it deliberately"

    servers = load_servers()
    assert servers["google-gmail"].resolved_env()["GOOGLE_OAUTH_CLIENT_SECRET"] == GOOGLE_SECRET


def test_the_deliberate_path_still_works(psok_home):
    mcp_commands.add_from_catalogue("google-gmail")
    mcp_commands.set_env(
        "google-gmail", "GOOGLE_OAUTH_CLIENT_SECRET", GOOGLE_SECRET, secret=True
    )
    rotated = GOOGLE_SECRET_ROTATED
    mcp_commands.set_env(
        "google-gmail", "GOOGLE_OAUTH_CLIENT_SECRET", rotated, secret=True, force=True
    )
    assert load_servers()["google-gmail"].resolved_env()["GOOGLE_OAUTH_CLIENT_SECRET"] == rotated


def test_a_public_client_id_is_still_editable(psok_home):
    """The guard is about the secret. A client id is a public identifier, and
    refusing to correct one would be friction with nothing behind it."""
    mcp_commands.add_from_catalogue("google-gmail")
    mcp_commands.set_env("google-gmail", "GOOGLE_OAUTH_CLIENT_ID", GOOGLE_CLIENT_ID)
    mcp_commands.set_env("google-gmail", "GOOGLE_OAUTH_CLIENT_ID", "other-" + GOOGLE_CLIENT_ID)
    env = load_servers()["google-gmail"].env
    assert env["GOOGLE_OAUTH_CLIENT_ID"] == "other-" + GOOGLE_CLIENT_ID


def test_the_first_credential_is_never_refused(psok_home):
    """Locking must not lock someone out of setting one up."""
    mcp_commands.add_from_catalogue("google-gmail")
    config = mcp_commands.set_env(
        "google-gmail", "GOOGLE_OAUTH_CLIENT_SECRET", GOOGLE_SECRET, secret=True
    )
    assert config.resolved_env()["GOOGLE_OAUTH_CLIENT_SECRET"] == GOOGLE_SECRET


def test_the_api_refuses_and_offers_no_way_round_it(psok_home):
    """Hiding the input is not enough: the endpoint has to refuse too, or the
    credential is still manipulable by anything that can reach the API."""
    from fastapi.testclient import TestClient

    from backend.api.main import app

    mcp_commands.add_from_catalogue("google-gmail")
    mcp_commands.set_env(
        "google-gmail", "GOOGLE_OAUTH_CLIENT_SECRET", GOOGLE_SECRET, secret=True
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/mcp/servers/google-gmail/env",
            json={
                "key": "GOOGLE_OAUTH_CLIENT_SECRET",
                "value": "GOCSPX" + "-" + "111111111111111111111111aaaa",
                "secret": True,
                # Not a parameter the endpoint accepts; asking for it changes nothing.
                "force": True,
            },
        )
        assert response.status_code == 409
        assert "not editable from here" in response.json()["detail"]

        oauth = client.post(
            "/api/mcp/servers/google-gmail/oauth-client",
            json={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": "GOCSPX" + "-" + "222222222222222222222222bbbb",
            },
        )
        assert oauth.status_code == 409

    assert load_servers()["google-gmail"].resolved_env()[
        "GOOGLE_OAUTH_CLIENT_SECRET"
    ] == GOOGLE_SECRET
