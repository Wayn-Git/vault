# Ideas, with what they would actually cost

Wanted but not built. Each entry says what is already true on this machine, so
the next session picks up from the measurement rather than re-deriving it.

Written 2026-08-29. Anything measured here was measured that day.

## Recurring tasks, and a calendar that can be written to

The two most-implied capabilities of "personal OS" that are missing, and they
are one piece of work: a repeating task is a task with a schedule, and the
schedule is only useful if it can reach the calendar.

**Half of it is already readable.** Microsoft Graph exposes `recurrence` on a
`todoTask` and PSOK has never requested it, so the To Do side needs a field
added to the pull rather than a design. The local side does need one: a schema
slot on `tasks`, and a rule for what happens to a missed occurrence — does it
pile up, roll forward, or vanish? That decision is the actual work, and the
answer differs for "water the plants" and "pay the rent".

**Calendar is read-only here.** `list_calendar` and `find_free_slot` exist
(`psok/tools/builtin/tasks.py`); nothing creates an event, so `find_free_slot`
ends with the user booking it by hand. The first-party path is the one Mail now
uses — `psok/mail/gmail.py` refreshes the token the connector stored and calls
Google directly — and the same file would serve Calendar. Blocked only on the
calendar scope being granted at the next Google sign-in.

## Browser tabs, history and bookmarks

**The browser is Zen**, a Firefox fork:
`~/.config/zen/aivbe3un.Default (release)/`, touched while this was written,
holding **21,298 visits, 14,451 pages and 13 bookmarks**.

Reading it is cheap and entirely local:

- History and bookmarks are `places.sqlite` — ordinary SQLite, the same shape
  Firefox has used for years. It must be **copied before reading**: the browser
  holds a lock, and PSOK already copies a live database this way for the
  connector checks.
- Open tabs live in `sessionstore-backups/recovery.jsonlz4` — JSON behind
  Mozilla's `mozlz4` framing, which is lz4 with a magic header.

**Controlling those tabs is the hard half.** Zen is Firefox, so there is no
CDP; closing a tab or moving one between folders needs Firefox's remote agent
or a WebExtension talking to PSOK. Reading first is the honest order: a page
that can list and search everything you have looked at is most of the value,
and it needs no protocol at all.

**Browserbase is not the answer.** Its repository is archived and marked "no
longer maintained", the browser runs in their cloud, and it is paid. PSOK
already drives a local browser two ways — Playwright (24 tools) and
chrome-devtools (29) — and those two cost 2,977 tokens of schema on every round
trip between them. The want here is *your* browser and its real history, which
neither a cloud browser nor a fresh automated one has.

## Instagram reels into a knowledge base, and on to cinejoy

The most valuable-sounding one and the one with a blocker that is not PSOK's.

Reading DMs — which is what "send a reel to my account" means — needs an
Instagram **Professional** account, a Meta app, and permission review before
the messaging endpoints answer at all. That is a process with a queue in it,
not an afternoon.

**Scope the half that is not blocked first.** "A link goes in, a tagged note
comes out, and a film goes to cinejoy" is a pipeline PSOK can already almost
build: fetch the page, extract what it is, classify it, write it to the vault,
and post the subset that are films. Prove that with links pasted into a
conversation, and the Meta side becomes a different way to feed a thing that
already works rather than the thing itself.

## WhatsApp

**2Chat** is the only realistic route today: official MCP, 11 tools, a regular
number linked by QR. It is a **paid relay** — messages pass through their
infrastructure, and sending counts against the plan's quota. That is the trade,
and it is worth stating plainly rather than discovering later.

The local alternatives all still want `better-sqlite3`, which does not build on
this box's **Node 26**. Worth rechecking when it ships support, because a local
bridge changes the trade entirely.

## What is worth taking from Khoj

Read at `/home/wayne/Documents/GitHub/khoj`.

**Its ingestion, yes.** `src/khoj/processor/content/` handles org-mode, PDF,
DOCX, Notion and GitHub. PSOK's vault reads markdown and plain text, so
everything in a PDF on this machine is invisible to retrieval. That gap is the
difference between "notes I wrote" and "a second brain", and closing it is
file-format work rather than design work.

**Its operator, no.** `processor/operator/` gives Khoj a computer by running a
container with its own desktop: Docker, an Anthropic key, Claude-only. PSOK's
posture is local-first with Bubblewrap, it has no Anthropic key, and a second
sandbox model beside the one that already works is a lot of machinery for a
capability nobody has asked to use yet.

## The lever nobody has pulled

Restated because it is still the largest single win and it costs nothing to
take: **178 tools, 11,582 tokens of schema on every round trip**, against Groq's
free tier of 8,000 tokens per minute. The turn cannot fit, so it falls back to
the slower provider.

```
github           44 tools   3,007 tokens
chrome-devtools  29         1,771
linkedin         19         1,456
playwright       24         1,206
                            -----
                            7,440
```

Switching those four off leaves 62 tools at 4,142 tokens, which fits Groq
comfortably. **Tool profiles** — named sets of connectors, per conversation —
are the feature that makes the choice stick rather than being a settings chore
nobody repeats. `CapabilityService` already scopes connectors per conversation;
what is missing is the naming and the picker.
