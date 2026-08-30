"""Converting a file with the tools already on the machine.

Every test names the mutation that makes it fail. The engines are not run here
-- that was done against real files, and what is worth locking down in a suite
is the routing and the sentence a missing engine produces.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.tools.base import ToolContext
from backend.tools.builtin.convert import convert_file, plan_conversion


def _ctx(root: Path) -> ToolContext:
    return ToolContext(conversation_id="c", workspace_root=str(root), events=asyncio.Queue())


@pytest.mark.parametrize(
    ("source", "target", "engine"),
    [
        ("holiday.png", "jpg", "magick"),
        ("holiday.heic", "png", "magick"),
        ("scan.pdf", "png", "magick"),
        ("song.wav", "mp3", "ffmpeg"),
        ("clip.mov", "mp4", "ffmpeg"),
        ("clip.mp4", "gif", "ffmpeg"),
        ("report.docx", "pdf", "soffice"),
        ("sheet.xlsx", "csv", "soffice"),
        ("notes.md", "pdf", "pandoc"),
        ("notes.md", "epub", "pandoc"),
        ("big.pdf", "pdf", "gs"),
    ],
)
def test_each_pair_goes_to_the_engine_that_owns_it(source, target, engine):
    """Routing by kind rather than by an exhaustive format table: the engines
    already know their own formats -- ImageMagick alone claims two hundred --
    and a second copy here would be one to keep in step and a way to refuse
    conversions that would have worked.

    Mutation check: swap any two branches in `plan_conversion`.
    """
    assert plan_conversion(Path(source), target)[0] == engine


def test_a_pair_nothing_handles_says_so_in_a_sentence():
    """Returned rather than raised, and a sentence rather than a code, because
    every caller does the same thing with it: shows it to the user.

    Mutation check: return a tuple for an unroutable pair.
    """
    answer = plan_conversion(Path("holiday.png"), "mp3")
    assert isinstance(answer, str)
    assert ".png" in answer and ".mp3" in answer
    assert "ImageMagick" in answer, "it says which engine covers what instead of just refusing"


@pytest.mark.asyncio
async def test_a_missing_engine_is_named_not_guessed_at(tmp_path, monkeypatch):
    """"converting .md to .epub needs pandoc, which is not installed here" is a
    sentence somebody can act on. A subprocess exit code is not, and neither is
    a traceback -- and pandoc really is absent on the machine this was written
    for.

    Mutation check: drop the `shutil.which` check and let the subprocess fail.
    """
    monkeypatch.setattr("backend.tools.builtin.convert.shutil.which", lambda name: None)
    source = tmp_path / "notes.md"
    source.write_text("# hello")

    result = await convert_file(
        {"source": str(source), "target_format": "epub"}, _ctx(tmp_path)
    )
    assert result.is_error
    assert "pandoc" in result.content and "not installed" in result.content


@pytest.mark.asyncio
async def test_it_will_not_quietly_replace_something(tmp_path):
    """The destination is the user's file. Overwriting one because the model
    guessed a path is not recoverable.

    Mutation check: drop the `destination.exists()` guard.
    """
    source = tmp_path / "a.png"
    source.write_bytes(b"not really a png")
    (tmp_path / "a.jpg").write_bytes(b"precious")

    result = await convert_file({"source": str(source), "target_format": "jpg"}, _ctx(tmp_path))
    assert result.is_error and "already exists" in result.content
    assert (tmp_path / "a.jpg").read_bytes() == b"precious"


@pytest.mark.asyncio
async def test_whether_it_is_possible_is_asked_before_whether_it_is_free(tmp_path):
    """The other order tells someone their file already exists when the real
    answer is that nothing here could have written it -- a true sentence about
    the wrong thing. Found by running it.

    Mutation check: move the `destination.exists()` check back above the route.
    """
    source = tmp_path / "a.png"
    source.write_bytes(b"x")
    (tmp_path / "a.mp3").write_bytes(b"in the way")

    result = await convert_file({"source": str(source), "target_format": "mp3"}, _ctx(tmp_path))
    assert result.is_error
    assert "nothing here converts" in result.content
    assert "already exists" not in result.content


@pytest.mark.asyncio
async def test_converting_a_file_to_its_own_format_is_refused(tmp_path):
    """It would resolve to the source path and overwrite the input mid-read.

    Mutation check: drop the same-path guard.
    """
    source = tmp_path / "a.png"
    source.write_bytes(b"x")
    result = await convert_file({"source": str(source), "target_format": "png"}, _ctx(tmp_path))
    assert result.is_error and "already" in result.content


@pytest.mark.asyncio
async def test_a_missing_source_is_a_sentence_not_a_traceback(tmp_path):
    """Mutation check: remove the `is_file` check."""
    result = await convert_file(
        {"source": str(tmp_path / "nope.png"), "target_format": "jpg"}, _ctx(tmp_path)
    )
    assert result.is_error and "no such file" in result.content
