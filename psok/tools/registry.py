"""The flat tool registry and the single dispatch path (ADR-0005).

No tool call reaches the filesystem, the shell or an external service by any
other route: every one passes the permission gate, gets normalized, gets
truncated, and gets an audit row.
"""

from __future__ import annotations

import time
from typing import Any

from psok.db.repositories import ExecutionLogRepository
from psok.runtime.types import ToolSchema
from psok.security.confirmation import ConfirmationService
from psok.tools.base import Tool, ToolContext, ToolResult, ToolSource

MAX_RESULT_CHARS = 100_000
MCP_DELIMITER = "__mcp__"


def truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit - 200]
    return f"{head}\n\n[... truncated, {len(text) - limit + 200} characters omitted ...]"


class ToolRegistry:
    def __init__(
        self,
        confirmation: ConfirmationService | None = None,
        logs: ExecutionLogRepository | None = None,
    ):
        self._tools: dict[str, Tool] = {}
        self.confirmation = confirmation or ConfirmationService()
        self._logs = logs

    @property
    def logs(self) -> ExecutionLogRepository:
        if self._logs is None:
            self._logs = ExecutionLogRepository()
        return self._logs

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def register_all(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def unregister_server(self, server_name: str) -> None:
        for name in [n for n, t in self._tools.items() if t.server_name == server_name]:
            del self._tools[name]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self, *, hidden_servers: set[str] | None = None) -> list[ToolSchema]:
        """What the model sees. Source is deliberately invisible here.

        `hidden_servers` withholds the tools of connectors switched off for the
        current conversation. The connection itself is process-wide -- one
        manager serves every conversation -- so what a conversation can reach is
        decided here rather than by connecting a different set of servers.
        """
        hidden = hidden_servers or set()
        return [
            ToolSchema(name=t.name, description=t.description, parameters=t.parameters)
            for t in self._tools.values()
            if not (t.server_name and t.server_name in hidden)
        ]

    async def dispatch(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext | None = None,
    ) -> ToolResult:
        ctx = context or ToolContext()
        tool = self._tools.get(name)
        if tool is None:
            known = ", ".join(sorted(self._tools)[:20]) or "none"
            return ToolResult.error(f"unknown tool '{name}'. Available tools: {known}")

        # A capability switched off for this conversation is not advertised and
        # not dispatchable. Withholding the schema is not enough on its own: the
        # model can name a tool it saw in an earlier turn, and the connection is
        # shared with every other conversation.
        if tool.server_name and not _connector_enabled(tool.server_name, ctx.conversation_id):
            return ToolResult.error(
                f"the '{tool.server_name}' connector is switched off for this conversation."
                " Ask the user to turn it back on if they want it used."
            )

        outcome = await self.confirmation.check(tool, arguments, ctx)
        if not outcome.allowed:
            self.logs.record(
                tool_name=name,
                tool_source=tool.source.value,
                conversation_id=ctx.conversation_id,
                arguments=arguments,
                error="denied by user",
                risk_level=outcome.risk.value,
                confirmation_decision=outcome.decision,
            )
            return ToolResult.error(
                f"'{name}' was not run: the user declined to approve this "
                f"{outcome.risk.value}-risk operation."
            )

        started = time.monotonic()
        try:
            result = await tool.handler(arguments, ctx)
        except Exception as exc:  # errors are data, never exceptions (see ai-runtime.md)
            result = ToolResult.error(f"{name} failed: {type(exc).__name__}: {exc}")

        result.content = truncate(result.content)
        self.logs.record(
            tool_name=name,
            tool_source=tool.source.value,
            conversation_id=ctx.conversation_id,
            arguments=arguments,
            result_summary=None if result.is_error else result.content[:2000],
            error=result.content[:2000] if result.is_error else None,
            risk_level=outcome.risk.value,
            confirmation_decision=outcome.decision,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return result


def _connector_enabled(server_name: str, conversation_id: str | None) -> bool:
    """Capability state for one MCP server, failing open if it cannot be read.

    Failing open matches how the prompt treats an unreadable capability table:
    the state is a user preference, not a security boundary -- the permission
    gate is, and it runs regardless.
    """
    try:
        from psok.capabilities import CapabilityService, Kind

        return not CapabilityService().switched_off(Kind.CONNECTOR, server_name, conversation_id)
    except Exception:
        return True


def mcp_tool_key(tool_name: str, server_name: str) -> str:
    """Composite key so two servers offering the same tool name never collide.

    Characters models cannot use in a tool name are percent-escaped rather than
    replaced, because collapsing '-' and '_' to the same character made
    'my-server' and 'my_server' produce one key -- the exact collision this
    function exists to prevent.
    """
    safe_server = "".join(c if (c.isalnum() or c == "_") else f"_{ord(c):02x}" for c in server_name)
    return f"{tool_name}{MCP_DELIMITER}{safe_server}"


def build_default_registry(
    confirmation: ConfirmationService | None = None,
    *,
    workspace_root: str | None = None,
) -> ToolRegistry:
    from psok.tools.builtin import desktop, documents, filesystem, shell, tasks, web

    registry = ToolRegistry(confirmation=confirmation)
    registry.register_all(filesystem.tools(workspace_root))
    registry.register_all(shell.tools())
    registry.register_all(desktop.tools())
    registry.register_all(tasks.tools())
    registry.register_all(documents.tools())
    registry.register_all(web.tools())
    return registry


__all__ = [
    "ToolRegistry",
    "ToolSource",
    "build_default_registry",
    "mcp_tool_key",
    "truncate",
]
