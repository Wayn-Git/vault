"""Shell execution. One component owns this, and it never raises at the agent.

Two execution modes, as alternatives rather than layers: sandbox mode is
OS-contained and lower friction; direct mode has full access and always
confirms. Every failure -- bad cwd, timeout, spawn error -- comes back as a
structured result the loop can reason about.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from psok.security.sandbox import SandboxPolicy, unavailable_reason, wrap_command
from psok.tools.base import RiskLevel, Tool, ToolContext, ToolResult

DEFAULT_TIMEOUT_S = 30
MAX_TIMEOUT_S = 120
MAX_OUTPUT_CHARS = 60_000


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n[... {len(text) - MAX_OUTPUT_CHARS} more characters ...]"


async def run_shell_command(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    command = (args.get("command") or "").strip()
    if not command:
        return ToolResult.error("no command provided")

    workspace = str(Path(ctx.workspace_root or Path.cwd()).expanduser().resolve())
    cwd = str(Path(args.get("cwd") or workspace).expanduser())
    if not Path(cwd).is_dir():
        return ToolResult.error(f"working directory does not exist: {cwd}")

    # The advertised timeout is the enforced timeout -- no silent clamping of a
    # contract the model reasons about.
    timeout = min(int(args.get("timeout_seconds") or DEFAULT_TIMEOUT_S), MAX_TIMEOUT_S)

    mode = args.get("execution_mode") or "sandbox"
    policy = SandboxPolicy.load()
    if mode == "direct":
        argv, backend = ["/bin/bash", "-c", command], None
    else:
        argv, backend = wrap_command(command, policy, workspace)

    env = {**os.environ, "PSOK": "1"}
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, FileNotFoundError) as exc:
        return ToolResult.error(f"failed to start command: {exc}")

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ToolResult.error(f"command timed out after {timeout}s and was killed:\n{command}")

    stdout = _clip(stdout_b.decode(errors="replace"))
    stderr = _clip(stderr_b.decode(errors="replace"))

    parts = []
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"[stderr]\n{stderr}")
    if proc.returncode != 0:
        parts.append(f"[exit code {proc.returncode}]")
        # Tell the model how to recover rather than just failing.
        if mode != "direct" and backend and _looks_like_sandbox_denial(stderr):
            parts.append(
                "[note] this looks like a sandbox restriction. Retry with"
                " execution_mode='direct' if the command genuinely needs full access."
            )
    if mode != "direct" and backend is None:
        reason = unavailable_reason()
        if reason:
            parts.append(f"[note] {reason}")

    output = "\n".join(parts) or "(no output)"
    return ToolResult(content=output, is_error=proc.returncode != 0)


def _looks_like_sandbox_denial(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(s in lowered for s in ("operation not permitted", "permission denied", "eperm"))


def tools() -> list[Tool]:
    sandbox_note = unavailable_reason()
    description = (
        "Run a shell command. Use execution_mode='sandbox' (default, OS-contained) unless the"
        " command genuinely needs unrestricted access, in which case use 'direct'."
    )
    if sandbox_note:
        description += f" Note: {sandbox_note}."

    return [
        Tool(
            name="run_shell_command",
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run"},
                    "cwd": {"type": "string", "description": "Working directory"},
                    "timeout_seconds": {
                        "type": "integer",
                        "description": f"Timeout, max {MAX_TIMEOUT_S}s",
                    },
                    "execution_mode": {
                        "type": "string",
                        "enum": ["sandbox", "direct"],
                        "description": "sandbox is OS-contained; direct always asks the user",
                    },
                    "operation_type": {
                        "type": "string",
                        "enum": ["read-only", "write-only", "read-write"],
                        "description": "Your assessment of what this command does. This can only"
                        " raise the confirmation requirement, never lower it.",
                    },
                },
                "required": ["command"],
            },
            handler=run_shell_command,
            risk=RiskLevel.HIGH,
            touches_paths=True,
        )
    ]
