"""One state per connector, derived in one place.

Setting a connector up was a scavenger hunt. The Connectors tab showed
`enabled`, `signed_in`, `missing_credentials`, an error string and a separate
pending-authorization poll, and left the reader to work out from those five
whether anything more was needed and what. Every screen that asked the question
answered it slightly differently, which is how a connector reporting 122 tools
live ended up sitting beside a "Sign in" button.

So the states are named, ordered, and computed here — not in JSX, so the API,
the interface and the CLI cannot disagree, and so the derivation is testable
without a browser.

    Adding -> Setting up -> Authenticating -> Syncing -> Ready
                                           \\-> Failed (with a reason and a Retry)

Each state carries `action`: the single thing that moves it forward, or None
where the answer is "wait". A state with no next action and no explanation is
what made the old screen unanswerable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

#: Connectors whose setup is not finished when the tools appear. Microsoft To Do
#: mirrors into the local tasks table, and until the first pull has run the
#: Tasks page is empty while the connector claims to be ready -- which reads as
#: the sync being broken rather than as never having been asked to run.
FIRST_SYNC: dict[str, str] = {"microsoft-todo": "tasks"}


@dataclass(frozen=True)
class ConnectorState:
    #: Machine-readable, stable. The interface keys styling off this.
    state: str
    #: One sentence for a person. Never an exception string on its own.
    detail: str
    #: What moves it forward: connect, sign_in, credentials, sync, retry, or
    #: None when the only correct thing to do is wait.
    action: str | None = None
    #: Whether this connector can be used right now.
    ready: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def state_of(
    row: dict[str, Any],
    *,
    pending: dict[str, Any] | None = None,
    live: dict[str, Any] | None = None,
    synced: bool = True,
    reconciled: bool = True,
) -> ConnectorState:
    """Where this connector is in its setup.

    `row` is one entry from `commands.status()`; `pending` its entry from
    `GET /api/mcp/authorizations` if it has one; `live` its entry from
    `MCPManager.state()`. Everything is optional because the CLI has no manager
    and the catalogue view has no poll -- a partial answer beats a screen that
    refuses to say anything until every source has reported.

    The order of the checks is the whole design. A connector mid sign-in is
    *authenticating* even though it is also not connected and also has no
    account; reporting the deepest unmet requirement rather than the first one
    found is what stops the screen saying "not connected" at someone who is
    looking at a consent page.
    """
    name = row.get("name", "")
    pending = pending or {}
    live = live or {}

    if not row.get("enabled", True):
        return ConnectorState("off", "Switched off.", action="connect")

    # A sign-in in flight outranks everything: the user is at the provider, and
    # every other fact about this connector is temporarily meaningless.
    status = pending.get("status")
    if status == "waiting":
        return ConnectorState(
            "authenticating",
            "Waiting for you to finish signing in with the provider.",
            action=None,
        )
    if status == "failed":
        return ConnectorState(
            "failed",
            pending.get("message") or "The sign-in did not complete.",
            action="retry",
        )

    # Credentials the server needs before its own flow can even start. Named
    # rather than counted: "needs 2 credentials" is not something anyone can act
    # on without going and finding out which two.
    missing = row.get("missing_credentials") or []
    if missing:
        return ConnectorState(
            "setup",
            f"Needs {_join(missing)} before it can sign in.",
            action="credentials",
        )

    if row.get("signed_in") is False:
        return ConnectorState(
            "sign_in",
            "Running, but no account is signed in — its tools are withheld until one is.",
            action="sign_in",
        )

    error = live.get("error")
    if error:
        return ConnectorState("failed", _readable(name, error), action="retry")

    if not live.get("connected"):
        if not reconciled:
            # Nothing has asked it to start yet. Distinct from failing to start,
            # and they used to render identically -- so on a freshly booted
            # server every connector looked broken.
            return ConnectorState("starting", "Not started yet.", action="connect")
        return ConnectorState("failed", "Not running.", action="connect")

    if name in FIRST_SYNC and not synced:
        return ConnectorState(
            "syncing",
            f"Signed in. Its {FIRST_SYNC[name]} have not been pulled in yet.",
            action="sync",
        )

    tools = live.get("tools") or 0
    return ConnectorState("ready", f"Ready, {tools} tool{'' if tools == 1 else 's'}.", ready=True)


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _readable(name: str, error: str) -> str:
    """A failure a person can act on, from a string a library wrote.

    The raw text is kept -- it is the only diagnostic there is -- but the common
    cases are recognised and led with, because "SignInRequired" and
    "[Errno 111] Connection refused" are both true and neither says what to do.
    """
    lowered = error.lower()
    if "signinrequired" in lowered or "signed in" in lowered:
        return f"Needs you to sign in. ({error})"
    if "enoent" in lowered or "not found" in lowered:
        return f"Its command could not be found — check it is installed. ({error})"
    if "refused" in lowered or "unreachable" in lowered:
        return f"Nothing answered at its address. ({error})"
    return f"{name} did not start. ({error})"
