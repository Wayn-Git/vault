# The web interface

One React application over the HTTP API, built with Vite and no UI framework
behind it. It is the same product as the CLI, not a lesser one: everything the
agent can be given — skills, connectors, memory, a workspace root, a model — is
reachable from the composer or the command palette, and every prompt the
permission gate raises can be answered with the keyboard.

## Running it

```bash
cd frontend && npm install && npm run build   # once
psok serve --open                             # http://127.0.0.1:8000
```

`psok serve` is the whole product in one process: FastAPI serves the API under
`/api` and the built bundle everywhere else, so there is no second port and no
cross-origin request to configure. A path that is not a file falls through to
`index.html` for the client router; an unknown `/api/...` path still returns a
JSON 404, because a typo in a fetch should look like a missing endpoint and not
like HTML arriving where JSON was expected.

While working on the interface itself:

```bash
psok serve                 # or: uvicorn psok.api.main:app --reload
cd frontend && npm run dev # http://localhost:5173, proxying /api to :8000
```

The dev server proxies `/api`, so the browser makes same-origin requests and
CORS does not enter into it. `PSOK_CORS_ORIGINS` exists for the case where the
bundle really is served from somewhere else, and is deliberately not a wildcard:
this API runs shell commands on the machine.

## The design, and why it is this one

Stated so it can be argued with rather than absorbed as taste.

**The direction is an instrument panel.** PSOK sits open all day beside a
terminal and does real things to a real filesystem. That rules out the product
page look, and it rules out the two defaults generative design falls into: cream
with a serif, or acid green on black.

**Colour.** Warm graphite for every neutral — each one carries a little red,
which is what keeps it off the standard slate-blue dark theme. Colour itself is
spent on exactly three meanings and nothing else: green is running, amber is
waiting on you, coral is destructive. Nothing decorative is coloured, so the eye
goes to what is true.

**Type.** Space Grotesk names things, Archivo carries prose because it holds at
12px, IBM Plex Mono sets anything the machine reports — paths, tool names, key
hints, counts — because numbers that change should sit still. None of the three
is the face reached for on autopilot, and each was picked for a job.

**Icons.** One family (Phosphor) drawn on a 24px grid, at one weight. The marks
used to be hand-drawn paths and it showed; a row of icons now lines up because
the family says so.

**Motion.** Transform and opacity only, strong custom curves, nothing over
220ms, transitions rather than keyframes so a re-triggered animation retargets
instead of restarting. Menus scale from the control that opened them; modals
scale from their own centre because they are not anchored to anything. The
command palette does not animate at all — it opens dozens of times a day, and an
entrance on something that frequent reads as lag. `prefers-reduced-motion` stops
all of it.

**The signature.** The signal strip under the composer: one channel per
connector, lit only when its process is actually running, carrying the number of
tools it is contributing right now. Everything around it is quiet so it reads at
a glance.

## The shape of it

```
main.jsx
└── AppProvider ............ store.jsx: view, health, conversations, capabilities
    └── App ................ one global keydown listener, the only one in the app
        ├── Sidebar ........ places, every conversation, and what the machine has
        ├── Chat ........... transcript, composer, + menu, permission prompts
        ├── Tasks · Skills · Mcp · Memory · Logs · Dashboard
        ├── CommandPalette . every action in one searchable list
        ├── Directory ...... browse and install skills; add connectors
        ├── Settings ....... general, models, permissions, capabilities
        └── Shortcuts ...... the keyboard reference
```

The rail holds the conversations because that is what a person switches between
most, and a top bar carrying both navigation and history ends up carrying
neither well. Everything that is a setting rather than a conversation lives
behind **Customise** (`⌘,`), and everything installable behind the **Directory**
— reachable from the `+` menu, the palette, or settings.

## The directory

Two tabs, both browsable rather than a list of what you already have.

**Skills** are read from their source repositories at open time: the tree comes
from the GitHub API, every `SKILL.md`'s frontmatter is parsed for its real name
and description, and the result is cached for an hour. A hand-written list of
titles would drift the moment the source changed, so there isn't one — and when
the network is not there, the last good answer is served with the reason
attached rather than an invented one. `+` installs; the gear on an installed
card engages, stands down, or uninstalls it. A link to any `SKILL.md` still
installs directly, which is what the CLI's `psok skills --install` does.

**Connectors** are the bundled MCP catalogue, grouped by category, each tile
carrying what it will need before it can work — `no sign-in`, `oauth`, or the
setup steps written out in full.

## The connectors view

Popular additions, then `All / Connected / Not connected`, then one row per
configured server with its transport, what it is actually doing, and the
controls: sign in, connect or disconnect, remove, and a set-up panel that opens
in place for the OAuth client and the environment credentials a stdio server
reads. Status is the live fact — `12 tools live`, `on, not running`,
`needs sign-in`, `failed to start` — never merely what a switch was set to.

Three decisions are load-bearing:

**Capabilities live in the store, not in the component that shows them.** The +
menu, the chips under the composer, the palette and the Skills view are four
views of one fact. Toggling a connector runs identical code from any of them,
and the answer they render is what the process actually did — "running with 24
tools", or the error it failed with — not the intention that was recorded.

