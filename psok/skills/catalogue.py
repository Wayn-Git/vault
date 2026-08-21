"""A browsable directory of skills that can be installed.

The MCP side has had a catalogue since the beginning: a list of servers a person
can add with one click. Skills had nothing equivalent -- the interface could
list what was already on disk and nothing else, so "add a skill" meant knowing a
URL by heart.

This reads a real repository rather than shipping a hand-written list of titles
that would drift the moment the source changed: the tree is fetched from the
GitHub API, every SKILL.md's frontmatter is parsed for its real name and
description, and the result is cached for an hour so opening the directory twice
costs one round trip. When the network is not there, the last good answer is
served and, failing that, an empty list with the reason attached -- never an
invented one.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from psok.skills.loader import FRONTMATTER_RE, NAME_RE

USER_AGENT = "PSOK/0.1 (+skills catalogue)"
CACHE_TTL = 3600.0


@dataclass(frozen=True)
class Source:
    """A repository whose SKILL.md files are offered for installation."""

    id: str
    publisher: str
    repo: str  # owner/name
    ref: str = "main"
    homepage: str = ""


SOURCES: list[Source] = [
    Source(
        id="anthropic",
        publisher="Anthropic",
        repo="anthropics/skills",
        homepage="https://github.com/anthropics/skills",
    ),
]


@dataclass
class CatalogueSkill:
    id: str
    name: str
    description: str
    publisher: str
    source: str
    url: str
    path: str
    homepage: str = ""


@dataclass
class Catalogue:
    skills: list[CatalogueSkill] = field(default_factory=list)
    error: str | None = None
    fetched_at: float = 0.0


_cache: dict[str, Catalogue] = {}


def _raw_url(source: Source, path: str) -> str:
    return f"https://raw.githubusercontent.com/{source.repo}/{source.ref}/{path}"


def _frontmatter(text: str) -> tuple[str | None, str | None]:
    import yaml

    match = FRONTMATTER_RE.match(text)
    if not match:
        return None, None
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None, None
    name = meta.get("name")
    description = meta.get("description")
    if not isinstance(name, str) or not NAME_RE.match(name.strip()):
        return None, None
    return name.strip(), (description or "").strip() if isinstance(description, str) else ""


async def _read_source(client: httpx.AsyncClient, source: Source) -> list[CatalogueSkill]:
    tree = await client.get(
        f"https://api.github.com/repos/{source.repo}/git/trees/{source.ref}?recursive=1",
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    tree.raise_for_status()
    paths = [
        node["path"]
        for node in tree.json().get("tree", [])
        if node.get("path", "").endswith("/SKILL.md")
    ]

    async def one(path: str) -> CatalogueSkill | None:
        response = await client.get(_raw_url(source, path), headers={"User-Agent": USER_AGENT})
        if response.status_code != 200:
            return None
        name, description = _frontmatter(response.text)
        if not name:
            return None
        return CatalogueSkill(
            id=f"{source.id}/{name}",
            name=name,
            description=description or "",
            publisher=source.publisher,
            source=source.id,
            url=f"https://github.com/{source.repo}/blob/{source.ref}/{path}",
            path=path,
            homepage=source.homepage,
        )

    found = await asyncio.gather(*(one(path) for path in paths))
    return sorted((skill for skill in found if skill), key=lambda s: s.name)


async def fetch(*, force: bool = False) -> Catalogue:
    """Every installable skill across the configured sources."""
    cached = _cache.get("all")
    if cached and not force and time.monotonic() - cached.fetched_at < CACHE_TTL:
        return cached

    skills: list[CatalogueSkill] = []
    error: str | None = None
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=25.0) as client:
            for source in SOURCES:
                skills.extend(await _read_source(client, source))
    except Exception as exc:  # network, rate limit, or a moved repository
        error = f"{type(exc).__name__}: {exc}"
        if cached:
            # A stale list is more use than none; it says so through `error`.
            return Catalogue(skills=cached.skills, error=error, fetched_at=cached.fetched_at)

    catalogue = Catalogue(skills=skills, error=error, fetched_at=time.monotonic())
    if skills:
        _cache["all"] = catalogue
    return catalogue
