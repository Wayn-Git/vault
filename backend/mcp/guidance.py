"""What the model is told when a connector cannot do the job.

This is the fix for the bug that started the whole connector audit. A Google
connector that had never completed OAuth still put fifteen Gmail tools in front
of the model. The model called one, got `Connection closed` back, concluded
there was a service outage, and handed the work back to the user -- who could
see Gmail working perfectly in their browser.

Two separate mistakes, so two separate fixes:

* **A tool that cannot work is not offered.** `connected` is not `signed in`: a
  stdio server starts, registers its tools and answers `initialize` long before
  anybody has attached an account to it. Withholding those schemas is what stops
  the model spending a turn on them, and `BASE_PROMPT` saying "errors are
  information" cannot help once the call has already been made.
* **When something does fail, the message is an instruction.** The model used to
  see a raw exception string, which names no connector, no screen and no button,
  and so cannot be acted on or relayed. Every message here says what broke, what
  to do about it, and -- crucially -- *not to retry*, because retrying is what
  turned one dead connector into a turn that spent its whole iteration budget.

The wording lives in one module so the tool result, the dispatch guard and the
prompt cannot drift into describing three different user interfaces.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

#: Where a person fixes any of this. One string, because an instruction that
#: names the wrong screen is worse than one that names none.
CONNECTORS_SCREEN = "Skills & connectors (Cmd/Ctrl+3), Connectors tab"

#: `is_signed_in` globs a credentials directory and parses JSON, and dispatch
#: asks once per tool call. Short enough that pressing Connect is noticed within
#: a turn, long enough that a fifteen-call turn does not stat the disk fifteen
#: times per connector.
CACHE_TTL_SECONDS = 5.0

_cache: tuple[float, frozenset[str]] | None = None


def forget() -> None:
    """Drop the cache, so a sign-in that just landed is believed at once."""
    global _cache
    _cache = None


def unsigned_connectors() -> frozenset[str]:
    """Configured connectors that are running but have no account attached.

    `is_signed_in` returns `None` for a connector with nothing to sign in to,
    which is not the same as `False` and must not hide anything -- the fetch
    connector needs no account and works fine without one.
    """
    global _cache
    now = time.monotonic()
    if _cache is not None and now < _cache[0]:
        return _cache[1]

    try:
        from backend.mcp import commands as mcp
        from backend.mcp.config import load_servers

        names = frozenset(
            name
            for name, config in load_servers().items()
            if config.enabled and mcp.is_signed_in(config) is False
        )
    except Exception as exc:
        # Failing open matches `_connector_enabled`: this is a usefulness
        # judgement, not a security boundary. The permission gate is the
        # boundary and it runs regardless.
        log.debug("could not read connector sign-in state, advertising all: %s", exc)
        names = frozenset()

    _cache = (now + CACHE_TTL_SECONDS, names)
    return names


def sign_in_instruction(server_name: str) -> str:
    """Told to the model when it names a tool of a connector nobody signed in to.

    It should reach the model rarely -- the schemas are withheld -- but a model
    can name a tool it saw in an earlier turn, and the connection is shared with
    every other conversation.
    """
    return (
        f"'{server_name}' is running but no account is signed in to it, so none of its"
        " tools can work yet. This is not an outage and not a bug: it is a setup step"
        " only the user can complete."
        f" Tell them to open {CONNECTORS_SCREEN}, open the '{server_name}' row and press"
        " Connect. Do not retry this tool. Finish everything else the request needs and"
        " say plainly which part is waiting on that sign-in."
    )


def not_connected_instruction(server_name: str) -> str:
    """Told to the model when the server is configured but not running."""
    return (
        f"'{server_name}' is not running, so its tools are unavailable."
        f" Tell the user to open {CONNECTORS_SCREEN}, open the '{server_name}' row and"
        " press Connect. Do not retry this tool. Do the rest of the task without it and"
        " say what you could not do."
    )


def dropped_instruction(server_name: str, detail: str) -> str:
    """Told to the model when a live connection died and would not come back."""
    return (
        f"'{server_name}' lost its connection during this call and could not be"
        f" restarted ({detail})."
        f" Tell the user to open {CONNECTORS_SCREEN}, open the '{server_name}' row and"
        " press Reconnect — or Connect, if it asks them to sign in again."
        " Do not retry this tool. Do the rest of the task without it and say what you"
        " could not do."
    )
