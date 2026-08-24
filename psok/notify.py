"""Desktop notifications.

The narrowest possible surface: a title, a body, and best effort. PSOK has one
thing to say from outside a conversation -- a reminder is due -- and this is how
it says it.

Deliberately not abstracted into a notification *system*. There is no queue, no
retry, no history, and no delivery guarantee, because none of those would be
honest: a notification daemon that is not running drops the message and does not
say so, and pretending otherwise would be worse than the plain rule that
notifications arrive while a desktop session is there to receive them.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys

log = logging.getLogger(__name__)

# Said once per process. A machine with no notifier is a normal configuration
# (a server, a container, a stripped desktop), not an error to repeat every
# thirty seconds for as long as PSOK runs.
_warned = False


def _notifier() -> list[str] | None:
    """The argv prefix that shows a notification here, or None.

    Mirrors `desktop._opener`: ask the platform what it has rather than assume
    a compositor or a desktop environment.
    """
    if sys.platform == "darwin":
        return ["osascript", "-e"]
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-Command"]
    if shutil.which("notify-send"):
        return ["notify-send"]
    if shutil.which("kdialog"):
        return ["kdialog", "--passivepopup"]
    return None


def _argv(prefix: list[str], title: str, body: str) -> list[str]:
    if sys.platform == "darwin":
        # AppleScript string literals: only the quote and the backslash matter.
        def quote(value: str) -> str:
            return value.replace("\\", "\\\\").replace('"', '\\"')

        return [*prefix, f'display notification "{quote(body)}" with title "{quote(title)}"']
    if sys.platform == "win32":
        def quote(value: str) -> str:
            return value.replace("'", "''")

        return [
            *prefix,
            "[reflection.assembly]::LoadWithPartialName('System.Windows.Forms') > $null;"
            "$n = New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon = [System.Drawing.SystemIcons]::Information;"
            "$n.Visible = $true;"
            f"$n.ShowBalloonTip(10000, '{quote(title)}', '{quote(body)}', 'Info')",
        ]
    if prefix[0] == "kdialog":
        return [*prefix, f"{title}\n{body}", "10"]
    return [*prefix, "--app-name=PSOK", title, body]


def available() -> bool:
    return _notifier() is not None


async def notify(title: str, body: str) -> bool:
    """Show one notification. Returns whether it was handed off successfully.

    Never raises. The caller is a background tick, and a missing notification
    daemon must not be able to stop reminders from being marked as fired -- a
    reminder that cannot be shown is still a reminder that came due, and
    retrying it forever would produce a burst of them the moment a desktop
    session appeared.
    """
    global _warned
    prefix = _notifier()
    if prefix is None:
        if not _warned:
            _warned = True
            log.warning(
                "no desktop notifier on this system (looked for notify-send, kdialog);"
                " reminders will be recorded but not shown"
            )
        return False

    try:
        process = await asyncio.create_subprocess_exec(
            *_argv(prefix, title, body),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    except TimeoutError:
        log.warning("notifier did not exit; giving up on this notification")
        return False
    except OSError as exc:
        log.warning("could not run the desktop notifier: %s", exc)
        return False

    if process.returncode != 0:
        log.warning(
            "notifier exited %s: %s", process.returncode, stderr.decode(errors="replace").strip()
        )
        return False
    return True
