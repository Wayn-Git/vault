"""Installing a skill from a URL.

A skill is a directory with a SKILL.md in it (ADR-0006), so installing one is
mostly writing a file to the right place -- but the file has to be a valid skill
before it is written, and the name in its frontmatter is what decides where it
goes. Anything else lets a malformed download shadow a working skill, or land a
directory the loader will only ever report as broken.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import httpx

from psok.config import paths
from psok.mcp.ssrf import check_url
from psok.skills.loader import NAME_RE, Skill, parse_skill_md

# github.com/<owner>/<repo>/blob/<ref>/<path> is what a person copies out of the
# address bar; raw.githubusercontent.com is what serves the file.
_GITHUB_BLOB = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$"
)

MAX_BYTES = 512_000


class SkillInstallError(RuntimeError):
    pass


def to_raw_url(url: str) -> str:
    """Rewrite a GitHub page URL to the raw file it displays."""
    match = _GITHUB_BLOB.match(url.strip())
    if not match:
        return url.strip()
    owner, repo, ref, path = match.groups()
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"


async def fetch_skill_md(url: str) -> str:
    raw = to_raw_url(url)
    # The same guard the MCP transports use: a URL that resolves to a private
    # address must not be fetched just because it arrived through this door.
    check_url(raw)
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
        response = await client.get(raw)
    if response.status_code != 200:
        raise SkillInstallError(f"{raw} returned HTTP {response.status_code}")
    if len(response.content) > MAX_BYTES:
        raise SkillInstallError(f"{raw} is larger than {MAX_BYTES // 1000}kB")
    return response.text


def install_text(text: str, *, skills_dir: Path | None = None, overwrite: bool = False) -> Skill:
    """Validate a SKILL.md and place it under the name it declares.

    Written to a temporary directory and parsed there first: a download that
    turns out not to be a skill must not leave a half-installed directory
    behind, and it must never overwrite a working skill with a broken one.
    """
    root = skills_dir or paths().skills_dir
    root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        # The loader checks that the name matches its directory, so the file
        # has to be parsed once to learn where it belongs, then again in place.
        probe = staging / "probe"
        probe.mkdir()
        (probe / "SKILL.md").write_text(text)
        skill, error = parse_skill_md(probe / "SKILL.md")
        if skill is None and error and "does not match directory" not in error:
            raise SkillInstallError(error)

        name = _declared_name(text)
        if not name or not NAME_RE.match(name):
            raise SkillInstallError(
                "the file has no usable 'name' in its frontmatter"
                " (lowercase letters, digits and hyphens)"
            )

        staged = staging / name
        staged.mkdir()
        (staged / "SKILL.md").write_text(text)
        skill, error = parse_skill_md(staged / "SKILL.md")
        if skill is None:
            raise SkillInstallError(error or "not a valid skill")

        target = root / name
        if target.exists() and not overwrite:
            raise SkillInstallError(f"'{name}' is already installed")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(staged, target)

    installed, error = parse_skill_md(target / "SKILL.md")
    if installed is None:  # pragma: no cover - it parsed a moment ago
        raise SkillInstallError(error or "not a valid skill")
    return installed


def _declared_name(text: str) -> str | None:
    import yaml

    from psok.skills.loader import FRONTMATTER_RE

    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    name = meta.get("name")
    return name.strip() if isinstance(name, str) else None


async def install_from_url(url: str, *, overwrite: bool = False) -> Skill:
    return install_text(await fetch_skill_md(url), overwrite=overwrite)


def remove(name: str, *, skills_dir: Path | None = None) -> bool:
    """Delete an installed skill. Refuses anything that is not a plain name,
    because the name arrives from an HTTP path and `../` would be a delete
    anywhere on the machine."""
    if not NAME_RE.match(name or ""):
        raise SkillInstallError(f"'{name}' is not a skill name")
    root = (skills_dir or paths().skills_dir).resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root) or not target.is_dir():
        return False
    shutil.rmtree(target)
    return True
