"""Curated MCP servers the user can add with one click.

Every entry here was verified to exist at the time of writing. Entries are
templates, not magic: adding one writes an ordinary mcp.yaml entry the user can
edit or delete afterwards.

`auth` tells the interface what a one-click add actually requires:
  none        -- works immediately
  oauth       -- clicking through takes the user to the provider's own login page
  setup       -- needs credentials or a local file the user must supply first
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from psok.mcp.config import ServerConfig, Source, Transport


class AuthKind(enum.StrEnum):
    NONE = "none"
    OAUTH = "oauth"
    SETUP = "setup"


@dataclass
class CatalogueEntry:
    id: str
    title: str
    description: str
    category: str
    auth: AuthKind
    transport: Transport
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    oauth_scopes: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    requires: str | None = None  # what the user must have installed
    setup_hint: str | None = None  # shown when auth is SETUP
    homepage: str | None = None

    def to_server_config(self, name: str | None = None) -> ServerConfig:
        return ServerConfig(
            name=name or self.id,
            transport=self.transport,
            command=self.command,
            args=list(self.args),
            url=self.url,
            env=dict(self.env),
            oauth=self.auth is AuthKind.OAUTH,
            oauth_scopes=list(self.oauth_scopes),
            source=Source.BUNDLED,
            catalogue_id=self.id,
            description=self.description,
        )


CATALOGUE: list[CatalogueEntry] = [
    # ---------------------------------------------------------------- browser
    CatalogueEntry(
        id="playwright",
        title="Browser (Playwright)",
        description=(
            "Drive a real browser: navigate, click, fill forms, extract content, take"
            " screenshots. Works from the accessibility tree, so it does not depend on"
            " screenshots to decide what to click."
        ),
        category="Browser",
        auth=AuthKind.NONE,
        transport=Transport.STDIO,
        command="npx",
        args=["-y", "@playwright/mcp@latest"],
        requires="Node.js (npx)",
        homepage="https://github.com/microsoft/playwright-mcp",
    ),
    CatalogueEntry(
        id="chrome-devtools",
        title="Browser (Chrome DevTools)",
        description=(
            "Control Chrome through the DevTools protocol, including performance traces"
            " and network inspection. Use when debugging a page rather than just using it."
        ),
        category="Browser",
        auth=AuthKind.NONE,
        transport=Transport.STDIO,
        command="npx",
        args=["-y", "chrome-devtools-mcp@latest"],
        requires="Node.js (npx) and Chrome",
        homepage="https://github.com/ChromeDevTools/chrome-devtools-mcp",
    ),
    # ----------------------------------------------------------------- github
    CatalogueEntry(
        id="github",
        title="GitHub",
        description=(
            "Repositories, issues, pull requests, code search, actions and notifications"
            " through GitHub's own hosted MCP server."
        ),
        category="Development",
        auth=AuthKind.OAUTH,
        transport=Transport.STREAMABLE_HTTP,
        url="https://api.githubcopilot.com/mcp/",
        oauth_scopes=["repo", "read:org", "read:user", "gist", "notifications", "workflow"],
        homepage="https://github.com/github/github-mcp-server",
    ),
    # ----------------------------------------------------------------- google
    CatalogueEntry(
        id="google-workspace",
        title="Google Workspace",
        description=(
            "Gmail, Calendar, Drive, Docs, Sheets, Slides, Forms, Tasks and Chat in one"
            " server. Sign in once with Google and every surface is available."
        ),
        category="Google",
        auth=AuthKind.SETUP,
        transport=Transport.STDIO,
        command="uvx",
        args=["workspace-mcp"],
        # This server runs its own OAuth callback listener. Its default port is
        # 8000, which is also where PSOK's API usually sits, so the entry pins a
        # free one rather than letting the two fight over the socket. The
        # redirect URI registered with Google has to match this exactly.
        env={
            "WORKSPACE_MCP_PORT": "8765",
            "OAUTHLIB_INSECURE_TRANSPORT": "1",  # the callback is plain http on loopback
        },
        requires="uv (uvx) and a Google Cloud OAuth client",
        setup_hint=(
            "Google requires your own OAuth client rather than a shared one.\n"
            "  1. console.cloud.google.com -> APIs & Services -> enable the Gmail API"
            " (and Calendar/Drive if you want them)\n"
            "  2. OAuth consent screen -> External -> add yourself as a test user\n"
            "  3. Credentials -> Create OAuth client ID -> *Web application*\n"
            "     Authorised redirect URI: http://localhost:8765/oauth2callback\n"
            "  4. psok mcp env google-workspace GOOGLE_OAUTH_CLIENT_ID=<id>\n"
            "  5. psok mcp env google-workspace GOOGLE_OAUTH_CLIENT_SECRET=<secret> --secret\n"
            "The first tool call opens Google's own consent page in your browser."
        ),
        homepage="https://github.com/taylorwilsdon/google_workspace_mcp",
    ),
    # ------------------------------------------------------------------ local
    CatalogueEntry(
        id="fetch",
        title="Web Fetch",
        description="Fetch a URL and convert the page to markdown for the model to read.",
        category="Web",
        auth=AuthKind.NONE,
        transport=Transport.STDIO,
        command="uvx",
        args=["mcp-server-fetch"],
        requires="uv (uvx)",
        homepage="https://github.com/modelcontextprotocol/servers",
    ),
    CatalogueEntry(
        id="memory",
        title="Knowledge Graph Memory",
        description=(
            "A persistent knowledge graph of entities and relations. Complementary to"
            " PSOK's own memory: this one is explicitly curated by the model."
        ),
        category="Knowledge",
        auth=AuthKind.NONE,
        transport=Transport.STDIO,
        command="npx",
        args=["-y", "@modelcontextprotocol/server-memory"],
        requires="Node.js (npx)",
        homepage="https://github.com/modelcontextprotocol/servers",
    ),
]

CATALOGUE_BY_ID = {entry.id: entry for entry in CATALOGUE}


def get(entry_id: str) -> CatalogueEntry | None:
    return CATALOGUE_BY_ID.get(entry_id)


def by_category() -> dict[str, list[CatalogueEntry]]:
    grouped: dict[str, list[CatalogueEntry]] = {}
    for entry in CATALOGUE:
        grouped.setdefault(entry.category, []).append(entry)
    return grouped
