"""The sandbox is a security claim, so it is verified against the real OS, not mocked."""

from __future__ import annotations

import pytest

from backend.security.sandbox import (
    SandboxPolicy,
    platform_backend,
    unavailable_reason,
    wrap_command,
)
from backend.tools.base import ToolContext
from backend.tools.builtin import shell

requires_sandbox = pytest.mark.skipif(
    platform_backend() is None, reason=f"no OS sandbox here: {unavailable_reason()}"
)


def test_policy_defaults_written_on_first_load(psok_home):
    policy = SandboxPolicy.load()
    assert policy.enabled
    assert any(".ssh" in p for p in policy.denied_read_paths)
    assert (psok_home / "config" / "sandbox.yaml").exists()


def test_direct_mode_is_never_wrapped(psok_home):
    argv, backend = wrap_command("echo x", SandboxPolicy(enabled=False), "/tmp")
    assert backend is None and argv[0] == "/bin/bash"


@requires_sandbox
def test_wrapped_command_uses_the_platform_backend(psok_home):
    argv, backend = wrap_command("echo x", SandboxPolicy.load(), "/tmp")
    assert backend in ("bubblewrap", "seatbelt")
    assert argv[0] in ("bwrap", "sandbox-exec")


@requires_sandbox
async def test_sandbox_masks_denied_credential_paths(db, psok_home, tmp_path):
    """The containment claim itself: a denied path must not be readable."""
    fake_home = tmp_path / "home"
    (fake_home / ".ssh").mkdir(parents=True)
    (fake_home / ".ssh" / "id_rsa").write_text("PRIVATE KEY")

    policy_file = psok_home / "config" / "sandbox.yaml"
    policy_file.parent.mkdir(parents=True, exist_ok=True)
    policy_file.write_text(
        f"enabled: true\ndenied_read_paths:\n  - {fake_home / '.ssh'}\n"
        f"allowed_write_paths:\n  - /tmp\nallow_network: true\n"
    )

    ctx = ToolContext(workspace_root=str(tmp_path))
    sandboxed = await shell.run_shell_command(
        {"command": f"cat {fake_home / '.ssh' / 'id_rsa'} 2>&1"}, ctx
    )
    assert "PRIVATE KEY" not in sandboxed.content

    direct = await shell.run_shell_command(
        {"command": f"cat {fake_home / '.ssh' / 'id_rsa'}", "execution_mode": "direct"}, ctx
    )
    assert "PRIVATE KEY" in direct.content, "direct mode is unrestricted by design"


@requires_sandbox
async def test_sandbox_still_allows_ordinary_work(db, psok_home, tmp_path):
    ctx = ToolContext(workspace_root=str(tmp_path))
    result = await shell.run_shell_command({"command": "echo hello from the sandbox"}, ctx)
    assert not result.is_error and "hello from the sandbox" in result.content
