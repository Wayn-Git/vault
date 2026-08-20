"""Skill discovery (ADR-0006).

A skill is a directory with a SKILL.md. Discovery caches only name, description
and path -- the body is read by the model through the ordinary view_file tool
when it decides the skill is relevant (progressive disclosure). There is no
invoke_skill tool, by design.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from psok.config import paths

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    version: str | None = None
    tags: list[str] | None = None


@dataclass
class SkillLoadError:
    path: Path
    error: str


def parse_skill_md(path: Path) -> tuple[Skill | None, str | None]:
    try:
        text = path.read_text()
    except OSError as exc:
        return None, f"unreadable: {exc}"

    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, "missing YAML frontmatter"
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        return None, f"invalid frontmatter: {exc}"

    name = meta.get("name")
    description = meta.get("description")
    if not name or not isinstance(name, str):
        return None, "frontmatter is missing 'name'"
    if not NAME_RE.match(name):
        return None, f"invalid name '{name}' (lowercase letters, digits and hyphens, max 64)"
    if name != path.parent.name:
        return None, f"name '{name}' does not match directory '{path.parent.name}'"
    if not description or not isinstance(description, str):
        return None, "frontmatter is missing 'description'"
    if len(description) > 1024:
        return None, "description exceeds 1024 characters"

    return (
        Skill(
            name=name,
            description=description.strip(),
            path=path,
            version=meta.get("version"),
            tags=meta.get("tags"),
        ),
        None,
    )


def scan(skills_dir: Path | None = None) -> tuple[list[Skill], list[SkillLoadError]]:
    root = skills_dir or paths().skills_dir
    skills: list[Skill] = []
    errors: list[SkillLoadError] = []
    if not root.exists():
        return skills, errors

    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            errors.append(SkillLoadError(child, "no SKILL.md"))
            continue
        skill, error = parse_skill_md(skill_md)
        if skill:
            skills.append(skill)
        else:
            errors.append(SkillLoadError(skill_md, error or "unknown error"))
    return skills, errors


def seed_builtin_skills(skills_dir: Path | None = None) -> list[str]:
    """Copy shipped skills into the user's directory without clobbering edits."""
    import shutil

    source = Path(__file__).parent / "builtin"
    target = skills_dir or paths().skills_dir
    target.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return []

    seeded = []
    for child in source.iterdir():
        if not child.is_dir():
            continue
        dest = target / child.name
        if dest.exists():
            continue
        shutil.copytree(child, dest)
        seeded.append(child.name)
    return seeded


def format_catalogue(skills: list[Skill]) -> str:
    """What goes in the system prompt: name, description, path. Never the body."""
    if not skills:
        return ""
    lines = ["<skills>"]
    for s in skills:
        lines.append(f'  <skill name="{s.name}" path="{s.path}">{s.description}</skill>')
    lines.append("</skills>")
    return "\n".join(lines)
