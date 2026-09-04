-- PSOK schema. See docs/architecture/data-model.md.
-- SQLite is the single relational engine (ADR-0002); documents live on the
-- filesystem and secrets live in the OS keychain (ADR-0004, ADR-0012).

CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- "don't ask again" preferences, keyed operation[:subtype] (ADR-0009)
CREATE TABLE IF NOT EXISTS confirmation_preferences (
    operation_key TEXT PRIMARY KEY,
    decision      TEXT NOT NULL CHECK (decision IN ('allow', 'deny')),
    risk_level    TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id                     TEXT PRIMARY KEY,
    title                  TEXT,
    provider               TEXT NOT NULL,
    model                  TEXT NOT NULL,
    -- Set when a scheduled run wrote this conversation rather than a person.
    -- Every run gets its own -- history is replayed into each model call, so
    -- one shared conversation would make each run slower than the last -- and
    -- without this they were indistinguishable from conversations someone
    -- started, so 26 of one machine's 50 rail entries were automation runs and
    -- real conversations fell off the end of the list.
    -- Deliberately not a foreign key: a run outlives the automation it came from.
    automation_id          TEXT,
    -- Which providers may answer for this conversation if `provider` cannot,
    -- as a JSON array of names. NULL means the default: every other configured
    -- provider, in providers.yaml's order. Per conversation rather than global
    -- because the right fallback for a long careful piece of work is not the
    -- right one for a throwaway question.
    fallback               TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_conversations_automation
    ON conversations(automation_id, created_at);

-- Normalized per-message rows, not one JSON blob per conversation (ADR-0017)
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content         TEXT,
    tool_calls      TEXT,   -- JSON: assistant turns that requested tools
    tool_call_id    TEXT,   -- tool results, linking back
    tool_name       TEXT,
    is_error        INTEGER NOT NULL DEFAULT 0,
    token_count     INTEGER,
    -- A message someone marked worth keeping in reach. On the message rather
    -- than in a table of its own: a pin has no life of its own, it is one bit
    -- about one message, and it goes when the message goes.
    pinned          INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_pinned
    ON messages(conversation_id, id) WHERE pinned = 1;

CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    path         TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    file_type    TEXT,
    size_bytes   INTEGER,
    mtime        REAL,
    title        TEXT,
    source       TEXT NOT NULL DEFAULT 'vault',
    indexed_at   TEXT,
    stale        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    heading_path TEXT,
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,   -- per chunk, for incremental re-index
    token_count  INTEGER,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON document_chunks(content_hash);


-- The lists a task can belong to. Microsoft To Do owns these when an account is
-- signed in: `external_id` is the Graph list id, and PSOK mirrors rather than
-- invents. A list with no `external_id` is local-only, which is what a machine
-- with no task connector gets.
CREATE TABLE IF NOT EXISTS task_lists (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    external_source TEXT,
    external_id     TEXT,
    -- The list a task goes in when nobody said which. Graph flags exactly one
    -- `defaultList`; locally there is one too, so "no list" is never a state.
    is_default      INTEGER NOT NULL DEFAULT 0,
    position        INTEGER,
    -- Set when the list is gone upstream. Kept rather than deleted, for the
    -- same reason a vanished task is cancelled: an outage and an emptied
    -- account look identical and only one of them is recoverable.
    retired_at      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_task_lists_external
    ON task_lists(external_source, external_id)
    WHERE external_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_task_lists_local_name
    ON task_lists(name)
    WHERE external_id IS NULL;


CREATE TABLE IF NOT EXISTS tasks (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    title                    TEXT NOT NULL,
    notes                    TEXT,
    due_at                   TEXT,   -- the deadline
    scheduled_at             TEXT,   -- when work happens; deliberately distinct
    duration_estimate_minutes INTEGER,
    status                   TEXT NOT NULL DEFAULT 'todo'
                             CHECK (status IN ('todo','in_progress','done','cancelled')),
    priority                 TEXT,
    source                   TEXT NOT NULL DEFAULT 'user',
    calendar_event_id        INTEGER REFERENCES calendar_events(id),
    -- When to say something. NULL means "at due_at"; a task with neither is
    -- never announced, which is the right default for a list you look at.
    reminder_at              TEXT,
    -- Stamped when the reminder actually fired. Written in the same
    -- transaction as the notification so a restart cannot repeat one.
    reminded_at              TEXT,
    -- Identity in whatever system this row was mirrored from, so a repeated
    -- pull updates the same row instead of adding another.
    external_source          TEXT,
    external_id              TEXT,
    external_etag            TEXT,
    last_synced_at           TEXT,
    -- Which list this belongs to. NULL only while a row predates the lists
    -- table or the account has never been synced; the service resolves it to
    -- the default on the next write.
    list_id                  INTEGER REFERENCES task_lists(id),
    -- Flagged by the user, not by the model. Distinct from `priority`, which
    -- is To Do's `importance` and is advisory: a task can be important with no
    -- deadline and no priority, which is the whole point of the bucket.
    important                INTEGER NOT NULL DEFAULT 0,
    -- Every category To Do holds for this task, as a JSON array. Kept because
    -- Graph's categories field is all-or-nothing on write: sending one tag
    -- would silently delete whatever else the user had tagged the task with.
    -- Written by the pull, read by the push. My Day is not among them -- it is
    -- the list the task is in, `list_id`, and nothing else.
    external_categories      TEXT,
    completed_at             TEXT,
    -- A local change that has not reached To Do yet. The push half of the sync
    -- reads exactly this; cleared when the upstream write returns.
    dirty_at                 TEXT,
    created_at               TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at               TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(status, due_at);
CREATE INDEX IF NOT EXISTS idx_tasks_list ON tasks(list_id, status);
-- The bucket scans, each of which runs on every Tasks page load. My Day is a
-- list, so `idx_tasks_list` above already covers it.
CREATE INDEX IF NOT EXISTS idx_tasks_important ON tasks(important, status) WHERE important = 1;
-- What the push half walks. Partial, because the overwhelming majority of rows
-- are clean and a full scan every fifteen minutes would be pure waste.
CREATE INDEX IF NOT EXISTS idx_tasks_dirty ON tasks(dirty_at) WHERE dirty_at IS NOT NULL;
-- The scan the reminder tick runs, twice a minute, forever.
CREATE INDEX IF NOT EXISTS idx_tasks_reminder ON tasks(reminded_at, reminder_at, due_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_external
    ON tasks(external_source, external_id)
    WHERE external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS calendar_events (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    title                TEXT NOT NULL,
    starts_at            TEXT NOT NULL,
    ends_at              TEXT NOT NULL,
    all_day              INTEGER NOT NULL DEFAULT 0,
    location             TEXT,
    busy                 INTEGER NOT NULL DEFAULT 1,
    source               TEXT NOT NULL DEFAULT 'local',
    external_id          TEXT,
    external_calendar_id TEXT,
    etag                 TEXT,
    last_synced_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_window ON calendar_events(starts_at, ends_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_external
    ON calendar_events(external_calendar_id, external_id)
    WHERE external_id IS NOT NULL;

-- Every tool call from every source. Arguments are redacted before write.
CREATE TABLE IF NOT EXISTS execution_logs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id       TEXT,
    message_id            INTEGER,
    tool_name             TEXT NOT NULL,
    tool_source           TEXT NOT NULL,
    arguments             TEXT,
    result_summary        TEXT,
    error                 TEXT,
    risk_level            TEXT,
    confirmation_decision TEXT,
    duration_ms           INTEGER,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_logs_conv ON execution_logs(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_logs_tool ON execution_logs(tool_name, created_at);

-- MCP servers whose first-call trust confirmation has been granted (security.md)
CREATE TABLE IF NOT EXISTS mcp_trusted_servers (
    server_name TEXT PRIMARY KEY,
    trusted_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Which skills and connectors are live, globally or for one conversation.
-- Scope is 'global' or a conversation id; the more specific row wins.
CREATE TABLE IF NOT EXISTS capability_state (
    scope      TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('skill', 'connector')),
    name       TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (scope, kind, name)
);

-- A named snapshot of capability_state's rows, so switching what a
-- conversation can reach is one action instead of toggling connectors one at
-- a time. Written because a provider's tool-schema budget (Groq: 128 tools,
-- 8,000 tokens/min) is exceeded by every connector switched on at once far
-- sooner than any one conversation actually needs them all -- see
-- docs/roadmap/ideas.md's "the lever nobody has pulled".
CREATE TABLE IF NOT EXISTS capability_profiles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Applying a profile is authoritative, not additive: every capability of a
-- kind the profile covers is set to exactly what is stored here, including
-- off for anything the profile omits -- otherwise applying "Search-only"
-- would leave whatever was already on still on, and the budget problem this
-- exists to fix would not actually be fixed.
CREATE TABLE IF NOT EXISTS capability_profile_items (
    profile_id INTEGER NOT NULL REFERENCES capability_profiles(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('skill', 'connector')),
    name       TEXT NOT NULL,
    enabled    INTEGER NOT NULL,
    PRIMARY KEY (profile_id, kind, name)
);

-- BETA. Automations: a turn that runs without anyone typing.
--
-- Deliberately the smallest thing that is honestly a scheduled turn: a prompt,
-- an interval, and a record of what happened. `next_run_at` is stored rather
-- than derived so "when does this run" is one read and does not depend on the
-- evaluator agreeing with the UI about arithmetic.
--
-- What this is NOT yet, and must not be claimed to be: cron expressions,
-- triggers other than time, retries, or anything that can answer a permission
-- prompt. An unattended turn cannot raise one, so it runs with the gate
-- denying everything that is not already a standing approval, and records that
-- it was blocked. See docs/architecture/automation.md before extending this.
CREATE TABLE IF NOT EXISTS automations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    every_minutes INTEGER NOT NULL,
    enabled       INTEGER NOT NULL DEFAULT 1,
    provider      TEXT,           -- NULL: whatever the machine's default is
    model         TEXT,
    next_run_at   TEXT NOT NULL,
    last_run_at   TEXT,
    last_status   TEXT,           -- ok | error | blocked | running
    last_summary  TEXT,
    last_conversation_id TEXT,    -- the transcript it wrote; not a foreign key,
                                  -- the record outlives a deleted conversation
    -- Which saved capability profile (backend/capabilities.py) this run's own
    -- conversation is scoped to. NULL: every enabled connector, same as before
    -- this column existed. Not a foreign key to capability_profiles(name) --
    -- a deleted profile must fail the run loudly, not silently widen a
    -- deliberately narrowed automation back to full access.
    capability_profile   TEXT,
    -- Consecutive `error` runs, reset to 0 by the next `ok`. Backs off
    -- next_run_at so a permanently broken automation is not retried every
    -- interval forever; a `blocked` run neither increments nor resets this,
    -- because a correct denial is not a failure to route around.
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_automations_due ON automations(enabled, next_run_at);

-- Long-term memory: the second tier of the two-tier design (docs/research/khoj.md).
-- Facts are superseded rather than deleted, so "what did PSOK believe last week,
-- and when did that change" stays answerable -- the transcript records what was
-- said, and this records what was concluded.
CREATE TABLE IF NOT EXISTS memories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fact            TEXT NOT NULL,
    conversation_id TEXT,          -- where it was learned; not a foreign key, the
                                   -- fact outlives a deleted conversation
    superseded_at   TEXT,          -- NULL while the fact is live
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_memories_live ON memories(superseded_at, created_at);

-- Memory on/off, globally or for one conversation, same scope convention as
-- capability_state. A separate table because capability_state's CHECK
-- constraint predates memory, and SQLite cannot alter a constraint in place --
-- adding a 'memory' kind there would fail on every database created before now.
CREATE TABLE IF NOT EXISTS memory_state (
    scope      TEXT PRIMARY KEY,
    enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Briefings and reviews: the day, written down.
--
-- One table for three kinds because they are the same shape -- an entry for a
-- date, built from signals, carrying prose and the user's own words. A briefing
-- looks forward at the morning, a daily review looks back at the evening, a
-- weekly rolls up the dailies; splitting them into three tables would duplicate
-- the claim, the signals column and every read.
--
-- `entry_date` is the LOCAL calendar date, the same rule `_now()` in
-- repositories.py states and for the same reason: SQLite's date('now') is UTC,
-- and a review filed under yesterday west of Greenwich is one nobody can find.
-- `created_at`/`updated_at` stay UTC like every other pair in this schema, and
-- the interface parses them with serverTime(). The two are never compared.
--
-- `signals` is the JSON the entry was written from -- the real counts, events
-- and items as they stood. Stored rather than recomputed so a review read in a
-- month still shows the day it was actually about, and so the prose can always
-- be checked against what it was given.
--
-- `kind` deliberately carries no CHECK. `memory_state` exists as a table of its
-- own only because capability_state's CHECK predates memory and SQLite cannot
-- alter one in place; a monthly rollup should not cost a table rebuild. The
-- service validates it and names the accepted values in the error.
--
-- Any column added here later carries a DEFAULT or is nullable:
-- `_add_missing_columns` refuses a NOT NULL column with no default and logs
-- rather than failing, which is a silently absent column.
CREATE TABLE IF NOT EXISTS journal_entries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL,          -- briefing | daily | weekly
    entry_date     TEXT NOT NULL,          -- local YYYY-MM-DD
    signals        TEXT NOT NULL,          -- JSON, always present
    summary        TEXT,                   -- the model's prose; NULL when none ran
    user_notes     TEXT,                   -- the user's own answers
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'complete')),
    -- Why there is no summary, when there is none. A briefing with no prose and
    -- no stated reason is indistinguishable from a broken one.
    model_error    TEXT,
    model_provider TEXT,
    model_name     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
-- The claim, owned by the database rather than by the runner looking first:
-- two overlapping ticks, or a restart mid-tick, must not produce two briefings.
CREATE UNIQUE INDEX IF NOT EXISTS idx_journal_day ON journal_entries(kind, entry_date);
CREATE INDEX IF NOT EXISTS idx_journal_recent ON journal_entries(entry_date DESC, id DESC);

-- Everything read, watched or listened to, logged as it is consumed.
--
-- The record is here; the text is a real file under ~/.psok/library, indexed by
-- the ordinary document indexer. So a library item is searchable by exactly the
-- machinery a vault note is, `search_documents` finds it without knowing it
-- exists, and the filesystem stays the source of truth for the text (ADR-0004)
-- rather than this table growing a second copy of it.
--
-- `document_id` NULL means no text was captured -- a paywall, a video with no
-- transcript, a fetch that failed. That is a normal state and not an error: the
-- item is still logged, still listed, still yours, and `capture_note` says why.
CREATE TABLE IF NOT EXISTS library_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,     -- book|article|newsletter|video|podcast|paper|note|other
    title        TEXT NOT NULL,
    url          TEXT,
    author       TEXT,
    site         TEXT,
    published_on TEXT,              -- from the page's own metadata only, never guessed
    consumed_on  TEXT NOT NULL,     -- local YYYY-MM-DD
    notes        TEXT,
    rating       INTEGER,           -- 1-5, the user's own; NULL until they say
    document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    text_path    TEXT,
    capture_note TEXT,              -- why the text is thin or absent, when it is
    word_count   INTEGER,
    -- What the model wrote about this item, and only ever from text that
    -- actually exists. NULL is the ordinary state for a reel with no caption and
    -- no speech; `enrichment_note` says which, in a sentence.
    summary          TEXT,
    tags             TEXT,     -- JSON array of strings
    resources        TEXT,     -- JSON array of {type, name, detail, url}
    enrichment_note  TEXT,     -- why there is no summary, when there is none
    enrichment_model TEXT,     -- "provider:model", so what wrote it stays answerable
    enriched_at      TEXT,
    -- Where the indexed text came from. 'caption' and 'transcript' are words
    -- somebody actually wrote or said; 'none' is the honest empty state, and is
    -- what forbids enrichment outright rather than by asking a prompt nicely.
    text_source      TEXT,     -- caption | transcript | page | notes | none
    thumbnail_path   TEXT,
    media_path       TEXT,     -- the video, while it is kept; NULL once discarded
    duration_seconds INTEGER,  -- from ffprobe, never estimated
    -- External identity for things that arrive rather than being pasted, e.g.
    -- "instagram:media:17895..." or "instagram:reel:{video_id}". Not unique --
    -- saving the same reel again a year later is a real event -- but it is what
    -- lets an ingest offer the existing row instead of making a second one.
    source_ref       TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_library_source_ref
    ON library_items(source_ref) WHERE source_ref IS NOT NULL;
-- Not unique: re-reading something a year later is a real event worth logging
-- twice. Capture looks here first and offers what it finds rather than refusing.
CREATE INDEX IF NOT EXISTS idx_library_url ON library_items(url) WHERE url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_library_consumed ON library_items(consumed_on DESC, id DESC);

-- How PSOK writes when it writes *for* the user rather than *to* them.
--
-- Exactly one row, pinned by the CHECK, because a person has one voice here. A
-- table rather than a JSON blob in app_settings: these are fields with types,
-- `_add_missing_columns` can add a tenth to a database that already exists, and
-- a blob can do neither.
--
-- Every field is optional and an empty profile injects nothing at all -- a
-- <brand> block of blank headings costs context on every turn and tells the
-- model the user has no voice, which is worse than saying nothing.
CREATE TABLE IF NOT EXISTS brand_profile (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    enabled     INTEGER NOT NULL DEFAULT 1,
    name        TEXT,
    mission     TEXT,
    audience    TEXT,
    voice       TEXT,
    values_list TEXT,   -- JSON array of strings; `values` is a reserved word
    do_list     TEXT,   -- JSON array of strings
    dont_list   TEXT,   -- JSON array of strings
    palette     TEXT,   -- JSON array of {name, hex}
    fonts       TEXT,   -- JSON array of {role, family}
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Inbound Instagram webhooks, written down before they are acted on.
--
-- The table exists because Meta wants a 200 within seconds and the work behind
-- one delivery -- a Graph call, a video download, ffmpeg, a transcription, a
-- model call -- takes minutes. A FastAPI BackgroundTask dies with the process,
-- so a crash between the acknowledgement and the capture is a reel the user
-- watched Instagram accept and then never saw, with no retry because we already
-- said 200. Here the acknowledgement means "written down", and a runner drains
-- it -- the same bargain automations and the journal already make.
--
-- `payload` is the entry verbatim. Reprocessing after a bug is then setting
-- status back to 'queued', rather than re-parsing a body nobody kept.
CREATE TABLE IF NOT EXISTS instagram_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- One webhook *fact*, stable across Meta's retries: "mention:{media}:{comment}"
    -- or "dm:{mid}", falling back to a hash of the entry when it carries neither.
    delivery_key    TEXT NOT NULL,
    route           TEXT NOT NULL,   -- mention|dm_reel|dm_share|dm_link|unsupported
    sender_id       TEXT,            -- the IGSID of whoever sent it
    payload         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'working', 'done', 'failed', 'ignored')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    library_item_id INTEGER REFERENCES library_items(id) ON DELETE SET NULL,
    note            TEXT,            -- why it failed or was ignored, in a sentence
    received_at     TEXT NOT NULL DEFAULT (datetime('now')),
    started_at      TEXT,
    finished_at     TEXT
);
-- The idempotency key, owned by the database rather than by the handler looking
-- first. Meta re-delivers anything it did not see a 200 for, and two deliveries
-- of one comment must not become two rows in the library.
CREATE UNIQUE INDEX IF NOT EXISTS idx_ig_delivery ON instagram_events(delivery_key);
CREATE INDEX IF NOT EXISTS idx_ig_pending ON instagram_events(status, id);
