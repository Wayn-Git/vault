from __future__ import annotations

from psok.security.confirmation import ConfirmationService, auto_approve
from psok.tools.base import ToolContext, ToolResult
from psok.tools.builtin import filesystem, shell
from psok.tools.registry import ToolRegistry, mcp_tool_key, truncate


def registry_for(workspace):
    from psok.tools.registry import build_default_registry

    return build_default_registry(ConfirmationService(auto_approve), workspace_root=str(workspace))


async def test_filesystem_roundtrip(db, workspace):
    reg = registry_for(workspace)
    ctx = ToolContext(workspace_root=str(workspace))

    assert not (
        await reg.dispatch("write_file", {"path": "a.md", "content": "hello"}, ctx)
    ).is_error
    read = await reg.dispatch("view_file", {"path": "a.md"}, ctx)
    assert "hello" in read.content

    await reg.dispatch(
        "edit_file", {"path": "a.md", "old_string": "hello", "new_string": "bye"}, ctx
    )
    assert "bye" in (await reg.dispatch("view_file", {"path": "a.md"}, ctx)).content

    listing = await reg.dispatch("list_files", {}, ctx)
    assert "a.md" in listing.content


async def test_missing_file_is_an_error_result_not_a_crash(db, workspace):
    reg = registry_for(workspace)
    result = await reg.dispatch(
        "view_file", {"path": "nope.md"}, ToolContext(workspace_root=str(workspace))
    )
    assert result.is_error and "no such file" in result.content


async def test_edit_refuses_ambiguous_match(db, workspace):
    (workspace / "d.md").write_text("x\nx\n")
    ctx = ToolContext(workspace_root=str(workspace))
    result = await filesystem.edit_file({"path": "d.md", "old_string": "x", "new_string": "y"}, ctx)
    assert result.is_error and "appears 2 times" in result.content


async def test_grep_finds_matches(db, workspace):
    (workspace / "notes.md").write_text("alpha\nbeta gamma\n")
    result = await filesystem.grep_files(
        {"pattern": "beta"}, ToolContext(workspace_root=str(workspace))
    )
    assert "notes.md:2" in result.content


async def test_shell_captures_output_and_exit_code(db, workspace):
    ctx = ToolContext(workspace_root=str(workspace))
    ok = await shell.run_shell_command({"command": "echo hi", "execution_mode": "direct"}, ctx)
    assert not ok.is_error and "hi" in ok.content

    bad = await shell.run_shell_command({"command": "exit 3", "execution_mode": "direct"}, ctx)
    assert bad.is_error and "exit code 3" in bad.content


async def test_shell_timeout_returns_a_result(db, workspace):
    ctx = ToolContext(workspace_root=str(workspace))
    result = await shell.run_shell_command(
        {"command": "sleep 5", "timeout_seconds": 1, "execution_mode": "direct"}, ctx
    )
    assert result.is_error and "timed out" in result.content


async def test_unknown_tool_lists_alternatives(db):
    reg = ToolRegistry(ConfirmationService(auto_approve))
    result = await reg.dispatch("nonexistent", {}, ToolContext())
    assert result.is_error and "unknown tool" in result.content


async def test_handler_exception_becomes_an_error_result(db):
    from psok.tools.base import RiskLevel, Tool

    async def explode(args, ctx):
        raise RuntimeError("boom")

    reg = ToolRegistry(ConfirmationService(auto_approve))
    reg.register(
        Tool(
            name="x",
            description="",
            parameters={"type": "object"},
            handler=explode,
            risk=RiskLevel.LOW,
        )
    )
    result = await reg.dispatch("x", {}, ToolContext())
    assert result.is_error and "boom" in result.content


async def test_every_dispatch_writes_an_audit_row(db, workspace):
    reg = registry_for(workspace)
    await reg.dispatch("list_files", {}, ToolContext(workspace_root=str(workspace)))
    rows = reg.logs.recent(5)
    assert rows and rows[0]["tool_name"] == "list_files"
    assert rows[0]["confirmation_decision"] == "auto"


def test_mcp_keys_do_not_collide():
    assert mcp_tool_key("search", "notes") != mcp_tool_key("search", "mail")


def test_truncation_marks_omission():
    assert "truncated" in truncate("x" * 200, limit=100)


def test_result_envelope():
    assert not ToolResult.ok("fine").is_error
    assert ToolResult.error("bad").is_error
