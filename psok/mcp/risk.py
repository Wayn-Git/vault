"""How much a connector's tool is trusted to do without asking first.

Until 2026-08-29 every MCP tool was registered at `RiskLevel.MEDIUM`, on the
reasoning that PSOK cannot inspect what somebody else's server actually does.
The cost of that was not theoretical: with thirteen connectors and 156 of 178
tools coming from them, searching mail, listing tasks and reading a calendar all
raised a confirmation prompt, and the user answered so many that the prompt
stopped carrying information. A gate that fires on everything is a gate nobody
reads.

The premise was also wrong. MCP has carried `annotations` on every tool since
the 2025-03-26 revision -- `readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint` -- and PSOK was discarding the field at discovery. The server
does say what its tools do; nothing was listening.

Two rules, in this order:

1. **What the server declares.** `destructiveHint` is HIGH, `readOnlyHint` is
   LOW, anything else declared is MEDIUM.
2. **What the name says, for the servers that declare nothing** -- which is most
   of them today. A leading `get_`/`list_`/`search_` reads; a leading
   `delete_`/`remove_` destroys.

The name never *lowers* a declaration, only raises it. A server calling
`delete_everything` read-only is either wrong or lying, and neither is a reason
to run it silently; a server that says destructive keeps that rating whatever it
is called.

A tool nothing matches stays MEDIUM, which is the old behaviour: unknown is not
safe, it is unknown.
"""

from __future__ import annotations

from typing import Any

from psok.tools.base import RiskLevel

#: Verbs that read. Deliberately prefixes with a trailing underscore rather than
#: substrings: `list_` matches `list_tasks` and not `blocklist_add`.
READ_PREFIXES = (
    "get_",
    "list_",
    "search_",
    "read_",
    "fetch_",
    "find_",
    "describe_",
    "query_",
    "show_",
    "view_",
    "check_",
    "count_",
    "browser_snapshot",
    "take_snapshot",
)

#: Verbs that destroy. These are HIGH rather than MEDIUM because the prompt for
#: them is the one worth keeping: a write can usually be undone by writing
#: again, and a delete cannot.
DESTRUCTIVE_PREFIXES = (
    "delete_",
    "remove_",
    "drop_",
    "destroy_",
    "purge_",
    "clear_",
    "trash_",
    "revoke_",
    "uninstall_",
    "kill_",
    "close_",
)


def _declared(annotations: dict[str, Any] | None) -> RiskLevel | None:
    """What the server says, or None if it said nothing.

    Both spellings are accepted: the Python SDK models these as snake_case and
    the wire sends camelCase, and a server talking to PSOK through some other
    client library is not the place to find out which one won.
    """
    if not annotations:
        return None

    def flag(*names: str) -> bool:
        return any(bool(annotations.get(name)) for name in names)

    if flag("destructiveHint", "destructive_hint"):
        return RiskLevel.HIGH
    if flag("readOnlyHint", "read_only_hint"):
        return RiskLevel.LOW
    # It annotated *something* -- a title, an idempotency hint -- but said
    # nothing about what the call costs. That is not a claim to be safe.
    return None


def _from_name(name: str) -> RiskLevel | None:
    lowered = (name or "").lower()
    if lowered.startswith(DESTRUCTIVE_PREFIXES):
        return RiskLevel.HIGH
    if lowered.startswith(READ_PREFIXES):
        return RiskLevel.LOW
    return None


def classify(name: str, annotations: dict[str, Any] | None = None) -> RiskLevel:
    """The risk tier for one MCP tool.

    `name` is the tool's own name as its server calls it, not PSOK's registry
    key -- the key carries a `__mcp__<server>` suffix that no prefix rule should
    have to know about.
    """
    declared = _declared(annotations)
    guessed = _from_name(name)

    if declared is None:
        return guessed or RiskLevel.MEDIUM
    if guessed is RiskLevel.HIGH:
        # The name contradicts the annotation upwards. Believe the worse of the
        # two: a mistaken prompt costs a keystroke, a mistaken deletion does not.
        return RiskLevel.HIGH
    return declared
