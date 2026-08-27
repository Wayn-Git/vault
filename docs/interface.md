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

**State is a word, not a lamp.** Every status used to be a small glowing dot,
half of them pulsing — nine on one screen is a christmas tree, and none of them
said what it meant without a tooltip: an amber dot beside a connector is either
"starting" or "needs sign-in", and the dot cannot tell you which. The colour
rule above still holds; it is carried by the word now, which can also be read.

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

**Nothing under the composer.** There was a signal strip there — one lit
channel per connector, with its live tool count. It was true, and it was still
the wrong thing in the loudest position on the screen: it repeated what the `+`
menu says, directly beneath the field you type in, and it was the first thing
the eye went to on a page whose subject is the conversation. The composer is the
message box and the controls that act on the message, and nothing else.

## The shape of it

```
main.jsx
└── AppProvider ............ store.jsx: view, health, conversations, capabilities
    └── App ................ one global keydown listener, the only one in the app
        ├── Sidebar ........ places, every conversation, and what the machine has
        ├── Chat ........... transcript, pins, composer, + menu, permission prompts
        ├── Capabilities ... Skills | Connectors — what is added and what could be
        ├── Automations .... beta: a prompt, an interval, and what happened
        ├── Tasks · Memory · Logs · Dashboard
        ├── CommandPalette . every action in one searchable list
        ├── Settings ....... general, models, permissions — and links to the pages
        └── Shortcuts ...... the keyboard reference
```

The rail holds the conversations because that is what a person switches between
most, and a top bar carrying both navigation and history ends up carrying
neither well. A conversation row opens on click, renames on `F2` or a double
click, and carries a `⋯` menu with rename and delete; deleting asks for a second
click rather than raising a modal, because a modal on every discarded
conversation is friction on the common case and an undo this interface cannot
honour would be a lie.

**One page per thing.** Settings (`⌘,`) used to carry a second, shorter Skills
page, a second Connectors page and a second Memory page beside the real ones in
the rail, and the Activity view carried a second copy of the standing-approval
list. Two implementations of one thing is two things to keep in step and one
more place to look, and the short copy was always the one missing whatever you
had come for — the Connectors panel in the settings could not finish an OAuth
sign-in, so the answer to half of what it showed you was "open the full view".
Settings now holds only what has nowhere else to live — general, models,
permissions — and lists the pages beneath them, going to the real one rather
than drawing a worse copy inside a dialog.

## Skills and connectors: one page, two tabs

They are the same kind of thing — something the agent is given — and they were
three surfaces: a Skills view, a Connectors view, and a Directory overlay that
browsed both. So a connector had a page where it was managed and a different
card where it was added, and a skill could appear twice with different controls
in each place. **Adding is now done where managing is done**, on one page
(`⌘3`) with a tab each.

**Skills.** Installed and installable in one list, installed first, because a
skill that exists in both places is one skill. The catalogue is read from its
source repositories at open time: the tree comes from the GitHub API, every
`SKILL.md`'s frontmatter is parsed for its real name and description, and the
result is cached for an hour. A hand-written list of titles would drift the
moment the source changed, so there isn't one — and when the network is not
there, the last good answer is served with the reason attached rather than an
invented one. Three ways in, and all three end in the same validated file:

- **New skill** — a name, a description and an instruction. That is what a skill
  *is* (ADR-0006): a directory with a `SKILL.md` whose frontmatter carries the
  first two and whose body is the third. Authoring one used to mean writing YAML
  by hand into a file at a path that had to match the name inside it, so the
  form takes the three fields and the backend composes the file. The description
  is quoted on the way in — a colon in ordinary English must not become a second
  YAML key — and the result goes through exactly the validation an installed
  skill goes through, so nothing authored here can be a skill the loader will
  only ever report as broken.
- **Import a link** — any `SKILL.md` URL, which is what the CLI's
  `psok skills --install` does.
- **Install** from a catalogue card.

The gear on an installed card engages it, stands it down, or uninstalls it.

**Connectors**, in three parts, and the split is the point.

**Connected** is what the agent can reach this second, with its live tool count.
**Added, not running** is everything configured that is contributing nothing —
each row saying what it is waiting for: `needs sign-in`, `failed to start`,
`off`. They were one table called "Added", which put a connector that had never
once worked beside four that were serving tools under a heading claiming they
were the same thing. They are not, and a permanently-failing connector among the
working ones makes the working ones look uncertain.

Then the catalogue: an icon and a name per row, two columns, eight of them under
**Featured** with **See more** for the rest. The tiles used to carry a
description, a transport, an auth badge and a collapsible setup note each — four
lines of explanation for a list whose only question is "which one". What a
service is is not in doubt; what it needs is a question for after you pick it,
and the row that manages it answers that.

