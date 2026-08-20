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
    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

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
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);

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
    created_at               TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at               TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(status, due_at);

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