**Chat stays mounted.** Navigating to another view hides it rather than
unmounting it, because a turn is a live stream: unmounting mid-turn would drop
the reader and leave the loop running on the server with nobody listening.

**The `+` menu is the composer's whole surface.** Files, the working directory,
skills, connectors, the tool list and memory hang off one button beside the
message box, each in a submenu that opens in place. Nothing there is a display
of intent: a connector row starts the process and waits for the outcome, and
the toggle reports what came back.

**One keydown listener.** Every binding is resolved in `App`, from a normalised
chord string (`mod+shift+o`). Scattered handlers are how two components end up
owning Escape and neither wins reliably; here Escape closes what is open, and
only when nothing is open does it reach the running turn.

## The transcript

Answers are markdown, rendered to React elements by `components/Markdown.jsx`.
Nothing reaches `dangerouslySetInnerHTML`, so a model that emits a `<script>`
tag produces visible text rather than an execution — the reason it is written by
hand rather than delegated to a parser plus a sanitiser. It also has to survive
a half-finished document: an unterminated code fence is a normal intermediate
state when text arrives token by token, so every block parser closes itself at
end of input.

The chain of thought is not the answer. `reasoning_delta` frames render in a
separate collapsed block, never as the reply.

The answer arrives exactly once: a streaming provider sends `assistant_delta`
and no `assistant_text`, a non-streaming one the reverse, and `done.text` — a
convenience repeat of the final answer — is deliberately not rendered.

## The permission prompt

A medium- or high-risk tool call suspends the turn, and the stream says so with
a `confirmation_required` frame. The prompt shows the arguments and the
**operation key** rather than the tool name: remembering an approval for
`run_shell_command:read-only` must not also approve a destructive command.

The Activity view lists every standing approval — what now runs without asking
— with a button to revoke one, because a grant nobody can see is a grant nobody
can take back. `psok permissions` prints the same list.

It is answerable without the mouse — `Enter` allows, `Escape` denies, `R` arms
"remember this decision" — because the turn is suspended for as long as it takes
to answer. `GET /api/confirmations` recovers a prompt a page reload left
unanswered; it is a recovery path, not the primary one, since polling cannot say
which of two identical pending calls a response belongs to.

Pending prompts are process-wide, and each one carries the conversation it
suspended. A recovered prompt belonging to a different conversation is announced
as a line above the transcript with a way to open that conversation, rather than
raised as a modal over the one being read — approving a tool call whose context
is not on screen is not a decision anyone can make well.

## Keyboard

| | |
|---|---|
| `Ctrl/⌘ K` | Command palette — every action, searchable |
| `Ctrl/⌘ ⇧ O` | New conversation |
| `Ctrl/⌘ L` | Focus the composer |
| `Ctrl/⌘ /` | Files, skills, connectors, tools |
| `Ctrl/⌘ U` | Attach a file |
| `Ctrl/⌘ ,` | Settings |
| `Ctrl/⌘ M` | Memory on or off |
| `Ctrl/⌘ B` | Show or hide the rail |
| `Ctrl/⌘ 1…6` | Chat, Tasks, Skills, Connectors, Memory, Activity |
| `Ctrl/⌘ ↑ / ↓` | Previous / next conversation |
| `F2` | Rename the open conversation |
| `?` | The shortcut list |
| `Escape` | Close what is open, or stop the running turn |
| `Enter` / `⇧ Enter` | Send / new line |
| `/name` | Engage a skill; `↑` in an empty composer recalls the last message |

Stopping is a request, not an abort: `Escape` asks the server to end the turn,
which cancels the tool call in flight and closes the stream with a `guard`
frame. Aborting the browser's read instead would leave the loop running.

## Attachments, and what a file means here

A browser has no idea where a file is on disk, and PSOK's tools work on paths.
So a file dropped into the composer, pasted into it, or picked with `⌘U` is
uploaded to `~/.psok/attachments/<id>/<name>` first, and the message carries the
path it landed at — which `view_file`, `grep_files` and the shell then read like
any other file. The upload endpoint keeps only the basename, so a filename
containing `../` cannot place the file anywhere else.

## Plan before acting

The composer's **Plan** switch is not a mode the backend knows about; it is an
instruction prepended to the message asking for the steps and what each one will
touch, with nothing written or run that turn. It is a phrasing shortcut for
something people type by hand, kept honest by being exactly that.

## Connector setup in the browser

The Connectors view covers the whole path: the catalogue, adding a server, the
setup steps an entry needs before it can work, the OAuth client for providers
that have no dynamic registration, the login itself, and the environment
variables a stdio server takes its credentials through.

That last one is why `POST /api/mcp/servers/{name}/env` exists. Google Workspace
wants a client id and secret it obtained from Google Cloud; without an endpoint
for them the browser could add that connector and then not finish it. Secrets go
to the OS keychain and `mcp.yaml` keeps only a reference, exactly as the CLI
does it — and the server list reports which variables are set without ever
returning their values.

While a login is pending the view keeps polling `/api/mcp/authorizations`, so
the provider's sign-in URL appears as a link even when the browser that opened
it was on the machine running the backend rather than the one being used.
