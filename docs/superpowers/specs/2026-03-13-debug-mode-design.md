# Debug Mode Design Spec

## Overview

Add a structured debug loop to Hypothex that mirrors Cursor's Debug Mode: hypothesis generation, targeted instrumentation, runtime evidence collection, and verified fixes. Logs are linked to hypotheses via a many-to-many relationship so the agent can correlate runtime data back to what it was testing.

## Approach

Hybrid orchestration: a skill file (`debug-skill.md`) defines the workflow, while the MCP server tracks hypotheses and their linked logs as structured data. The server does not enforce workflow sequence — the skill handles that.

## Data Model Changes

### LogEntry model

New optional field:

```python
hypothesis_ids: list[str] | None = None
```

### New `hypotheses` table

```sql
CREATE TABLE hypotheses (
    id TEXT PRIMARY KEY,           -- globally unique: "{session_id}:h{n}"
    session_id TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed | rejected
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_hypotheses_session ON hypotheses(session_id);
```

ID format: `{session_id}:h{n}` where `n` is derived from `MAX` of existing hypothesis numbers for that session (not `COUNT`, to avoid collisions if hypotheses are ever deleted). Example: `debug-abc:h1`, `debug-abc:h2`.

### New `log_hypotheses` join table

```sql
CREATE TABLE log_hypotheses (
    log_id INTEGER NOT NULL REFERENCES logs(id) ON DELETE CASCADE,
    hypothesis_id TEXT NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
    PRIMARY KEY (log_id, hypothesis_id)
);
CREATE INDEX idx_log_hyp_hypothesis ON log_hypotheses(hypothesis_id);
```

### Insertion flow

When the collector receives a log with `hypothesis_ids`:
1. Insert the log row into `logs` (without hypothesis data), capture `lastrowid`
2. For each ID in `hypothesis_ids`, insert a row into `log_hypotheses` — silently skip any `hypothesis_id` that doesn't exist in `hypotheses` (fire-and-forget principle)

**Note:** `db.insert_log()` must be updated to return the inserted row's ID (`lastrowid`).

## New MCP Tools

### `create_hypothesis(session_id, description)`
- Auto-assigns globally unique ID as `{session_id}:h{n}` (uses MAX of existing numbers + 1)
- Returns `{id, session_id, description, status: "pending"}`

### `list_hypotheses(session_id)`
- Returns all hypotheses for a session with status and linked log count
- Format: `[{id, description, status, log_count, created_at}]`

### `update_hypothesis(hypothesis_id, status)`
- Sets status to `confirmed` or `rejected`
- Returns the updated hypothesis

### `get_hypothesis_logs(hypothesis_id)`
- Returns all logs linked to a hypothesis via the join table
- `hypothesis_id` is globally unique so `session_id` is not needed
- Same return format as `get_logs`

## Existing Tool Changes

Three existing tools gain an optional `hypothesis_id` parameter:

- **`get_logs(session_id, ..., hypothesis_id?)`** — filter to logs linked to a hypothesis
- **`tail_logs(session_id, n?, hypothesis_id?)`** — tail within a hypothesis
- **`search_logs(session_id, query, hypothesis_id?)`** — search within a hypothesis

When `hypothesis_id` is provided, these tools JOIN through `log_hypotheses`. When omitted, behavior is unchanged.

`list_sessions` remains unchanged.

`clear_session` is updated to also delete from `log_hypotheses` (via CASCADE on `logs.id` FK) and `hypotheses` for the session. Deletion order: delete from `logs` (cascades to `log_hypotheses`), then delete from `hypotheses`.

**Required:** `PRAGMA foreign_keys = ON` must be set on both DB connections in `db.connect()` (alongside the existing WAL pragma) for CASCADE deletes to work.

## Instrumentation Format

Injected logging is wrapped with comment markers for reliable cleanup:

```python
# hypothex:start debug-abc:h1 debug-abc:h3
try:
    import httpx, os
    httpx.post(f"http://localhost:{os.environ.get('HYPOTHEX_PORT', '3282')}/log", json={
        "session_id": os.environ.get("HYPOTHEX_SESSION_ID", "default"),
        "hypothesis_ids": ["debug-abc:h1", "debug-abc:h3"],
        "level": "debug",
        "message": "cache state after profile update",
        "data": {"cache_keys": list(cache.keys()), "user_id": user.id},
        "file": __file__, "function": "update_profile", "line": 42
    })
except Exception:
    pass
# hypothex:end debug-abc:h1 debug-abc:h3
```

**Marker format:** `# hypothex:start <full-ids...>` / `# hypothex:end <full-ids...>` (always use full globally unique IDs)

Language-specific comment syntax applies (`//` for JS/TS/Go, `#` for Python/Ruby/Shell).

The hypothesis IDs in the markers enable targeted cleanup — the agent can remove instrumentation for a rejected hypothesis while keeping others.

## Debug Skill Workflow (`debug-skill.md`)

### 1. Understand the bug
- User describes the bug
- Agent reads relevant code, error messages, context

### 2. Generate hypotheses
- Agent calls `create_hypothesis()` for 2-4 candidate root causes
- Ranks them by likelihood

### 3. Instrument
- Agent injects logging for the top hypothesis first (wrapped in `hypothex:start/end` markers)
- Logs linked via `hypothesis_ids`
- Agent tells user what to do to reproduce

### 4. Reproduce & analyze
- User reproduces the bug
- Agent calls `get_hypothesis_logs(h1)` to read runtime data
- Agent calls `update_hypothesis(h1, "confirmed")` or `update_hypothesis(h1, "rejected")`
- If rejected, moves to next hypothesis and instruments for that one

### 5. Fix
- Once root cause is confirmed, agent proposes and applies a fix
- Agent asks user to reproduce again to verify

### 6. Cleanup
- Agent removes all `hypothex:start/end` blocks from the codebase
- Agent calls `clear_session()` to clean up logs
- Final diff contains only the fix, no instrumentation

**Key constraint:** The agent must not jump from step 2 to step 5. Runtime evidence is required before proposing a fix.

## Files Changed

| File | Change |
|------|--------|
| `src/hypothex/models.py` | Add `hypothesis_ids` field to LogEntry |
| `src/hypothex/db.py` | Add `hypotheses` + `log_hypotheses` tables, hypothesis CRUD functions, update insert/query functions for join, `insert_log` returns `int` (lastrowid), enable `PRAGMA foreign_keys = ON` in `connect()` |
| `src/hypothex/collector.py` | Handle `hypothesis_ids` on log insertion |
| `src/hypothex/mcp_server.py` | Add 4 new tools, update 3 existing tools with `hypothesis_id` filter |
| `debug-skill.md` | New file: debug loop workflow guide |
| `tests/test_db.py` | Tests for hypothesis CRUD and log-hypothesis linking |
| `tests/test_collector.py` | Tests for `hypothesis_ids` in POST /log |
| `tests/test_mcp_server.py` | Tests for new tools and updated filters |
