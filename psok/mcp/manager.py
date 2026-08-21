"""MCP lifecycle and registration into the flat tool registry.

Once a server's tools are registered, the agent loop cannot tell them apart from
builtin tools -- that indistinguishability is the point (ADR-0005). The two facts
the dispatcher does know are that MCP servers run outside PSOK's sandbox and that
a new server needs a one-time trust confirmation, both handled by the permission
gate rather than here.
"""

from __future__ import annotations

import logging
from typing import Any

from psok.mcp.client import MCPConnection, MCPConnectionError, OAuthRequired
from psok.mcp.config import ServerConfig, load_servers
from psok.tools.base import RiskLevel, Tool, ToolContext, ToolResult, ToolSource
from psok.tools.registry import ToolRegistry, mcp_tool_key

log = logging.getLogger(__name__)

MAX_TOOLS_PER_SERVER = 128


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


class MCPManager:
    """Owns every MCP connection and keeps the registry in step with them."""

    def __init__(self, registry: ToolRegistry, *, open_browser: bool = True):
        self.registry = registry
        self.open_browser = open_browser
        self.connections: dict[str, MCPConnection] = {}
        self.errors: dict[str, str] = {}

    # ------------------------------------------------------------------ connect

    async def connect_server(self, config: ServerConfig) -> int:
        """Connect, discover, and register. Returns the number of tools added."""
        if not config.enabled:
            return 0

        await self.disconnect_server(config.name)
        connection = MCPConnection(config, open_browser=self.open_browser)

        try:
            await connection.connect()
        except MCPConnectionError as exc:
            # Already classified (OAuthRequired, OAuthRegistrationUnsupported, ...).
            # Re-wrapping would erase the type callers branch on.
            self.errors[config.name] = str(exc)
            raise
        except Exception as exc:
            self.errors[config.name] = str(exc)
            raise MCPConnectionError(f"'{config.name}' failed to connect: {exc}") from exc

        self.connections[config.name] = connection
        self.errors.pop(config.name, None)
        return self._register_tools(config, connection)

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
                    # PSOK cannot inspect what an external server actually does, so
                    # its tools never sit at the lowest risk tier.
                    risk=RiskLevel.MEDIUM,
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
                return ToolResult.error(
                    f"MCP server '{server_name}' is not connected. Reconnect it and retry."
                )
            try:
                raw = await connection.call(tool_name, arguments)
            except OAuthRequired:
                return ToolResult.error(
                    f"'{server_name}' needs authorization. Ask the user to run"
                    f" `psok mcp login {server_name}`, then retry."
                )
            except TimeoutError:
                return ToolResult.error(f"'{tool_name}' on '{server_name}' timed out.")
            except Exception as exc:
                connection.breaker.record_failure()
                return ToolResult.error(f"[{server_name}] {tool_name} failed: {exc}")
            connection.breaker.record_success()
            return normalize_result(raw)

        return handler

    # --------------------------------------------------------------- lifecycle

    async def disconnect_server(self, name: str) -> None:
        connection = self.connections.pop(name, None)
        if connection is not None:
            await connection.disconnect()
        self.registry.unregister_server(name)

    async def connect_all(self, *, conversation_id: str | None = None) -> dict[str, int | str]:
        """Connect every switched-on server. Failures are reported, never raised."""
        from psok.capabilities import CapabilityService

        live = CapabilityService().enabled_connector_names(conversation_id)

        results: dict[str, int | str] = {}
        for name, config in load_servers().items():
            if not config.enabled:
                continue
            if name not in live:
                continue  # configured but switched off
            try:
                results[name] = await self.connect_server(config)
            except Exception as exc:
                results[name] = str(exc)
        return results

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

        A server that already failed is left alone until something asks for it
        again: retrying a dead one here would spend its connect timeout at the
        start of every turn, before the model is even called.
        """
        from psok.capabilities import CapabilityService, Kind

        service = CapabilityService()
        configured = load_servers()
        results: dict[str, int | str] = {}

        for name in [n for n in set(self.connections) | set(self.errors) if n not in configured]:
            # Removed from mcp.yaml. Its failure has to go with it, or health
            # stays degraded forever over a connector that no longer exists.
            await self.disconnect_server(name)
            self.errors.pop(name, None)
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
                if name in self.errors:
                    continue
                try:
                    results[name] = await self.connect_server(config)
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
