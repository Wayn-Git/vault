"""MCP lifecycle and registration into the flat tool registry.

Once a server's tools are registered, the agent loop cannot tell them apart from
builtin tools -- that indistinguishability is the point (ADR-0005). The two facts
the dispatcher does know are that MCP servers run outside PSOK's sandbox and that
a new server needs a one-time trust confirmation, both handled by the permission
gate rather than here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from psok.mcp import guidance
from psok.mcp.client import MCPConnection, MCPConnectionError, OAuthRequired
from psok.mcp.config import ServerConfig, load_servers
from psok.mcp.risk import classify
from psok.tools.base import Tool, ToolContext, ToolResult, ToolSource
from psok.tools.registry import ToolRegistry, mcp_tool_key

log = logging.getLogger(__name__)

MAX_TOOLS_PER_SERVER = 128

# How long reconcile leaves a failed server alone, by consecutive failure. The
# last value repeats, so a server that is genuinely gone is retried twice an
# hour rather than at the head of every turn.
RETRY_BACKOFF_SECONDS = (60.0, 300.0, 1800.0)


def normalize_result(result: Any) -> ToolResult:
    """MCP content blocks into PSOK's uniform envelope.

    Every provider receives plain text; images and other binary blocks become
    artifacts so they never bloat the text the model reads.
    """
    text_parts: list[str] = []
    artifacts: list[dict[str, Any]] = []

    for block in getattr(result, "content", None) or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            text_parts.append(getattr(block, "text", "") or "")
        elif kind == "image":
            artifacts.append(
                {
                    "type": "image",
                    "mime_type": getattr(block, "mime_type", "image/png"),
                    "data": getattr(block, "data", ""),
                }
            )
            text_parts.append("[image returned]")
        elif kind == "resource":
            resource = getattr(block, "resource", None)
            uri = getattr(resource, "uri", "")
            inline = getattr(resource, "text", None)
            text_parts.append(inline if inline else f"[resource: {uri}]")
            if not inline:
                artifacts.append({"type": "resource", "uri": str(uri)})
        else:
            text_parts.append(str(block))

    structured = getattr(result, "structured_content", None)
    if structured and not text_parts:
        text_parts.append(str(structured))

    content = "\n".join(p for p in text_parts if p) or "(no content returned)"
    return ToolResult(
        content=content, artifacts=artifacts, is_error=bool(getattr(result, "is_error", False))
    )


# What a dead transport looks like coming back out of the SDK. Matched on the
# message because the exception types are anyio's and vary by transport, and
# because a `TaskGroup` wrapper hides them anyway.
_TRANSPORT_FAILURES = (
    "connection closed",
    "closedresourceerror",
    "brokenresourceerror",
    "broken pipe",
    "server has been shut down",
    "transport is closed",
    "endofstream",
)


def _is_transport_failure(exc: BaseException) -> bool:
    """Whether this failure means the session died, rather than the call failing.

    The distinction matters: a tool that raises is information for the model,
    while a dead session makes every later call in the turn fail identically
    until something reconnects.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _TRANSPORT_FAILURES)


