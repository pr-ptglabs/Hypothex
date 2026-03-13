# Hypothex Design Spec

**Project:** Hypothex — Runtime Debugging MCP Server for Claude Code
**Author:** PTG Labs
**Date:** 2026-03-13
**License:** MIT

## Overview

Hypothex is a runtime debugging system that enables Claude Code to follow a scientific observe-hypothesize-test-verify-fix loop. Instead of client libraries, Claude Code inserts raw HTTP POST calls into whatever code it's debugging. The MCP server collects these logs and exposes them back to Claude via MCP tools.

A single Python process runs two async servers:
- A FastAPI HTTP endpoint (port 3282) that accepts log posts from instrumented code
- An MCP server (stdio transport) that exposes tools for Claude to query those logs

## Architecture

```
Claude Code <-- stdio --> MCP Server --> SQLite (aiosqlite, WAL mode)
                                              ^
Instrumented Code -- HTTP POST :3282 --> FastAPI Collector --+
```

Both servers are launched concurrently via `asyncio.gather` in a single process. They use two separate `aiosqlite` connections to `~/.hypothex/hypothex.db` — one for writes (collector) and one for reads (MCP). WAL mode enables safe concurrent access across connections.

A shared `asyncio.Event` (`shutdown_event`) coordinates graceful shutdown: when either server exits (e.g., MCP stdin closes or uvicorn stops), the event is set, triggering cancellation of the other server. On Windows, shutdown is handled via `KeyboardInterrupt` (SIGTERM does not exist on Windows; `loop.add_signal_handler` is Unix-only).

### Transport

- **MCP:** stdio (Claude Code launches Hypothex as a subprocess)
- **Log collector:** HTTP on port 3282 (default), overridable via `HYPOTHEX_PORT` env var

### Session Identity

Running processes identify their session via the `HYPOTHEX_SESSION_ID` environment variable. Claude Code sets this before running instrumented code.

## File Structure

```
hypothex/
├── pyproject.toml
├── src/
│   └── hypothex/
│       ├── __init__.py
│       ├── main.py            # Entrypoint: asyncio.gather(mcp, collector)
│       ├── db.py              # SQLite schema, connection pool, query helpers
│       ├── models.py          # Pydantic models (LogEntry, query params)
│       ├── collector.py       # FastAPI app: POST /log endpoint
│       └── mcp_server.py      # MCP server: tool definitions and handlers
└── tests/
    ├── __init__.py
    ├── test_db.py
    ├── test_collector.py
    └── test_mcp_server.py
```

### Module Responsibilities

- **`main.py`** (~20 lines) — Initializes DB, creates `~/.hypothex/` directory, starts both servers via `asyncio.gather`, handles graceful shutdown.
- **`db.py`** — Schema creation, insert function, all query functions. The only module that touches SQLite directly.
- **`models.py`** — `LogEntry` pydantic model shared between collector (validation) and MCP (serialization).
- **`collector.py`** — FastAPI app with `POST /log` and `GET /health` routes. Validates input via pydantic, calls `db.insert_log()`. Enforces 1MB max payload size.
- **`mcp_server.py`** — MCP tool definitions and handlers. Each tool calls into `db.*` query functions.

## Log Entry Shape

```json
{
  "session_id": "string",
  "timestamp": "ISO8601",
  "level": "debug|info|warn|error",
  "message": "string",
  "data": {},
  "file": "string",
  "function": "string",
  "line": "number"
}
```

Required fields: `session_id`, `level`, `message`.
Optional fields: `timestamp` (server fills if missing), `data`, `file`, `function`, `line`.

## Storage

### Database Location

`~/.hypothex/hypothex.db` — keeps project directories clean, won't end up in git, survives reboots.

### Schema

```sql
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    data TEXT,          -- JSON serialized
    file TEXT,
    function TEXT,
    line INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_session_id ON logs(session_id);
CREATE INDEX idx_session_level ON logs(session_id, level);
CREATE INDEX idx_session_timestamp ON logs(session_id, timestamp);
```

- `created_at` is server-side receive time, used for ordering in `tail_logs`.
- `timestamp` is what the instrumented code claims — not trusted for ordering.
- WAL mode enabled at init for concurrent read/write support.
- Two separate `aiosqlite` connections: one for writes (collector), one for reads (MCP). This avoids interleaved operations on a shared connection.

### Cleanup

Manual only via `clear_session` MCP tool. No auto-cleanup or TTL in v1.

## Data Flow

### Writing Logs (Instrumented Code -> SQLite)

1. Instrumented code fires `POST http://localhost:3282/log` with JSON body (max 1MB)
2. FastAPI validates against `LogEntry` pydantic model (rejects payloads over 1MB)
3. Validation failure -> 422 response (caller ignores — fire-and-forget)
4. Valid entry -> `db.insert_log()` writes to SQLite
5. Return 201

