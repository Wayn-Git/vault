"""The permission gate (ADR-0009).

Static per-tool risk floor, which the model's self-reported risk can escalate but
never lower -- the correction to Pipali's design, where model self-report was the
primary gate. Transport-agnostic: callers supply a callback, so a CLI, a web UI
and an unattended scheduled run all work through the same service.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.db.repositories import ConfirmationPreferenceRepository, McpTrustRepository
from backend.tools.base import RiskLevel, Tool, ToolContext, ToolSource

# Forces confirmation regardless of sandbox, preference or self-report.
SENSITIVE_PATH_PATTERNS = [
    re.compile(p)
    for p in (
        r"/\.ssh(/|$)",
        r"/\.aws(/|$)",
        r"/\.gnupg(/|$)",
        r"/\.config/gh(/|$)",
        r"/\.npmrc$",
        r"/\.netrc$",
        r"/\.env(\.|$)",
        r"/\.psok/config(/|$)",
        r"_history$",
        r"/\.mozilla(/|$)",
        r"/\.config/google-chrome(/|$)",
    )
]

_SELF_REPORT_RISK = {
    "read-only": RiskLevel.LOW,
    "safe": RiskLevel.LOW,
    "write-only": RiskLevel.MEDIUM,
    "read-write": RiskLevel.HIGH,
    "unsafe": RiskLevel.HIGH,
    "destructive": RiskLevel.HIGH,
}


@dataclass
class ConfirmationRequest:
    tool_name: str
    operation_key: str
    risk: RiskLevel
    reason: str
    arguments: dict[str, Any]
    # Minted here rather than by whichever transport answers the prompt, so the
    # same id can be announced to the interface and used to answer. A UI that
    # learns of a prompt only by polling cannot tell two pending calls to the
    # same tool apart.
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # Which conversation is suspended on this. Pending prompts are process-wide,
    # so without it an interface recovering one after a reload cannot tell
    # whether it belongs to the conversation on screen or another one.
    conversation_id: str | None = None


@dataclass
class ConfirmationOutcome:
    allowed: bool
    decision: str  # auto | approved | denied | skipped_by_pref | denied_by_pref
    risk: RiskLevel


# Return True to allow. Raise or return False to deny.
ConfirmationCallback = Callable[[ConfirmationRequest], Awaitable[bool]]


async def auto_approve(_: ConfirmationRequest) -> bool:
    """Non-interactive default. Only safe where the caller has vetted the tool set."""
    return True


def is_sensitive_path(value: str) -> bool:
    try:
        resolved = str(Path(value).expanduser())
    except (OSError, ValueError):
        resolved = value
    return any(p.search(resolved) for p in SENSITIVE_PATH_PATTERNS)


def _path_arguments(arguments: dict[str, Any]) -> list[str]:
    out = []
    for key, value in arguments.items():
        if isinstance(value, str) and ("path" in key or "file" in key or "dir" in key):
            out.append(value)
    return out


class ConfirmationService:
    def __init__(
        self,
        callback: ConfirmationCallback | None = None,
        *,
        preferences: ConfirmationPreferenceRepository | None = None,
        mcp_trust: McpTrustRepository | None = None,
    ):
        self.callback = callback or auto_approve
        self._prefs = preferences
        self._trust = mcp_trust

    @property
    def preferences(self) -> ConfirmationPreferenceRepository:
        if self._prefs is None:
            self._prefs = ConfirmationPreferenceRepository()
        return self._prefs

    @property
    def mcp_trust(self) -> McpTrustRepository:
        if self._trust is None:
            self._trust = McpTrustRepository()
        return self._trust

    def evaluate_risk(self, tool: Tool, arguments: dict[str, Any]) -> tuple[RiskLevel, str]:
        """Static floor, escalated only upward by self-report and sensitive paths."""
        risk = tool.risk
        reason = f"{tool.name} is rated {tool.risk.value} risk"

        self_reported = arguments.get("operation_type")
        if isinstance(self_reported, str):
            escalated = _SELF_REPORT_RISK.get(self_reported.lower())
            if escalated and escalated != risk:
                new_risk = risk.at_least(escalated)
                if new_risk != risk:
                    risk = new_risk
                    reason = f"model reported '{self_reported}', escalating to {risk.value}"

        if tool.touches_paths:
            for candidate in _path_arguments(arguments):
                if is_sensitive_path(candidate):
                    return RiskLevel.HIGH, f"touches sensitive path: {candidate}"

        return risk, reason

    async def _ask(
        self, request: ConfirmationRequest, context: ToolContext | None
    ) -> bool:
        """Announce the prompt, then block on it.

        Announcing first is what lets an interface react the moment the turn
        suspends. Without it the only signal is the stream going quiet, which
        looks exactly like a slow tool.
        """
        if context is not None and context.events is not None:
            context.events.put_nowait(
                (
                    "confirmation_required",
                    {
                        "request_id": request.id,
                        "tool_name": request.tool_name,
                        "operation_key": request.operation_key,
                        "risk": request.risk.value,
                        "reason": request.reason,
                        "arguments": request.arguments,
                        "conversation_id": request.conversation_id,
                    },
                )
            )
        return await self.callback(request)

    async def check(
        self,
        tool: Tool,
        arguments: dict[str, Any],
        context: ToolContext | None = None,
    ) -> ConfirmationOutcome:
        risk, reason = self.evaluate_risk(tool, arguments)

        # First call to a not-yet-trusted MCP server always confirms. This is a
        # one-time trust event, orthogonal to the per-call risk gate.
        if tool.source is ToolSource.MCP and tool.server_name:
            if not self.mcp_trust.is_trusted(tool.server_name):
                request = ConfirmationRequest(
                    tool_name=tool.name,
                    operation_key=f"mcp:{tool.server_name}",
                    risk=RiskLevel.HIGH,
                    reason=f"first use of MCP server '{tool.server_name}'",
                    arguments=arguments,
                    conversation_id=context.conversation_id if context else None,
                )
                if await self._ask(request, context):
                    self.mcp_trust.trust(tool.server_name)
                else:
                    return ConfirmationOutcome(False, "denied", RiskLevel.HIGH)

        sensitive = reason.startswith("touches sensitive path")
        if risk is RiskLevel.LOW and not sensitive:
            return ConfirmationOutcome(True, "auto", risk)

        operation_key = tool.operation_key(arguments)
        if not sensitive:
            # A standing preference cannot silence the sensitive-path check.
            remembered = self.preferences.get(operation_key)
            if remembered == "allow":
                return ConfirmationOutcome(True, "skipped_by_pref", risk)
            if remembered == "deny":
                return ConfirmationOutcome(False, "denied_by_pref", risk)

        request = ConfirmationRequest(
            tool_name=tool.name,
            operation_key=operation_key,
            risk=risk,
            reason=reason,
            arguments=arguments,
            conversation_id=context.conversation_id if context else None,
        )
        allowed = await self._ask(request, context)
        return ConfirmationOutcome(allowed, "approved" if allowed else "denied", risk)
