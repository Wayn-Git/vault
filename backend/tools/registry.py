"""The flat tool registry and the single dispatch path (ADR-0005).

No tool call reaches the filesystem, the shell or an external service by any
other route: every one passes the permission gate, gets normalized, gets
truncated, and gets an audit row.
"""

from __future__ import annotations

import time
from typing import Any

from backend.db.repositories import ExecutionLogRepository
from backend.runtime.types import ToolSchema
from backend.security.confirmation import ConfirmationService
from backend.tools.base import RiskLevel, Tool, ToolContext, ToolResult, ToolSource

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

    def with_confirmation(self, confirmation: ConfirmationService) -> ToolRegistry:
        """The same tools, gated differently.

        An unattended turn needs a permission callback that refuses rather than
        one that waits for a person, and it needs the connected MCP tools that
        the shared registry holds. Swapping the callback on the shared registry
        would change the rules for every interactive turn running at the same
        time, so this shares the tool dict -- deliberately by reference, so a
        connector that reconnects stays visible here too -- and nothing else.
        """
        view = ToolRegistry(confirmation=confirmation, logs=self._logs)
        view._tools = self._tools
        return view

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

    def schemas(
        self, *, hidden_servers: set[str] | None = None, read_only: bool = False
    ) -> list[ToolSchema]:
        """What the model sees. Source is deliberately invisible here.

        `hidden_servers` withholds the tools of connectors switched off for the
        current conversation, and of connectors nobody has signed in to. The
        connection itself is process-wide -- one manager serves every
        conversation -- so what a conversation can reach is decided here rather
        than by connecting a different set of servers.

        `read_only` withholds every tool that can change anything, which is what
        plan mode is. `RiskLevel.LOW` already means "changes nothing, runs
        without asking" -- the permission gate has trusted that judgement since
        it shipped -- so gating on it covers a connector's tools on the day it
        is added rather than on the day someone remembers to update a list.
        """
        hidden = hidden_servers or set()
        return [
            ToolSchema(name=t.name, description=t.description, parameters=t.parameters)
            for t in self._tools.values()
            if not (t.server_name and t.server_name in hidden)
            and not (read_only and t.risk is not RiskLevel.LOW)
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

        # Plan mode. Withholding the schema is a request; this is the answer to
        # "what if it asks anyway". Refused before the permission gate, because
        # a plan turn must not be able to raise a confirmation prompt either --
        # an approval dialog for a write the user did not ask for yet is worse
        # than the write being declined.
        if ctx.read_only and tool.risk is not RiskLevel.LOW:
            return ToolResult.error(
                f"'{name}' changes things, and this turn is planning rather than acting."
                " It is not available until the user approves the plan. Finish the plan"
                " and call submit_plan; do not try this tool again."
            )

        # Withholding the schema is not enough here either: a model can name a
        # tool it saw in an earlier turn, before the account was removed or
        # before the sign-in was found to be missing.
        if tool.server_name and tool.server_name in _unsigned_connectors():
            from backend.mcp.guidance import sign_in_instruction

            return ToolResult.error(sign_in_instruction(tool.server_name))

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


def _unsigned_connectors() -> frozenset[str]:
    """Connectors running with no account attached, cached briefly.

    Imported lazily and guarded for the same reason `_connector_enabled` is: the
    tool registry serves builtin tools on a machine with no connectors at all,
    and a failure to read MCP state must not stop a file being written.
    """
    try:
        from backend.mcp.guidance import unsigned_connectors

        return unsigned_connectors()
    except Exception:
        return frozenset()


def _connector_enabled(server_name: str, conversation_id: str | None) -> bool:
    """Capability state for one MCP server, failing open if it cannot be read.

    Failing open matches how the prompt treats an unreadable capability table:
    the state is a user preference, not a security boundary -- the permission
    gate is, and it runs regardless.
    """
    try:
        from backend.capabilities import CapabilityService, Kind

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
    from backend.tools.builtin import convert, desktop, documents, filesystem, shell, tasks, web

    registry = ToolRegistry(confirmation=confirmation)
    registry.register_all(filesystem.tools(workspace_root))
    registry.register_all(shell.tools())
    registry.register_all(desktop.tools())
    registry.register_all(tasks.tools())
    registry.register_all(documents.tools())
    registry.register_all(web.tools())
    registry.register_all(convert.tools())
    return registry


__all__ = [
    "ToolRegistry",
    "ToolSource",
    "build_default_registry",
    "mcp_tool_key",
    "truncate",
]
