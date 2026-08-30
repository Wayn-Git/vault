"""Desktop tools, deliberately narrow (ADR-0015).

OS default-handler launches only. No mouse or keyboard synthesis, no
screenshot-driven clicking -- that surface is deferred to a later, separately
risk-gated phase.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.tools.base import RiskLevel, Tool, ToolContext, ToolResult

ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


def _opener() -> list[str] | None:
    if sys.platform == "darwin":
        return ["open"]
    if sys.platform == "win32":
        return ["cmd", "/c", "start", ""]
    for candidate in ("xdg-open", "gio"):
        if shutil.which(candidate):
            return [candidate, "open"] if candidate == "gio" else [candidate]
    return None


async def _launch(target: str) -> ToolResult:
    opener = _opener()
    if opener is None:
        return ToolResult.error("no desktop opener available on this system")
    try:
        proc = await asyncio.create_subprocess_exec(
            *opener,
            target,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except TimeoutError:
        return ToolResult.ok(f"launched {target} (opener still running)")
    except OSError as exc:
        return ToolResult.error(f"failed to launch {target}: {exc}")

    if proc.returncode != 0:
        return ToolResult.error(
            f"opener exited {proc.returncode}: {stderr.decode(errors='replace')}"
        )
    return ToolResult.ok(f"opened {target}")


async def open_url(args: dict[str, Any], _: ToolContext) -> ToolResult:
    url = args["url"]
    scheme = urlparse(url).scheme.lower()
    if scheme not in ALLOWED_URL_SCHEMES:
        return ToolResult.error(f"refusing to open '{scheme}' URL; allowed: http, https, mailto")
    return await _launch(url)


async def open_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = Path(args["path"]).expanduser()
    if not path.is_absolute():
        path = Path(ctx.workspace_root or Path.cwd()) / path
    if not path.exists():
        return ToolResult.error(f"no such file: {path}")
    return await _launch(str(path.resolve()))


async def open_application(args: dict[str, Any], _: ToolContext) -> ToolResult:
    name = args["name"]
    if sys.platform == "darwin":
        argv = ["open", "-a", name]
    elif sys.platform == "win32":
        argv = ["cmd", "/c", "start", "", name]
    else:
        if not shutil.which(name):
            return ToolResult.error(f"'{name}' is not on PATH")
        argv = [name]
    try:
        await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
    except OSError as exc:
        return ToolResult.error(f"failed to launch {name}: {exc}")
    return ToolResult.ok(f"launched {name}")


def tools() -> list[Tool]:
    return [
        Tool(
            name="open_url",
            description="Open a URL in the user's default browser.",
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            handler=open_url,
            risk=RiskLevel.MEDIUM,
        ),
        Tool(
            name="open_file",
            description="Open a file with the operating system's default application.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=open_file,
            risk=RiskLevel.MEDIUM,
            touches_paths=True,
        ),
        Tool(
            name="open_application",
            description="Launch a desktop application by name.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            handler=open_application,
            risk=RiskLevel.MEDIUM,
        ),
    ]