class MCPManager:
    """Owns every MCP connection and keeps the registry in step with them."""

    def __init__(self, registry: ToolRegistry, *, open_browser: bool = True):
        self.registry = registry
        self.open_browser = open_browser
        self.connections: dict[str, MCPConnection] = {}
        self.errors: dict[str, str] = {}
        # When reconcile may next try a failed server again, and how many times
        # in a row it has failed -- see `_hold_off`.
        self.retry_after: dict[str, float] = {}
        self.attempts: dict[str, int] = {}

    def _hold_off(self, name: str) -> None:
        """Back a failed server off, rather than writing it off.

        `reconcile` used to skip anything with an error forever, so one refused
        DNS lookup left a connector reading "failed to start" until something
        explicitly cleared it. Backing off keeps the property that comment was
        protecting -- no connect timeout at the head of every turn -- without
        making a bad minute permanent.
        """
        self.attempts[name] = self.attempts.get(name, 0) + 1
        delay = RETRY_BACKOFF_SECONDS[min(self.attempts[name] - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
        self.retry_after[name] = time.monotonic() + delay

    def _clear_failure(self, name: str) -> None:
        self.errors.pop(name, None)
        self.retry_after.pop(name, None)
        self.attempts.pop(name, None)

    def forget_error(self, name: str) -> None:
        """Let the next reconcile retry this server immediately.

        Called when the user does something that means "try again now" -- a
        sign-in, a toggle, an explicit connect -- which should not have to wait
        out a backoff the user has no way of seeing.
        """
        self._clear_failure(name)
        # The same events that mean "try again" are the ones that change whether
        # an account is attached, and a cached "not signed in" outliving the
        # sign-in is how a connector stays hidden after the user fixed it.
        guidance.forget()

    # ------------------------------------------------------------------ connect

    def needs_sign_in(self, config: ServerConfig) -> bool:
        """Whether connecting this server would start an interactive sign-in.

        Only asked of OAuth servers, and answered from the keychain rather than
        by trying: the whole point is to avoid the attempt.
        """
        from psok.mcp.oauth import has_stored_token

        return bool(config.oauth) and not has_stored_token(config.name)

    async def connect_server(self, config: ServerConfig, *, interactive: bool = True) -> int:
        """Connect, discover, and register. Returns the number of tools added.

        `interactive=False` refuses to begin a sign-in rather than opening a
        browser. See `needs_sign_in`.
        """
        if not config.enabled:
            return 0

        if not interactive and self.needs_sign_in(config):
            message = (
                f"'{config.name}' has not been signed in to. Open it in Connectors"
                " and press Connect."
            )
            self.errors[config.name] = message
            raise OAuthRequired(message)

        await self.disconnect_server(config.name)
        connection = MCPConnection(
            config, open_browser=self.open_browser and interactive, interactive=interactive
        )

        try:
            await connection.connect()
        except MCPConnectionError as exc:
            # Already classified (OAuthRequired, OAuthRegistrationUnsupported, ...).
            # Re-wrapping would erase the type callers branch on.
            self.errors[config.name] = str(exc)
            self._hold_off(config.name)
            raise
        except Exception as exc:
            self.errors[config.name] = str(exc)
            self._hold_off(config.name)
            raise MCPConnectionError(f"'{config.name}' failed to connect: {exc}") from exc

        self.connections[config.name] = connection
        self._clear_failure(config.name)
        return self._register_tools(config, connection)

    def rebind(self, registry: ToolRegistry) -> int:
        """Move live connections onto a new registry without reconnecting them.

        The workspace root is baked into the *builtin* tools -- it is what the
        file tools are sandboxed to -- so changing it needs a new registry. It
        has nothing to do with MCP: a connector is a process holding a session,
        and which folder the file tools point at is not its business.

        Rebuilding both together meant every connector was torn down and
        respawned whenever the root changed, which it did constantly, because
        the root was the cache key and half the callers had no workspace to pass.
        A browser lost its pages, a signed-in server lost its session, and every
        tool call in flight came back "Connection closed".
        """
        self.registry = registry
        configured = load_servers()
        total = 0
        for name, connection in self.connections.items():
            config = configured.get(name)
            if config is None or not connection.connected:
                continue
            total += self._register_tools(config, connection)
        return total

    def _register_tools(self, config: ServerConfig, connection: MCPConnection) -> int:
        registered = 0
        for discovered in connection.tools[:MAX_TOOLS_PER_SERVER]:
            key = mcp_tool_key(discovered.name, config.name)
            if self.registry.get(key):
                continue
            self.registry.register(
                Tool(
                    name=key,
                    description=self._describe(config, discovered.description),
                    parameters=discovered.input_schema,
                    handler=self._make_handler(config.name, discovered.name),
                    # From the server's own `annotations`, falling back to what
                    # the name says -- see `psok/mcp/risk.py`. This was a flat
                    # `MEDIUM` until 2026-08-29, on the reasoning that PSOK
                    # cannot inspect somebody else's server. It can: MCP tools
                    # carry `readOnlyHint` and `destructiveHint`, and discovery
                    # was throwing the field away. The cost of not reading it
                    # was a confirmation prompt on every search and every list,
                    # which is how a permission gate stops being read.
                    risk=classify(discovered.name, discovered.annotations),
                    source=ToolSource.MCP,
                    server_name=config.name,
                )
            )
            registered += 1
        return registered

    def _describe(self, config: ServerConfig, description: str) -> str:
        label = config.description or config.name
        return (
            f"[{config.name}] {description}".strip() if description else f"[{config.name}] {label}"
        )

    def _make_handler(self, server_name: str, tool_name: str):
        async def handler(arguments: dict[str, Any], _: ToolContext) -> ToolResult:
            connection = self.connections.get(server_name)
            if connection is None:
                # Named the server and told the model to "reconnect it", which
                # it cannot do -- naming the screen and the button is what makes
                # this relayable to the person who can.
                return ToolResult.error(guidance.not_connected_instruction(server_name))
            try:
                raw = await connection.call(tool_name, arguments)
            except OAuthRequired:
                # Was a CLI command. The user is in a browser; sending them to a
                # terminal for a button that is two clicks away is the interface
                # telling on itself.
                return ToolResult.error(guidance.sign_in_instruction(server_name))
            except TimeoutError:
                return ToolResult.error(f"'{tool_name}' on '{server_name}' timed out.")
            except Exception as exc:
                if not _is_transport_failure(exc):
                    connection.breaker.record_failure()
                    return ToolResult.error(f"[{server_name}] {tool_name} failed: {exc}")

                # The session is gone, not the tool. A stdio server that exited
                # -- restarted, killed, crashed -- leaves the serving task alive
                # on a dead pipe, so `connected` stays true and every call from
                # here on answers "Connection closed" forever. Nothing retried,
                # and the model spent its turn calling three tools that could
                # not have worked. Reconnect once and try the call again.
                log.info(
                    "%s lost its connection during %s; reconnecting once",
                    server_name,
                    tool_name,
                )
                config = load_servers().get(server_name)
                if config is None:
                    return ToolResult.error(
                        f"[{server_name}] {tool_name} failed: {exc}"
                        f" (and '{server_name}' is no longer configured)"
                    )
                try:
                    self.forget_error(server_name)
                    await self.connect_server(config, interactive=False)
                    revived = self.connections.get(server_name)
                    if revived is None:
                        raise MCPConnectionError("reconnect produced no connection")
                    raw = await revived.call(tool_name, arguments)
                except Exception as retry_exc:
                    # Deliberately not a third attempt: a server that cannot be
                    # brought back is a fact to report, not one to keep paying a
                    # connect timeout for on every tool call in the turn.
                    return ToolResult.error(
                        guidance.dropped_instruction(server_name, str(retry_exc))
                    )
                connection = revived
            connection.breaker.record_success()
            return normalize_result(raw)

        return handler

    # --------------------------------------------------------------- lifecycle

    async def disconnect_server(self, name: str) -> None:
        connection = self.connections.pop(name, None)
        if connection is not None:
            await connection.disconnect()
        self.registry.unregister_server(name)

    async def connect_all(
        self, *, conversation_id: str | None = None, interactive: bool = False
    ) -> dict[str, int | str]:
        """Connect every switched-on server. Failures are reported, never raised.

        **Concurrent, and non-interactive by default.** Serially was costing
        minutes rather than the seconds the connections themselves take: on this
        machine seven working connectors come up in about eight seconds, while
        two switched-on-but-unauthorised ones each blocked the whole queue for
        `auth_timeout_seconds` (300s) waiting on a browser nobody had opened.
        A scheduled run's entire budget went on that before it reached a model.

        So: a server needing a sign-in is reported, not waited on, and the rest
        start together. `interactive=True` is for a person pressing Connect,
        which is the only context where opening a browser is an answer.
        """
        from psok.capabilities import CapabilityService

        live = CapabilityService().enabled_connector_names(conversation_id)
        wanted = [
            config
            for name, config in load_servers().items()
            if config.enabled and name in live
        ]

        async def one(config: ServerConfig) -> tuple[str, int | str]:
            try:
                return config.name, await self.connect_server(config, interactive=interactive)
            except Exception as exc:
                return config.name, str(exc)

        settled = await asyncio.gather(*(one(config) for config in wanted))
        return dict(settled)

    def state(self) -> dict[str, dict[str, Any]]:
        """What is actually running, per server.

        An interface that reports the capability row alone is reporting an
        intention: the row says "on" whether the process started, died, or was
        never asked to start. This is the fact to render instead.
        """
        out: dict[str, dict[str, Any]] = {}
        for name in set(load_servers()) | set(self.connections) | set(self.errors):
            connection = self.connections.get(name)
            connected = bool(connection and connection.connected)
            out[name] = {
                "connected": connected,
                "tools": len(connection.tools) if connected and connection else 0,
                "error": self.errors.get(name),
            }
        return out

    async def reconcile(self) -> dict[str, int | str]:
        """Bring live connections in line with what is currently switched on.

        One manager serves the whole process for its lifetime, so without this a
        connector switched on in the interface stayed dark until PSOK was
        restarted -- the toggle wrote a row nothing acted on.

        A server that already failed is left alone until its backoff expires:
        retrying a dead one on every pass would spend its connect timeout at the
        start of every turn, before the model is even called. But it *is*
        retried eventually -- skipping it forever meant one transient DNS
        failure disabled a connector for the rest of the session.
        """
        from psok.capabilities import CapabilityService, Kind

        service = CapabilityService()
        configured = load_servers()
        results: dict[str, int | str] = {}

        for name in [n for n in set(self.connections) | set(self.errors) if n not in configured]:
            # Removed from mcp.yaml. Its failure has to go with it, or health
            # stays degraded forever over a connector that no longer exists.
            await self.disconnect_server(name)
            self._clear_failure(name)
            results[name] = 0

        for name, config in configured.items():
            connection = self.connections.get(name)
            connected = bool(connection and connection.connected)

            if not config.enabled or service.switched_off(Kind.CONNECTOR, name):
                if connected:
                    await self.disconnect_server(name)
                    results[name] = 0
                continue

            # Only an explicit "on" starts a process. A server connected by hand
            # is left connected: no opinion is not the same as "switch it off".
            if not connected and service.is_enabled(Kind.CONNECTOR, name):
                if name in self.errors and time.monotonic() < self.retry_after.get(name, 0.0):
                    continue
                try:
                    results[name] = await self.connect_server(config, interactive=False)
                except Exception as exc:
                    results[name] = str(exc)
        return results

    async def shutdown(self) -> None:
        for name in list(self.connections):
            await self.disconnect_server(name)

    def status(self) -> list[dict[str, Any]]:
        out = []
        for name, config in load_servers().items():
            connection = self.connections.get(name)
            out.append(
                {
                    "name": name,
                    "transport": str(config.transport),
                    "enabled": config.enabled,
                    "connected": bool(connection and connection.connected),
                    "tools": len(connection.tools) if connection else 0,
                    "oauth": config.oauth,
                    "source": str(config.source),
                    "error": self.errors.get(name),
                }
            )
        return out
