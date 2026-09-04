"""ffmpeg, for the one thing this needs it for.

A video has to become a small mono audio file before anything can transcribe it,
and `ffprobe` has to say how long it is before that is worth doing. Both go
through `wrap_command` under the sandbox policy, and the argv is built as a list
and joined once -- `backend/tools/builtin/convert.py`'s discipline, for the same
reason: a filename is not a place to find out about shell quoting.

24 kbps mono opus is roughly 11 MB an hour, which is why the fifteen-minute
duration cap lands comfortably under a 24 MB upload limit. The numbers are
chosen together; changing one without the other breaks the other.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import shutil
from pathlib import Path

from backend.security.sandbox import SandboxPolicy, wrap_command

log = logging.getLogger(__name__)

SAMPLE_RATE = "16000"
BITRATE = "24k"
DEFAULT_TIMEOUT = 300.0


class MediaError(RuntimeError):
    """ffmpeg could not do it. Carries a sentence fit to show someone."""


def ffmpeg_missing() -> str | None:
    """The install line, or None when it is there. Checked before downloading."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return None
    return (
        "ffmpeg is not installed, so audio cannot be extracted and reels cannot be"
        " transcribed. Install it with your package manager (apt install ffmpeg,"
        " brew install ffmpeg)."
    )


async def _run(argv: list[str], *, timeout: float, workspace: str) -> tuple[int, str]:
    # `wrap_command` takes a string and returns (argv, backend), so the quoting
    # happens once here via shlex rather than in each caller -- convert.py's
    # arrangement, and the reason a filename with a space is not an injection.
    wrapped, _backend = wrap_command(shlex.join(argv), SandboxPolicy.load(), workspace)
    process = await asyncio.create_subprocess_exec(
        *wrapped,
        cwd=workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise MediaError(f"ffmpeg did not finish within {timeout:.0f}s") from None
    output = (stdout or b"").decode(errors="replace") + (stderr or b"").decode(errors="replace")
    return process.returncode or 0, output


async def probe_duration(path: Path, *, timeout: float = 60.0) -> float | None:
    """How long the video is, in seconds, or None when ffprobe will not say.

    Measured, never estimated -- a duration guessed from file size is how a
    forty-minute upload gets sent to a transcription API as if it were a reel.
    """
    code, output = await _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        timeout=timeout,
        workspace=str(path.parent),
    )
    if code != 0:
        log.debug("ffprobe failed for %s: %s", path.name, output.strip()[:200])
        return None
    try:
        return float(output.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


async def extract_audio(
    source: Path, destination: Path, *, timeout: float = DEFAULT_TIMEOUT
) -> Path:
    """Video in, small mono audio out.

    Opus first, AAC second. A distro ffmpeg built without libopus is common
    enough that a stated fallback is better than a stated failure.
    """
    missing = ffmpeg_missing()
    if missing:
        raise MediaError(missing)

    attempts = [
        (destination.with_suffix(".ogg"), ["-c:a", "libopus", "-b:a", BITRATE]),
        (destination.with_suffix(".m4a"), ["-c:a", "aac", "-b:a", "32k"]),
    ]
    last = ""
    for target, codec in attempts:
        code, output = await _run(
            ["ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", SAMPLE_RATE]
            + codec
            + [str(target)],
            timeout=timeout,
            workspace=str(destination.parent),
        )
        if code == 0 and target.exists() and target.stat().st_size:
            return target
        target.unlink(missing_ok=True)
        last = output.strip()[-300:]
    raise MediaError(f"ffmpeg could not extract the audio: {last}")
