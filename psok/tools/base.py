"""Tool contract and result envelope (ADR-0005).

Every tool -- builtin, integration, or MCP -- has the same shape. Above the
dispatcher nothing knows the difference; the source only affects how the call is
implemented and which permission rules apply.
"""

from __future__ import annotations

import asyncio
import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


class RiskLevel(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    def at_least(self, other: RiskLevel) -> RiskLevel:
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]
        return other if order.index(other) > order.index(self) else self


class ToolSource(enum.StrEnum):
    BUILTIN = "builtin"
    INTEGRATION = "integration"
    MCP = "mcp"


@dataclass
class ToolResult:
    """The uniform envelope. Errors are data, never exceptions."""

    content: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False

    @classmethod
    def ok(cls, content: str, artifacts: list[dict[str, Any]] | None = None) -> ToolResult:
        return cls(content=content, artifacts=artifacts or [])

    @classmethod
    def error(cls, message: str) -> ToolResult:
        return cls(content=message, is_error=True)


@dataclass
class ToolContext:
    """Passed to every tool implementation at call time."""

    conversation_id: str | None = None
    workspace_root: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    # Plan mode. The schemas of every mutating tool are withheld from the model,
    # and this is the second half of that: a tool named anyway -- from an
    # earlier turn, or invented -- is refused here rather than run. Withholding
    # alone is a request; this is the enforcement.
    read_only: bool = False
    # Where the dispatch path publishes anything the interface must see while a
    # call is still in flight -- today only a confirmation prompt, which
    # suspends the turn and cannot wait for the tool result to be reported.
    # Items are (event_type, data) pairs; the agent loop drains them.
    events: asyncio.Queue | None = None


ToolHandler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    risk: RiskLevel = RiskLevel.MEDIUM
    source: ToolSource = ToolSource.BUILTIN
    server_name: str | None = None  # MCP tools only
    touches_paths: bool = False  # triggers the sensitive-path check
    # Overrides how a call is keyed for "don't ask again". A tool needs this
    # when the arguments alone do not describe what will actually happen -- the
    # shell's sandbox mode is not sandboxed on a machine with no sandbox, and a
    # preference granted to contained commands must not cover uncontained ones.
    subtype: Callable[[dict[str, Any]], str | None] | None = None

    def operation_key(self, arguments: dict[str, Any]) -> str:
        """Key for 'don't ask again' preferences: operation[:subtype]."""
        if self.subtype is not None:
            subtype = self.subtype(arguments)
        else:
            subtype = arguments.get("operation_type") or arguments.get("execution_mode")
        return f"{self.name}:{subtype}" if subtype else self.name
