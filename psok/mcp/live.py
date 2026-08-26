"""The MCP manager this process is actually running, reachable without the API.

The manager is owned by whatever built the tool registry -- the API for a served
turn, the CLI for a chat session. Anything else that needs a connector has to be
handed one, which was fine while only the API needed it, and stopped being fine
the moment a builtin tool wanted to reach a connected server: a tool cannot
import the API, and spawning a second copy of a stdio server would mean a second
process and a second sign-in.

So the owner publishes it here and everything else asks. Deliberately a single
value rather than a registry of managers: PSOK is one user's process with one
set of connections (ADR-0001), and pretending otherwise would invent a concept
nothing needs.
"""

from __future__ import annotations

from typing import Any

_manager: Any | None = None


def set_manager(manager: Any | None) -> None:
    """Publish the manager for this process. Called when the registry is built."""
    global _manager
    _manager = manager


def get_manager() -> Any | None:
    """The live manager, or None if no registry has been built yet."""
    return _manager


def connection(server_name: str):
    """A connected server by name, or None.

    None covers every "not usable" case -- no registry, connector switched off,
    process died -- because callers all want the same fallback and none of them
    can do anything different about the reason.
    """
    manager = _manager
    if manager is None:
        return None
    found = getattr(manager, "connections", {}).get(server_name)
    return found if found is not None and found.connected else None
