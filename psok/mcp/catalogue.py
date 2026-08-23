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
    # Where a SETUP server's client credentials actually belong. PSOK's own
    # OAuth layer is consulted for remote transports only (see client.py's
    # `_transport`), so a stdio server that runs its own flow reads its client
    # id and secret from the environment instead. Without this mapping,
    # `set_oauth_client` wrote them to fields nothing downstream reads and then
    # reported success.
    client_id_env: str | None = None
    client_secret_env: str | None = None
    # Some read neither: they want a JSON file of their own. Same idea as the
    # two variables above -- put the credentials where this server actually
    # looks -- with the file's path and the keys it expects. The keychain stays
    # the source of truth; the file is written from it.
    credentials_file: str | None = None
    credentials_file_keys: dict[str, str] = field(default_factory=dict)
    # A stdio server that owns its OAuth exposes a tool to begin it. This is how
    # "Sign in" reaches the provider's real login page for such a server rather
    # than spawning the process and calling that authorization.
    auth_tool: str | None = None
    # Others sign in by being run differently rather than by exposing a tool --
    # a `--login` flag, or a second binary in the same package. Without this,
    # such a server can only be signed into by hand in a terminal, and PSOK's
    # Connect button would claim a sign-in it never performed.
    auth_command: str | None = None  # defaults to the entry's own command
    auth_command_args: list[str] = field(default_factory=list)
    # Some servers cannot begin their own flow without being told which account
    # it is for. Naming that here lets the interface ask for it generically
    # rather than special-casing one provider.
    account_hint_label: str | None = None
    # Connectors sharing this key share one signed-in account: signing into any
    # of them signs into all, and signing out of one signs out of all. The nine
    # Google applications are one Google account, and pretending otherwise would
    # mean nine identical sign-ins to the same address.
    shares_account_with: str | None = None
    # The server's own credential store, so signing out actually forgets the
    # account instead of leaving the next connect silently reusing it. Either a
    # directory or a single file -- a token cache is often just one file.
    credentials_path: str | None = None
    # Which files in that directory stand for a signed-in account. The default
    # matches Google's, whose credential files are named by address, and it
    # exists to exclude the `oauth_states.json` an abandoned flow leaves behind.
    # A server storing something else -- LinkedIn keeps a browser profile --
    # says so here, or it reports itself signed out forever.
    account_files: str = "*@*"
    # Where the store is one JSON file that exists before anyone signs in --
    # because the client credentials live in it too -- the key that appears
    # only once a sign-in has actually completed. Without this, storing a
    # client id would report the connector signed in, which is the exact claim
    # this module exists to stop making.
    account_key: str | None = None
    # Whether those filenames name the account. False where the store says only
    # that *someone* is signed in: better to render "Signed in" than to present
    # a profile directory's filename as if it were an address.
    account_from_filename: bool = True
    # Who is signed in, asked of the provider with the stored token. Only set
    # where one cheap unauthenticated-shaped GET answers it.
    identity_url: str | None = None
    identity_field: str | None = None

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


# One Google server, presented as the applications people actually think in.
#
# `workspace-mcp` covers nine Google services at once, and adding it put 122
# tools behind a single row called "Google Workspace" -- so wanting Gmail meant
# switching on Drive, Chat and Forms as well, and the row could not say what it
# was for. `--tools` selects the services one process registers, so each
# application here is its own connector with its own icon, its own on/off, and
# only its own tools.
#
# The account is shared on purpose. All of them read the same credential
# directory, so signing in once connects every Google app that is switched on,
# and signing out of one signs out of all -- which is the truth about a Google
# account, and less surprising than nine separate sign-ins to the same address.
GOOGLE_APPS: list[tuple[str, str, str, str]] = [
    ("gmail", "Gmail", "Communication", "Read, search, draft, send and label mail."),
    (
        "calendar",
        "Google Calendar",
        "Productivity",
        "Read and manage events across your calendars.",
    ),
    ("drive", "Google Drive", "Productivity", "Search Drive, read files and manage folders."),
    ("docs", "Google Docs", "Productivity", "Read, write and comment on documents."),
    ("sheets", "Google Sheets", "Productivity", "Read and write spreadsheet ranges."),
    ("slides", "Google Slides", "Creativity", "Read and build presentations."),
    ("forms", "Google Forms", "Productivity", "Build forms and read their responses."),
    ("tasks", "Google Tasks", "Productivity", "Read and manage task lists."),
    ("chat", "Google Chat", "Communication", "Read spaces and send messages."),
]