Every row's controls are there: sign in, connect or disconnect, remove, and a
set-up panel that opens in place for the OAuth client and the environment
credentials a stdio server reads.

**Before the first turn, nothing has reconciled.** Connectors start when a turn
starts, so on a freshly booted server every one of them is *truthfully* idle —
and a page reporting six connectors as "not running" is the same wall of red as
six failures. It says `not started yet` instead, with one button that starts
them (`POST /api/mcp/reconcile`, which does exactly what the first turn does).

Searching either tab is itself a request to look through everything there is, so
it opens the catalogue without being asked.

Three decisions are load-bearing:

**Capabilities live in the store, not in the component that shows them.** The +
menu, the palette and the Skills tab are three views of one fact. Toggling a connector runs identical code from any of them,
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

The chain of thought is not the answer, and never renders as the reply.
`reasoning_delta` frames stream into their own panel *while they arrive* —
watching the thinking is the whole value of having it, and a collapsed block
that says "thinking" for forty seconds tells you nothing about whether the model
is on the right track. It folds itself to one line (`thought for 6s`) the moment
the answer starts, and opening or closing it by hand wins from then on, because
a panel that shuts on someone mid-sentence is worse than one that never opened.

**A turn ends when the answer does.** `done`, `guard` and `error` release the
composer immediately, even though the stream stays open behind them: memory
extraction is a second model call the loop runs *after* `done`. Waiting for the
stream to close instead is what used to put a second "thinking" line under a
finished answer and leave the field disabled for seconds after the reply had
landed. A `warning` frame is not terminal — the loop is continuing a turn that
came back empty or truncated — and the composer stays disabled through it.

**The transcript is not refetched when a turn ends.** It used to be, and the
refetch is what made every finished turn flicker and then lose its own thinking:
reasoning, warnings and the memory note are stream-only events that were never
written to the database, so replacing what was on screen with what was stored
silently deleted them a second after they appeared. Nor is it refetched while a
turn is running — sending the first message of a new conversation sets the
conversation id, and the fetch that fired on that used to race the stream and
replace the message that had just been typed.

The answer arrives exactly once: a streaming provider sends `assistant_delta`
and no `assistant_text`, a non-streaming one the reverse, and `done.text` — a
convenience repeat of the final answer — is deliberately not rendered.

## Pins

A message can be pinned from its header or with `⌘P`, which acts on the newest
one. A pin is a bookmark in a transcript that scrolls, and deliberately nothing
more: it is not sent to the model, does not change what is recalled, and does
not reorder history. If it did any of those, "pin this" would quietly mean
"change the conversation".

It is a column on the message rather than a table of its own — one bit about one
message, which goes when the message goes — and it is written against the
database row id, which is why pinning is offered on stored messages and not on
one still streaming. The strip above the transcript is what makes it worth
having: a pin you cannot get back to is a mark on a page nobody turns to. The
write is optimistic and rolls back if the server refuses, because waiting a
round trip to flip one boolean on a row already on screen only makes the button
feel broken.

## Automations — beta

`⌘4`, and marked beta in the rail, on the page and in the API payload. A prompt
and an interval, run as an ordinary turn in a conversation of its own.

The page states the two beta positions rather than burying them, because both
are surprising: **they run while PSOK is open** and not otherwise — there is no
daemon — and **an unattended turn cannot answer a permission prompt, so it does
not raise one**. Anything outside the user's standing approvals is refused, and
the run records `blocked` naming the exact operations it wanted, so the fix is
approving those deliberately rather than exempting scheduled work from the gate.

Both decisions, and what is deliberately absent, are argued in
[architecture/automation.md](architecture/automation.md).

## The permission prompt

A medium- or high-risk tool call suspends the turn, and the stream says so with
a `confirmation_required` frame. The prompt shows the arguments and the
**operation key** rather than the tool name: remembering an approval for
`run_shell_command:read-only` must not also approve a destructive command.

**Settings → Permissions** lists every standing approval — what now runs
without asking — with a button to revoke one, because a grant nobody can see is
a grant nobody can take back. `psok permissions` prints the same list. The
Activity view is the trail and only the trail; it used to carry a second copy of
this list.

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

It now lands in about a second rather than whenever the current model call
happens to finish. The event was previously only read between iterations, so
pressing Stop during a model round trip did nothing until it returned — with a
120s timeout and three retries, up to about eight minutes of a dead interface.
The call is raced against the stop request, and cancelling it aborts the HTTP
request rather than waiting for a response nobody wants. The same applies one
layer down: cancelling a tool call now abandons the work, not just the waiter,
so an abandoned call no longer blocks the next call to that connector.

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
