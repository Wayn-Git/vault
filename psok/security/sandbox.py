"""OS-native sandbox wrapping for shell commands (ADR-0009).

macOS uses Seatbelt (sandbox-exec), Linux uses Bubblewrap (bwrap), both invoked
as subprocess wrappers. Windows has no sandbox in v1 and is always direct-mode
plus confirmation -- stated plainly rather than faked.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from psok.config import paths

DEFAULT_SANDBOX_YAML = """\
# PSOK shell sandbox policy. Applies to sandbox-mode commands only.
enabled: true
denied_read_paths:
  - ~/.ssh
  - ~/.aws
  - ~/.gnupg
  - ~/.psok/config
allowed_write_paths:
  - /tmp
  - ~/.psok/cache
allow_network: true
"""


@dataclass
class SandboxPolicy:
    enabled: bool = True
    denied_read_paths: list[str] = field(default_factory=list)
    allowed_write_paths: list[str] = field(default_factory=list)
    allow_network: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> SandboxPolicy:
        p = path or paths().sandbox_yaml
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(DEFAULT_SANDBOX_YAML)
        raw = yaml.safe_load(p.read_text()) or {}
        return cls(
            enabled=raw.get("enabled", True),
            denied_read_paths=raw.get("denied_read_paths") or [],
            allowed_write_paths=raw.get("allowed_write_paths") or [],
            allow_network=raw.get("allow_network", True),
        )

    def expanded(self, values: list[str]) -> list[str]:
        return [str(Path(v).expanduser()) for v in values]


def platform_backend() -> str | None:
    """Which sandbox mechanism is usable here, if any."""
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "seatbelt"
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        return "bubblewrap"
    return None


def _seatbelt_profile(policy: SandboxPolicy, workspace: str) -> str:
    lines = ["(version 1)", "(allow default)", "(deny file-write*)"]
    for path in policy.expanded(policy.allowed_write_paths) + [workspace]:
        lines.append(f'(allow file-write* (subpath "{path}"))')
    for path in policy.expanded(policy.denied_read_paths):
        lines.append(f'(deny file-read* (subpath "{path}"))')
    if not policy.allow_network:
        lines.append("(deny network*)")
    return "\n".join(lines)


def wrap_command(
    command: str, policy: SandboxPolicy, workspace: str
) -> tuple[list[str], str | None]:
    """Return (argv, backend). Backend is None when no sandbox is available."""
    backend = platform_backend()
    if not policy.enabled or backend is None:
        return (["/bin/bash", "-c", command], None)

    if backend == "seatbelt":
        return (
            [
                "sandbox-exec",
                "-p",
                _seatbelt_profile(policy, workspace),
                "/bin/bash",
                "-c",
                command,
            ],
            backend,
        )

    argv = ["bwrap", "--dev-bind", "/", "/", "--die-with-parent"]
    for path in policy.expanded(policy.denied_read_paths):
        if Path(path).exists():
            argv += ["--tmpfs", path]
    if not policy.allow_network:
        argv.append("--unshare-net")
    argv += ["/bin/bash", "-c", command]
    return (argv, backend)


def unavailable_reason() -> str | None:
    if sys.platform == "win32":
        return "Windows has no sandbox in v1; shell commands run in direct mode with confirmation"
    if platform_backend() is None:
        missing = "sandbox-exec" if sys.platform == "darwin" else "bwrap (bubblewrap)"
        return f"{missing} is not installed; shell commands run in direct mode with confirmation"
    return None
