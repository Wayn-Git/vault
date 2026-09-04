"""The permission gate is the load-bearing safety property, so it gets the most tests."""

from __future__ import annotations

import pytest

from backend.security.confirmation import ConfirmationService, is_sensitive_path
from backend.tools.base import RiskLevel, Tool, ToolContext, ToolResult, ToolSource


async def _noop(args, ctx):
    return ToolResult.ok("done")


def make_tool(name="t", risk=RiskLevel.LOW, **kw) -> Tool:
    return Tool(
        name=name,
        description="",
        parameters={"type": "object", "properties": {}},
        handler=_noop,
        risk=risk,
        **kw,
    )


async def test_low_risk_runs_without_confirmation(db):
    asked = False

    async def callback(_):
        nonlocal asked
        asked = True
        return True

    service = ConfirmationService(callback)
    outcome = await service.check(make_tool(risk=RiskLevel.LOW), {})
    assert outcome.allowed and outcome.decision == "auto"
    assert not asked


async def test_medium_risk_asks(db):
    service = ConfirmationService(lambda _: _true())
    outcome = await service.check(make_tool(risk=RiskLevel.MEDIUM), {})
    assert outcome.allowed and outcome.decision == "approved"


async def _true():
    return True


async def _false():
    return False


async def test_denial_blocks_execution(db):
    service = ConfirmationService(lambda _: _false())
    outcome = await service.check(make_tool(risk=RiskLevel.HIGH), {})
    assert not outcome.allowed and outcome.decision == "denied"


async def test_self_report_escalates_but_never_lowers(db):
    """The correction to Pipali: self-report is a refinement, not the gate."""
    service = ConfirmationService(lambda _: _true())

    # Claiming safety on a high-risk tool does not lower the floor.
    tool = make_tool(risk=RiskLevel.HIGH)
    risk, _ = service.evaluate_risk(tool, {"operation_type": "read-only"})
    assert risk is RiskLevel.HIGH

    # Reporting danger on a low-risk tool does raise it.
    tool = make_tool(risk=RiskLevel.LOW)
    risk, reason = service.evaluate_risk(tool, {"operation_type": "read-write"})
    assert risk is RiskLevel.HIGH
    assert "escalating" in reason


async def test_sensitive_path_forces_confirmation_despite_preference(db):
    service = ConfirmationService(lambda _: _false())
    tool = make_tool(name="view_file", risk=RiskLevel.LOW, touches_paths=True)
    service.preferences.remember("view_file", "allow", "low")

    outcome = await service.check(tool, {"path": "/home/someone/.ssh/id_rsa"})
    assert not outcome.allowed, "a standing preference must not silence the sensitive-path check"


async def test_remembered_preference_skips_the_prompt(db):
    asked = False

    async def callback(_):
        nonlocal asked
        asked = True
        return True

    service = ConfirmationService(callback)
    service.preferences.remember("write_file", "allow", "medium")
    outcome = await service.check(make_tool("write_file", RiskLevel.MEDIUM), {})
    assert outcome.allowed and outcome.decision == "skipped_by_pref"
    assert not asked


async def test_first_mcp_call_requires_trust_then_remembers(db):
    calls = []

    async def callback(request):
        calls.append(request.operation_key)
        return True

    service = ConfirmationService(callback)
    tool = make_tool(
        "search__mcp__notes", RiskLevel.LOW, source=ToolSource.MCP, server_name="notes"
    )

    await service.check(tool, {})
    assert calls == ["mcp:notes"], "first call to a new server must establish trust"

    calls.clear()
    await service.check(tool, {})
    assert calls == [], "trust is established once per server, not per call"


@pytest.mark.parametrize(
    "path",
    [
        "~/.ssh/config",
        "/home/x/.aws/credentials",
        "/srv/app/.env.production",
        "/home/x/.bash_history",
    ],
)
def test_sensitive_paths_detected(path):
    assert is_sensitive_path(path)


@pytest.mark.parametrize("path", ["/home/x/notes/todo.md", "/tmp/output.txt"])
def test_ordinary_paths_not_flagged(path):
    assert not is_sensitive_path(path)


async def test_dispatch_denial_returns_an_error_result_not_an_exception(db):
    from backend.tools.registry import ToolRegistry

    registry = ToolRegistry(ConfirmationService(lambda _: _false()))
    registry.register(make_tool("delete_file", RiskLevel.HIGH))
    result = await registry.dispatch("delete_file", {}, ToolContext())
    assert result.is_error and "declined" in result.content


async def test_a_sandbox_preference_does_not_cover_an_unsandboxed_machine(db, monkeypatch):
    """Sandbox mode runs the command unwrapped where the OS offers no sandbox.
    Keying it as ':sandbox' anyway meant "always allow sandboxed commands",
    granted on a machine with bubblewrap, silenced the gate on one without --
    full shell access with no prompt."""
    from backend.tools.builtin import shell

    tool = shell.tools()[0]
    contained = {"command": "ls", "execution_mode": "sandbox"}

    monkeypatch.setattr(shell, "platform_backend", lambda: "bubblewrap")
    assert tool.operation_key(contained) == "run_shell_command:sandbox"

    monkeypatch.setattr(shell, "platform_backend", lambda: None)
    assert tool.operation_key(contained) == "run_shell_command:direct"

    # And the gate honours the distinction: the sandbox preference does not match.
    service = ConfirmationService(lambda _: _false())
    service.preferences.remember("run_shell_command:sandbox", "allow", "high")
    outcome = await service.check(tool, contained)
    assert not outcome.allowed and outcome.decision == "denied"


async def test_the_model_still_describes_its_own_operation_where_a_sandbox_exists(db, monkeypatch):
    """The documented key stays what security.md says it is."""
    from backend.tools.builtin import shell

    monkeypatch.setattr(shell, "platform_backend", lambda: "seatbelt")
    key = shell.tools()[0].operation_key(
        {"command": "ls", "execution_mode": "sandbox", "operation_type": "read-only"}
    )
    assert key == "run_shell_command:read-only"