### Reading Logs (Claude -> MCP -> SQLite)

1. Claude calls an MCP tool (e.g. `get_logs(session_id, level="error")`)
2. `mcp_server.py` handler calls the corresponding `db.*` query function
3. Query function builds a parameterized SQL query, executes against SQLite
4. Results returned as list of dicts, serialized back to Claude via MCP

## MCP Tools

### `get_logs(session_id, limit?, level?, since?)`

- `limit` defaults to 50. `level` filters to a single level. `since` is ISO8601 — returns logs with `created_at` after that time (server-side receive time, not client-provided timestamp).
- Returns list of log entries, ordered by `id ASC` (insertion order).

### `list_sessions(limit?)`

- `limit` defaults to 50. Returns the most recent sessions (by last activity).
- Returns list of `{session_id, log_count, first_seen, last_seen}`.
- Used by Claude to discover which session to query.

### `tail_logs(session_id, n?)`

- `n` defaults to 20. Returns the most recent N logs for the session.
- Ordered by `id DESC` then reversed — Claude sees chronological order, just the latest entries.

### `search_logs(session_id, query)`

- `LIKE '%query%'` against `message` and `data` columns.
- Note: search against `data` is a raw text match over serialized JSON. Results may include false positives from JSON key names or structural characters. This is acceptable for a debugging tool.
- Returns matching entries, ordered by `id ASC`.
- Capped at 100 results.

### `clear_session(session_id)`

- `DELETE FROM logs WHERE session_id = ?`
- Returns count of deleted rows.

## Error Handling

### Collector (FastAPI)

- Pydantic validation failures -> 422 (automatic)
- Malformed JSON -> 422 (automatic)
- DB write failures -> 500, error logged to stderr
- All errors are silent from instrumented code's perspective (fire-and-forget)
- Validation errors logged to stderr for visibility in Claude's terminal

### MCP Server

- Invalid tool arguments -> MCP error response with descriptive message
- DB read failures -> MCP error response, logged to stderr
- Nonexistent session_id -> empty list (not an error)

### Process-Level

- Port 3282 already in use -> log to stderr, exit with error
- SQLite DB can't be created/opened -> log to stderr, exit with error
- Graceful shutdown via shared `asyncio.Event` — when either server exits, the other is cancelled. On Windows, shutdown is triggered by `KeyboardInterrupt` (not SIGTERM). Close DB connections, stop uvicorn.

## How Claude Code Uses Hypothex

Claude Code does NOT use a client library. It inserts raw HTTP POST calls in whatever language the codebase uses. Example in Python:

```python
import httpx, os
httpx.post(f"http://localhost:{os.environ.get('HYPOTHEX_PORT', '3282')}/log", json={
    "session_id": os.environ.get("HYPOTHEX_SESSION_ID", "default"),
    "level": "debug",
    "message": "what happened here",
    "data": {"var": value},
    "file": __file__,
    "function": "function_name",
    "line": 42
})
```

Note: The snippet should use whatever HTTP library the project already has (e.g., `requests`, `httpx`, `urllib.request`). The example above uses `httpx` but is not prescriptive.

Snippet patterns for each language are documented in a skill file, not generated by an MCP tool.

### MCP Server Metadata

- **Server name:** `hypothex`
- **Version:** `0.1.0`

## Testing Strategy

**Test runner:** pytest with pytest-asyncio.

**`test_db.py`** — Unit tests against real in-memory SQLite:
- Schema creation
- Insert and query round-trips
- Filtering by level, since, session_id
- Search across message and data fields
- Clear session

**`test_collector.py`** — FastAPI TestClient (no real server):
- Valid log entry -> 201
- Missing required fields -> 422
- Invalid level value -> 422
- Large data payload -> accepted

**`test_mcp_server.py`** — Call MCP tool handlers directly (async functions over `db.*`):
- Each tool returns expected shape
- Edge cases: empty session, nonexistent session_id
- Limit/cap behavior

No mocks — every test hits a real in-memory SQLite instance.

## Dependencies

- `fastapi` — HTTP framework for collector
- `uvicorn` — ASGI server for FastAPI
- `aiosqlite` — Async SQLite driver
- `mcp` — MCP SDK for Python (stdio transport)
- `pydantic` — Data validation (bundled with FastAPI)
- `pytest` / `pytest-asyncio` — Testing (dev dependency)

## Constraints

- Everything in a single Python process
- Async throughout
- Fire-and-forget logger — never crashes or slows the host process
- Port 3282 default, overridable via `HYPOTHEX_PORT`
- DB at `~/.hypothex/hypothex.db`
- No auto-cleanup in v1
- No batched log ingestion in v1
- No snippet generator tool — handled via skill file
