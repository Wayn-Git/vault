"""Turn one file into another, with the tools already on the machine.

The alternatives were weighed and both rejected on 2026-08-29:

* **ConvertAPI** (and every hosted converter) uploads the file. Sending a
  personal document to `v2.convertapi.com` to change its extension contradicts
  ADR-0013's local-first posture for exactly the data that posture is about.
* **VERT** is a good program and the wrong shape: a Svelte app running ffmpeg,
  ImageMagick and pandoc compiled to WebAssembly, so reaching those three means
  a browser and a wasm layer standing in front of binaries that are on `PATH`.
  Its video path needs a separate daemon on top.

So this shells out, like `run_shell_command` does, through the same sandbox and
with the same timeout discipline. What it adds over telling the model "run
ffmpeg" is a contract: one signature, a dispatch table that says which engine
owns which pair of formats, and a **named** failure when the engine for a
conversion is not installed. "converting .docx needs LibreOffice, which is not
installed here" is a sentence somebody can act on; a subprocess exit code is
not.

Deliberately not a format registry. The engines already know their own formats
-- ImageMagick alone claims two hundred -- and duplicating that list here would
be a second copy to keep in step and a way to refuse conversions that would
have worked. The table below routes by *kind*, and an unknown extension is
offered to the engine most likely to own it rather than rejected.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
from pathlib import Path
from typing import Any

from backend.security.sandbox import SandboxPolicy, wrap_command
from backend.tools.base import RiskLevel, Tool, ToolContext, ToolResult

#: Long enough for a video, short enough that a wedged process is noticed.
DEFAULT_TIMEOUT_S = 300

#: Extensions grouped by the engine that owns them. Not exhaustive on purpose:
#: it decides *routing*, not what is possible, and anything unlisted falls
#: through to the engine whose formats it most likely belongs to.
IMAGE = {
    "png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "tif", "ico", "heic",
    "avif", "svg", "psd", "xcf", "ppm", "pgm", "tga", "dds",
}
AUDIO = {"mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "wma", "aiff", "alac"}
VIDEO = {"mp4", "mkv", "webm", "mov", "avi", "wmv", "flv", "m4v", "mpg", "mpeg", "gifv"}
OFFICE = {
    "doc", "docx", "odt", "rtf", "xls", "xlsx", "ods", "csv", "ppt", "pptx",
    "odp", "pages", "numbers", "key",
}
MARKUP = {"md", "markdown", "rst", "org", "tex", "epub", "html", "htm", "docbook", "adoc"}

#: What to install when an engine is missing, said in the words of the thing
#: the user would type. Distributions disagree about package names; the command
#: is the honest common denominator.
ENGINES = {
    "magick": ("ImageMagick", "images"),
    "ffmpeg": ("ffmpeg", "audio and video"),
    "soffice": ("LibreOffice", "office documents"),
    "gs": ("Ghostscript", "PDF rewriting"),
    "pandoc": ("pandoc", "markup and ebooks"),
}


def _kind(extension: str) -> str:
    ext = extension.lower().lstrip(".")
    if ext in IMAGE:
        return "image"
    if ext in AUDIO:
        return "audio"
    if ext in VIDEO:
        return "video"
    if ext in OFFICE:
        return "office"
    if ext in MARKUP:
        return "markup"
    if ext == "pdf":
        return "pdf"
    return "unknown"


def plan_conversion(source: Path, target: str) -> tuple[str, str] | str:
    """Which engine handles this pair, or a sentence saying why none does.

    Returned rather than raised, and a sentence rather than a code, because
    every caller does the same thing with it: show it to the user. The order of
    the checks is the design -- a PDF is a target for almost everything and a
    source for very little, so it is asked about before the source's own kind.
    """
    source_kind = _kind(source.suffix)
    target_kind = _kind(target)

    if source_kind == "image" and target_kind in {"image", "pdf"}:
        return "magick", "image"
    if source_kind in {"audio", "video"} and target_kind in {"audio", "video", "image"}:
        return "ffmpeg", "media"
    if source_kind in {"office", "markup"} or target_kind in {"office"}:
        # LibreOffice converts markup too, and is here rather than pandoc
        # because it is installed on far more machines. Pandoc wins for the
        # pairs it is actually better at, below.
        if source_kind == "markup" and target_kind in {"markup", "office", "pdf"}:
            return "pandoc", "markup"
        return "soffice", "document"
    if source_kind == "pdf" and target_kind == "image":
        return "magick", "pdf-page"
    if source_kind == "pdf" and target_kind == "pdf":
        return "gs", "pdf"
    if source_kind == "pdf" and target_kind in {"office", "markup"}:
        return "soffice", "document"
    if target_kind == "pdf":
        return "soffice", "document"

    return (
        f"nothing here converts {source.suffix or 'that'} to .{target.lstrip('.')}."
        " Images go through ImageMagick, audio and video through ffmpeg,"
        " documents through LibreOffice, and markup through pandoc."
    )


def _argv(engine: str, shape: str, source: Path, destination: Path) -> list[str]:
    """The command for one conversion, as a list -- never a string.

    A filename with a space or a quote in it is ordinary, and building a shell
    string out of one is how a converted holiday photo becomes a command
    injection. `wrap_command` takes a string, so this is quoted once, centrally,
    by `shlex` at the call site rather than by each branch here.
    """
    if engine == "magick":
        if shape == "pdf-page":
            # A PDF is many pages and an image is one. `-density` before the
            # read is what makes the raster legible rather than 72dpi mush.
            return ["magick", "-density", "200", f"{source}[0]", str(destination)]
        return ["magick", str(source), str(destination)]
    if engine == "ffmpeg":
        # `-y` because the destination is checked before this runs, so the only
        # thing an interactive prompt could do here is hang the turn.
        return ["ffmpeg", "-y", "-i", str(source), str(destination)]
    if engine == "soffice":
        return [
            "soffice", "--headless", "--norestore",
            "--convert-to", destination.suffix.lstrip("."),
            "--outdir", str(destination.parent), str(source),
        ]
    if engine == "pandoc":
        return ["pandoc", str(source), "-o", str(destination)]
    if engine == "gs":
        return [
            "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/ebook", "-dNOPAUSE", "-dQUIET", "-dBATCH",
            f"-sOutputFile={destination}", str(source),
        ]
    raise ValueError(f"no command for engine {engine!r}")


async def convert_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    import shlex

    raw_source = (args.get("source") or "").strip()
    target = (args.get("target_format") or "").strip().lstrip(".").lower()
    if not raw_source:
        return ToolResult.error("convert_file needs a source path")
    if not target:
        return ToolResult.error("convert_file needs a target_format, like 'pdf' or 'mp3'")

    source = Path(raw_source).expanduser()
    if not source.is_file():
        return ToolResult.error(f"no such file: {source}")

    destination = (
        Path(args["destination"]).expanduser()
        if args.get("destination")
        else source.with_suffix(f".{target}")
    )
    if destination.resolve() == source.resolve():
        return ToolResult.error(
            f"{source.name} is already .{target}; converting it to itself would overwrite it"
        )
    # Whether the conversion is possible is asked before whether the
    # destination is free. The other order tells someone their file already
    # exists when the real answer is that nothing here could have written it --
    # which is a true sentence about the wrong thing.
    planned = plan_conversion(source, target)
    if isinstance(planned, str):
        return ToolResult.error(planned)
    engine, shape = planned

    if destination.exists() and not args.get("overwrite"):
        return ToolResult.error(
            f"{destination} already exists. Pass overwrite: true, or give another destination."
        )

    if shutil.which(engine) is None:
        label, covers = ENGINES[engine]
        return ToolResult.error(
            f"converting {source.suffix} to .{target} needs {label}, which is not installed"
            f" here. It covers {covers}; install it and try again."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    argv = _argv(engine, shape, source, destination)
    command = shlex.join(argv)

    workspace = str(Path(ctx.workspace_root or Path.cwd()).expanduser().resolve())
    wrapped, _backend = wrap_command(command, SandboxPolicy.load(), workspace)

    try:
        proc = await asyncio.create_subprocess_exec(
            *wrapped,
            cwd=str(destination.parent),
            env={**os.environ, "PSOK": "1"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return ToolResult.error(f"could not start {engine}: {exc}")

    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=DEFAULT_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ToolResult.error(
            f"{engine} did not finish within {DEFAULT_TIMEOUT_S}s and was killed"
        )
    except asyncio.CancelledError:
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        raise

    # LibreOffice names the output itself, from the source stem, and ignores a
    # destination filename that disagrees. Rather than fight it, move the file
    # it wrote to where the caller asked -- silently leaving the result under a
    # different name is how a converted file goes missing.
    if engine == "soffice":
        written = destination.parent / f"{source.stem}.{target}"
        if written.exists() and written != destination:
            written.replace(destination)

    if not destination.exists():
        detail = (err.decode(errors="replace") or "").strip().splitlines()
        reason = detail[-1] if detail else f"{engine} exited {proc.returncode} and wrote nothing"
        return ToolResult.error(f"conversion failed: {reason}")

    size = destination.stat().st_size
    return ToolResult.ok(
        f"converted {source.name} to {destination} ({size:,} bytes, via {ENGINES[engine][0]})"
    )


def tools() -> list[Tool]:
    return [
        Tool(
            name="convert_file",
            description=(
                "Convert a file to another format on this machine -- images,"
                " audio, video, documents, PDF. Nothing is uploaded. Give the"
                " target format, not a whole filename, unless the result needs"
                " to go somewhere specific."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Path of the file to convert."},
                    "target_format": {
                        "type": "string",
                        "description": "Extension to convert to, without the dot: pdf, mp3, png.",
                    },
                    "destination": {
                        "type": "string",
                        "description": (
                            "Where to write it. Defaults to the source path with the new"
                            " extension, which is usually what the user means."
                        ),
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Replace the destination if it already exists.",
                    },
                },
                "required": ["source", "target_format"],
            },
            handler=convert_file,
            risk=RiskLevel.MEDIUM,
            touches_paths=True,
        ),
    ]