GOOGLE_SETUP_HINT = (
    "Google requires your own OAuth client rather than a shared one. You only do\n"
    "this once — every Google app then shares it.\n"
    "  1. console.cloud.google.com -> APIs & Services -> enable the APIs you want\n"
    "     (Gmail API, Calendar API, Drive API, …)\n"
    "  2. OAuth consent screen -> External -> add yourself as a test user\n"
    "  3. Credentials -> Create OAuth client ID -> *Web application*\n"
    "     Authorised redirect URI: http://localhost:8765/oauth2callback\n"
    "     (this exact URI — it is the server's own callback, not PSOK's)\n"
    "  4. Paste the client id and secret below, then press Connect."
)


def _google_apps() -> list[CatalogueEntry]:
    entries = []
    for service, title, category, description in GOOGLE_APPS:
        entries.append(
            CatalogueEntry(
                id=f"google-{service}",
                title=title,
                description=description,
                category=category,
                auth=AuthKind.SETUP,
                transport=Transport.STDIO,
                command="uvx",
                args=["workspace-mcp", "--single-user", "--tools", service],
                env={
                    # The server's own OAuth callback listener. Its default is
                    # 8000, which is where PSOK's API usually sits, so this pins
                    # a free port; the redirect URI registered with Google has
                    # to match it exactly. Bound lazily, only during a sign-in,
                    # so several of these can run at once.
                    "WORKSPACE_MCP_PORT": "8765",
                    "OAUTHLIB_INSECURE_TRANSPORT": "1",  # plain http on loopback
                    # Lets the callback accept a code whose flow state it does
                    # not hold, which is what allows the account to be chosen on
                    # Google's page rather than declared up front.
                    "MCP_SINGLE_USER_MODE": "1",
                },
                requires="uv (uvx) and a Google Cloud OAuth client",
                setup_hint=GOOGLE_SETUP_HINT,
                homepage="https://github.com/taylorwilsdon/google_workspace_mcp",
                client_id_env="GOOGLE_OAUTH_CLIENT_ID",
                client_secret_env="GOOGLE_OAUTH_CLIENT_SECRET",
                auth_tool="start_google_auth",
                credentials_path="~/.google_workspace_mcp/credentials",
                shares_account_with="google",
            )
        )
    return entries


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
        setup_hint=(
            "GitHub publishes no dynamic registration endpoint, so register one app once:\n"
            "  1. github.com/settings/developers -> New OAuth App\n"
            "  2. Authorization callback URL: http://127.0.0.1:33418/oauth/callback\n"
            "  3. Generate a client secret\n"
            "  4. Paste the client id and secret below, then sign in."
        ),
        identity_url="https://api.github.com/user",
        identity_field="login",
    ),
    # ----------------------------------------------------------------- google
    *_google_apps(),
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
    # ----------------------------------------------------------------- vercel
    CatalogueEntry(
        id="vercel",
        title="Vercel",
        description=(
            "Projects, deployments and deployment logs, plus Web Analytics and a search"
            " over Vercel's own documentation."
        ),
        category="Development",
        auth=AuthKind.OAUTH,
        transport=Transport.STREAMABLE_HTTP,
        url="https://mcp.vercel.com",
        # Vercel's authorization server publishes a registration_endpoint, so
        # unlike GitHub it registers PSOK itself and needs nothing registered by
        # hand. Scopes are left to discovery: the resource advertises `openid`
        # and naming more here would only narrow what it grants.
        homepage="https://vercel.com/docs/agent-resources/vercel-mcp",
    ),
    # ------------------------------------------------------------- microsoft
    CatalogueEntry(
        id="microsoft-todo",
        title="Microsoft To Do",
        description="Task lists, tasks and checklist items in Microsoft To Do.",
        category="Productivity",
        auth=AuthKind.SETUP,
        transport=Transport.STDIO,
        command="npx",
        args=["-y", "microsoft-todo-mcp"],
        requires="Node.js (npx)",
        setup_hint=(
            "Nothing to register. This server signs in with Microsoft's own public\n"
            "client, and asks only for the `Tasks.ReadWrite` scope — your To Do lists\n"
            "and nothing else: no mail, no files, no calendar.\n"
            "Connecting shows a short code and opens microsoft.com/devicelogin. Enter\n"
            "the code there and approve, and the connection completes on its own."
        ),
        homepage="https://github.com/fabienbutz/microsoft-todo-mcp",
        auth_tool="sign_in",
        # One cache file rather than a directory of accounts, and its name says
        # nothing about who is signed in.
        credentials_path="~/.config/microsoft-todo-mcp/token-cache.json",
        account_from_filename=False,
    ),
    # -------------------------------------------------------------- linkedin
    CatalogueEntry(
        id="linkedin",
        title="LinkedIn",
        description=(
            "Profiles, companies, jobs, the feed and your inbox, read through a real"
            " browser session rather than an API."
        ),
        category="Communication",
        auth=AuthKind.SETUP,
        transport=Transport.STDIO,
        command="uvx",
        args=["mcp-server-linkedin@latest"],
        requires="uv (uvx). The server downloads and manages its own Chromium.",
        setup_hint=(
            "Read this before connecting. LinkedIn has no API for this: the server\n"
            "signs into your real account in a browser and reads the pages as you\n"
            "would. Automated access is against LinkedIn's terms of service, and\n"
            "accounts do get restricted or banned for it. Connecting opens a browser\n"
            "window for you to sign in; the session is kept in ~/.linkedin-mcp/profile\n"
            "and signing out deletes it. Keep to one active session at a time."
        ),
        homepage="https://github.com/stickerdaniel/linkedin-mcp-server",
        # A browser profile, not a file per account: it says someone is signed
        # in without saying who.
        credentials_path="~/.linkedin-mcp/profile",
        account_files="*",
        account_from_filename=False,
        auth_command_args=["mcp-server-linkedin@latest", "--login"],
    ),
    # --------------------------------------------------------------- spotify
    CatalogueEntry(
        id="spotify",
        title="Spotify",
        description=(
            "Search, playback control, queue, saved tracks and playlist management."
        ),
        category="Media",
        auth=AuthKind.SETUP,
        transport=Transport.STDIO,
        command="npx",
        args=["-y", "@0xbarandiaran/spotify-mcp-server"],
        requires="Node.js (npx) and a Spotify developer app",
        setup_hint=(
            "This is a published fork of marcelmarais/spotify-mcp-server, updated for\n"
            "Spotify's February 2026 API change — the original is not on npm.\n"
            "Spotify requires your own app rather than a shared one:\n"
            "  1. developer.spotify.com/dashboard -> Create app\n"
            "  2. Redirect URI: http://127.0.0.1:8888/callback (this exact URI)\n"
            "  3. Paste the client id and secret below, then press Connect.\n"
            "Everything works on a free account except volume control, which Spotify\n"
            "allows only for Premium."
        ),
        homepage="https://github.com/marcelmarais/spotify-mcp-server",
        # This server reads no environment at all -- verified against its own
        # `getConfigFilePath`, which prefers ~/.spotify-mcp/config.json.
        credentials_file="~/.spotify-mcp/config.json",
        credentials_file_keys={
            "client_id": "clientId",
            "client_secret": "clientSecret",
            "redirect_uri": "redirectUri",
        },
        credentials_path="~/.spotify-mcp/config.json",
        # The config file exists as soon as the client id is stored, so only the
        # token a finished sign-in writes means signed in.
        account_key="accessToken",
        account_from_filename=False,
        auth_command_args=["-y", "-p", "@0xbarandiaran/spotify-mcp-server", "spotify-mcp-auth"],
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
