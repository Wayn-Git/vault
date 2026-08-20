"""End-to-end MCP against real servers.

Marked `live` and deselected by default (see pyproject addopts) because these
spawn real processes and reach the network. Run them with:

    pytest -m live

They exist because the unit tests mock the transport, and a transport that only
works against a mock is not evidence that MCP works.
"""

from __future__ import annotations

import shutil

import pytest

from psok.mcp import commands as mcp_commands
from psok.mcp.config import load_servers
from psok.security.confirmation import ConfirmationService, auto_approve
from psok.tools.base import ToolContext
from psok.tools.registry import ToolRegistry

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(shutil.which("npx") is None, reason="needs Node.js (npx)"),
]


async def _connect(server_id: str):
    from psok.mcp.manager import MCPManager

    mcp_commands.add_from_catalogue(server_id)
    registry = ToolRegistry(ConfirmationService(auto_approve))
    manager = MCPManager(registry, open_browser=False)
    count = await manager.connect_server(load_servers()[server_id])
    return manager, registry, count


async def test_memory_server_discovers_and_executes(psok_home):
    manager, registry, count = await _connect("memory")
    try:
        assert count >= 5, "the memory server should expose a handful of tools"
        names = {t.name for t in registry.list()}
        assert "create_entities__mcp__memory" in names
        assert "read_graph__mcp__memory" in names

        created = await registry.dispatch(
            "create_entities__mcp__memory",
            {
                "entities": [
                    {"name": "PSOK", "entityType": "project", "observations": ["personal OS"]}
                ]
            },
            ToolContext(),
        )
        assert not created.is_error, created.content

        graph = await registry.dispatch("read_graph__mcp__memory", {}, ToolContext())
        assert not graph.is_error and "PSOK" in graph.content
    finally:
        await manager.shutdown()


async def test_bad_arguments_come_back_as_an_error_result(psok_home):
    """A server-side validation failure must not crash the turn."""
    manager, registry, _ = await _connect("memory")
    try:
        result = await registry.dispatch(
            "create_entities__mcp__memory", {"entities": "not-an-array"}, ToolContext()
        )
        assert result.is_error
        assert "expected array" in result.content or "validation" in result.content.lower()
    finally:
        await manager.shutdown()


async def test_browser_server_exposes_navigation_tools(psok_home):
    manager, registry, count = await _connect("playwright")
    try:
        assert count > 10, "playwright exposes a broad browser toolset"
        names = {t.name.split("__mcp__")[0] for t in registry.list()}
        assert {"browser_navigate", "browser_click", "browser_take_screenshot"} <= names
    finally:
        await manager.shutdown()


async def test_disconnect_removes_the_tools_again(psok_home):
    manager, registry, count = await _connect("memory")
    try:
        assert count > 0 and registry.list()
        await manager.disconnect_server("memory")
        assert not [t for t in registry.list() if t.server_name == "memory"]
    finally:
        await manager.shutdown()


@pytest.mark.skipif(shutil.which("curl") is None, reason="needs curl")
async def test_github_requires_authorization_with_useful_guidance(psok_home):
    """GitHub's real server should refuse anonymously and say what to do about it."""
    from psok.mcp.client import MCPConnectionError
    from psok.mcp.manager import MCPManager

    mcp_commands.add_from_catalogue("github")
    manager = MCPManager(ToolRegistry(ConfirmationService(auto_approve)), open_browser=False)
    try:
        with pytest.raises(MCPConnectionError) as excinfo:
            await manager.connect_server(load_servers()["github"])
        message = str(excinfo.value)
        assert "psok mcp auth github" in message or "authoriz" in message.lower()
    finally:
        await manager.shutdown()
