# Hypothex Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runtime debugging MCP server that collects HTTP log posts and exposes them to Claude Code via MCP tools.

**Architecture:** Two async servers (FastAPI HTTP collector + MCP stdio server) running via `asyncio.gather` in a single process, sharing a SQLite database with separate read/write connections in WAL mode.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, aiosqlite, mcp (FastMCP), pydantic, pytest, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-13-hypothex-design.md`

---

## Chunk 1: Project Scaffold and Data Layer

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/hypothex/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "hypothex"
version = "0.1.0"
description = "Runtime debugging MCP server for Claude Code"
license = "MIT"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.34.0",
    "aiosqlite>=0.21.0",
    "mcp>=1.0.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.25.0",
    "httpx>=0.28.0",
]

[project.scripts]
hypothex = "hypothex.main:main"
```

- [ ] **Step 2: Create src/hypothex/__init__.py**

```python
```

Empty file — just marks the package.

- [ ] **Step 3: Install the project in dev mode**

Run: `uv sync --all-extras` (if using uv) or `pip install -e ".[dev]"`
Expected: All dependencies install successfully.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml src/hypothex/__init__.py
git commit -m "feat: project scaffold with pyproject.toml"
```

---

### Task 2: Pydantic models

**Files:**
- Create: `src/hypothex/models.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create models.py**

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class LogEntry(BaseModel):
    session_id: str
    timestamp: str = ""
    level: Literal["debug", "info", "warn", "error"]
    message: str
    data: dict[str, Any] | None = None
    file: str | None = None
    function: str | None = None
    line: int | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def default_timestamp(cls, v: str) -> str:
        if not v:
            return datetime.now(timezone.utc).isoformat()
        return v

    def data_json(self) -> str | None:
        if self.data is None:
            return None
        return json.dumps(self.data)
```

- [ ] **Step 2: Create tests/__init__.py**

Empty file.

- [ ] **Step 3: Commit**

```bash
git add src/hypothex/models.py tests/__init__.py
git commit -m "feat: add LogEntry pydantic model"
```

---

### Task 3: Database layer — schema and insert

**Files:**
- Create: `src/hypothex/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for schema creation and insert**

Create `tests/test_db.py`:

```python
import pytest
import pytest_asyncio

from hypothex.db import Database


@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_connect_creates_table(db: Database):
    async with db._read_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='logs'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "logs"


@pytest.mark.asyncio
async def test_insert_and_get_logs(db: Database):
    await db.insert_log(
        session_id="s1",
        timestamp="2026-01-01T00:00:00Z",
        level="info",
        message="hello",
        data='{"key": "value"}',
        file="test.py",
        function="test_fn",
        line=10,
    )
    logs = await db.get_logs("s1")
    assert len(logs) == 1
    assert logs[0]["session_id"] == "s1"
    assert logs[0]["message"] == "hello"
    assert logs[0]["level"] == "info"
    assert logs[0]["data"] == '{"key": "value"}'
    assert logs[0]["file"] == "test.py"
    assert logs[0]["function"] == "test_fn"
    assert logs[0]["line"] == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `hypothex.db` does not exist.

- [ ] **Step 3: Implement Database class with schema and insert**

Create `src/hypothex/db.py`:

```python
from __future__ import annotations

import aiosqlite

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    data TEXT,
    file TEXT,
    function TEXT,
    line INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_session_id ON logs(session_id);
CREATE INDEX IF NOT EXISTS idx_session_level ON logs(session_id, level);
CREATE INDEX IF NOT EXISTS idx_session_timestamp ON logs(session_id, timestamp);
"""


class Database:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._write_conn: aiosqlite.Connection | None = None
        self._read_conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._write_conn = await aiosqlite.connect(self._db_path)
        self._read_conn = await aiosqlite.connect(self._db_path)
        await self._write_conn.execute("PRAGMA journal_mode=WAL")
        self._read_conn.row_factory = aiosqlite.Row
        for statement in _SCHEMA.strip().split(";"):
            stmt = statement.strip()
            if stmt:
                await self._write_conn.execute(stmt)
        await self._write_conn.commit()

    async def close(self) -> None:
        if self._write_conn:
            await self._write_conn.close()
        if self._read_conn:
            await self._read_conn.close()

    async def insert_log(
        self,
        *,
        session_id: str,
        timestamp: str,
        level: str,
        message: str,
        data: str | None = None,
        file: str | None = None,
        function: str | None = None,
        line: int | None = None,
    ) -> None:
        if self._write_conn is None:
            raise RuntimeError("Database not connected")
        await self._write_conn.execute(
            """\
            INSERT INTO logs (session_id, timestamp, level, message, data, file, function, line)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, timestamp, level, message, data, file, function, line),
        )
        await self._write_conn.commit()

    async def get_logs(
        self,
        session_id: str,
        *,
        limit: int = 50,
        level: str | None = None,
        since: str | None = None,
    ) -> list[dict]:
        if self._read_conn is None:
            raise RuntimeError("Database not connected")
        query = "SELECT * FROM logs WHERE session_id = ?"
        params: list = [session_id]
        if level:
            query += " AND level = ?"
            params.append(level)
        if since:
            query += " AND created_at > ?"
            params.append(since)
        query += " ORDER BY id ASC LIMIT ?"
        params.append(limit)
        async with self._read_conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/db.py tests/test_db.py
git commit -m "feat: database layer with schema, insert, and get_logs"
```

---

### Task 4: Database layer — remaining query functions

**Files:**
- Modify: `src/hypothex/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for list_sessions, tail_logs, search_logs, clear_session**

Append to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_get_logs_filter_by_level(db: Database):
    await db.insert_log(session_id="s1", timestamp="t1", level="info", message="a")
    await db.insert_log(session_id="s1", timestamp="t2", level="error", message="b")
    logs = await db.get_logs("s1", level="error")
    assert len(logs) == 1
    assert logs[0]["level"] == "error"


@pytest.mark.asyncio
async def test_get_logs_filter_by_since(db: Database):
    await db.insert_log(session_id="s1", timestamp="t1", level="info", message="old")
    # created_at is auto-set, so all entries will have similar times.
    # We test the query structure works — real time filtering is integration-level.
    logs = await db.get_logs("s1", since="1970-01-01T00:00:00")
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_list_sessions(db: Database):
    await db.insert_log(session_id="s1", timestamp="t1", level="info", message="a")
    await db.insert_log(session_id="s1", timestamp="t2", level="info", message="b")
    await db.insert_log(session_id="s2", timestamp="t3", level="info", message="c")
    sessions = await db.list_sessions()
    assert len(sessions) == 2
    s1 = next(s for s in sessions if s["session_id"] == "s1")
    assert s1["log_count"] == 2
    s2 = next(s for s in sessions if s["session_id"] == "s2")
    assert s2["log_count"] == 1


@pytest.mark.asyncio
async def test_tail_logs(db: Database):
    for i in range(30):
        await db.insert_log(
            session_id="s1", timestamp=f"t{i}", level="info", message=f"msg-{i}"
        )
    logs = await db.tail_logs("s1", n=5)
    assert len(logs) == 5
    # Should be in chronological order (oldest first of the tail)
    assert logs[0]["message"] == "msg-25"
    assert logs[4]["message"] == "msg-29"


@pytest.mark.asyncio
async def test_search_logs_message(db: Database):
    await db.insert_log(session_id="s1", timestamp="t1", level="info", message="hello world")
    await db.insert_log(session_id="s1", timestamp="t2", level="info", message="goodbye")
    logs = await db.search_logs("s1", "hello")
    assert len(logs) == 1
    assert logs[0]["message"] == "hello world"


@pytest.mark.asyncio
async def test_search_logs_data(db: Database):
    await db.insert_log(
        session_id="s1",
        timestamp="t1",
        level="info",
        message="check",
        data='{"user_id": "abc123"}',
    )
    await db.insert_log(session_id="s1", timestamp="t2", level="info", message="other")
    logs = await db.search_logs("s1", "abc123")
    assert len(logs) == 1
    assert logs[0]["message"] == "check"


@pytest.mark.asyncio
async def test_clear_session(db: Database):
    await db.insert_log(session_id="s1", timestamp="t1", level="info", message="a")
    await db.insert_log(session_id="s1", timestamp="t2", level="info", message="b")
    await db.insert_log(session_id="s2", timestamp="t3", level="info", message="c")
    count = await db.clear_session("s1")
    assert count == 2
    logs = await db.get_logs("s1")
    assert len(logs) == 0
    # s2 untouched
    logs = await db.get_logs("s2")
    assert len(logs) == 1


@pytest.mark.asyncio
async def test_get_logs_nonexistent_session(db: Database):
    logs = await db.get_logs("nonexistent")
    assert logs == []


@pytest.mark.asyncio
async def test_list_sessions_limit(db: Database):
    for i in range(10):
        await db.insert_log(
            session_id=f"s{i}", timestamp=f"t{i}", level="info", message="m"
        )
    sessions = await db.list_sessions(limit=3)
    assert len(sessions) == 3


@pytest.mark.asyncio
async def test_get_logs_limit(db: Database):
    for i in range(10):
        await db.insert_log(session_id="s1", timestamp=f"t{i}", level="info", message=f"m{i}")
    logs = await db.get_logs("s1", limit=3)
    assert len(logs) == 3
    assert logs[0]["message"] == "m0"
    assert logs[2]["message"] == "m2"
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `pytest tests/test_db.py -v`
Expected: New tests FAIL — methods not yet implemented.

- [ ] **Step 3: Implement remaining query methods on Database**

Add these methods to the `Database` class in `src/hypothex/db.py`:

```python
    async def list_sessions(self, *, limit: int = 50) -> list[dict]:
        if self._read_conn is None:
            raise RuntimeError("Database not connected")
        async with self._read_conn.execute(
            """\
            SELECT session_id,
                   COUNT(*) as log_count,
                   MIN(created_at) as first_seen,
                   MAX(created_at) as last_seen
            FROM logs
            GROUP BY session_id
            ORDER BY last_seen DESC
            LIMIT ?""",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def tail_logs(self, session_id: str, *, n: int = 20) -> list[dict]:
        if self._read_conn is None:
            raise RuntimeError("Database not connected")
        async with self._read_conn.execute(
            """\
            SELECT * FROM (
                SELECT * FROM logs
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) sub ORDER BY id ASC""",
            (session_id, n),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def search_logs(
        self, session_id: str, query: str, *, limit: int = 100
    ) -> list[dict]:
        if self._read_conn is None:
            raise RuntimeError("Database not connected")
        pattern = f"%{query}%"
        async with self._read_conn.execute(
            """\
            SELECT * FROM logs
            WHERE session_id = ?
              AND (message LIKE ? OR data LIKE ?)
            ORDER BY id ASC
            LIMIT ?""",
            (session_id, pattern, pattern, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def clear_session(self, session_id: str) -> int:
        if self._write_conn is None:
            raise RuntimeError("Database not connected")
        cursor = await self._write_conn.execute(
            "DELETE FROM logs WHERE session_id = ?",
            (session_id,),
        )
        await self._write_conn.commit()
        return cursor.rowcount
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/db.py tests/test_db.py
git commit -m "feat: add list_sessions, tail_logs, search_logs, clear_session to db layer"
```

---

## Chunk 2: HTTP Collector and MCP Server

### Task 5: FastAPI collector

**Files:**
- Create: `src/hypothex/collector.py`
- Create: `tests/test_collector.py`

- [ ] **Step 1: Write failing tests for the collector**

Create `tests/test_collector.py`:

```python
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from hypothex.collector import create_app
from hypothex.db import Database


@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def client(db: Database) -> TestClient:
    app = create_app(db)
    return TestClient(app)


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_post_log_valid(client: TestClient):
    resp = client.post(
        "/log",
        json={
            "session_id": "s1",
            "level": "info",
            "message": "test message",
        },
    )
    assert resp.status_code == 201


def test_post_log_with_all_fields(client: TestClient):
    resp = client.post(
        "/log",
        json={
            "session_id": "s1",
            "timestamp": "2026-01-01T00:00:00Z",
            "level": "error",
            "message": "full entry",
            "data": {"key": "value"},
            "file": "app.py",
            "function": "main",
            "line": 42,
        },
    )
    assert resp.status_code == 201


def test_post_log_missing_required_field(client: TestClient):
    resp = client.post(
        "/log",
        json={
            "session_id": "s1",
            "level": "info",
            # missing message
        },
    )
    assert resp.status_code == 422


def test_post_log_invalid_level(client: TestClient):
    resp = client.post(
        "/log",
        json={
            "session_id": "s1",
            "level": "critical",
            "message": "bad level",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_log_persists_to_db(db: Database):
    app = create_app(db)
    client = TestClient(app)
    client.post(
        "/log",
        json={
            "session_id": "s1",
            "level": "debug",
            "message": "persisted",
            "data": {"x": 1},
        },
    )
    logs = await db.get_logs("s1")
    assert len(logs) == 1
    assert logs[0]["message"] == "persisted"
    assert logs[0]["data"] == '{"x": 1}'


def test_post_log_malformed_json(client: TestClient):
    resp = client.post(
        "/log",
        content=b"not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


def test_post_log_payload_too_large(client: TestClient):
    resp = client.post(
        "/log",
        json={
            "session_id": "s1",
            "level": "info",
            "message": "x" * (1024 * 1024 + 1),
        },
    )
    assert resp.status_code == 413
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_collector.py -v`
Expected: FAIL — `hypothex.collector` does not exist.

- [ ] **Step 3: Implement the collector**

Create `src/hypothex/collector.py`:

```python
from __future__ import annotations

import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from hypothex.db import Database
from hypothex.models import LogEntry

MAX_PAYLOAD_BYTES = 1024 * 1024  # 1MB


def create_app(db: Database) -> FastAPI:
    app = FastAPI(title="Hypothex Collector")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/log", status_code=201)
    async def post_log(request: Request) -> JSONResponse:
        body = await request.body()
        if len(body) > MAX_PAYLOAD_BYTES:
            return JSONResponse(
                content={"detail": "Payload exceeds 1MB limit"},
                status_code=413,
            )
        try:
            entry = LogEntry.model_validate_json(body)
        except ValidationError as exc:
            return JSONResponse(
                content={"detail": exc.errors()},
                status_code=422,
            )
        try:
            await db.insert_log(
                session_id=entry.session_id,
                timestamp=entry.timestamp,
                level=entry.level,
                message=entry.message,
                data=entry.data_json(),
                file=entry.file,
                function=entry.function,
                line=entry.line,
            )
        except Exception as exc:
            print(f"[hypothex] DB write error: {exc}", file=sys.stderr)
            return JSONResponse(
                content={"detail": "Internal server error"},
                status_code=500,
            )
        return JSONResponse(content={"status": "ok"}, status_code=201)

    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_collector.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/collector.py tests/test_collector.py
git commit -m "feat: FastAPI collector with POST /log and GET /health"
```

---

### Task 6: MCP server

**Files:**
- Create: `src/hypothex/mcp_server.py`
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing tests for MCP tool handlers**

Create `tests/test_mcp_server.py`:

```python
import pytest
import pytest_asyncio

from hypothex.db import Database
from hypothex.mcp_server import create_mcp_server


@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def mcp(db: Database):
    return create_mcp_server(db)


async def _insert_sample_logs(db: Database):
    await db.insert_log(session_id="s1", timestamp="t1", level="info", message="first")
    await db.insert_log(session_id="s1", timestamp="t2", level="error", message="second")
    await db.insert_log(session_id="s2", timestamp="t3", level="debug", message="other session")


@pytest.mark.asyncio
async def test_get_logs_tool(db: Database, mcp):
    await _insert_sample_logs(db)
    tools = {t.name: t for t in await mcp.list_tools()}
    assert "get_logs" in tools
    result = await mcp.call_tool("get_logs", {"session_id": "s1"})
    assert not result.isError
    # Result content should contain both log entries
    text = result.content[0].text
    assert "first" in text
    assert "second" in text


@pytest.mark.asyncio
async def test_get_logs_filter_level(db: Database, mcp):
    await _insert_sample_logs(db)
    result = await mcp.call_tool("get_logs", {"session_id": "s1", "level": "error"})
    text = result.content[0].text
    assert "second" in text
    assert "first" not in text


@pytest.mark.asyncio
async def test_list_sessions_tool(db: Database, mcp):
    await _insert_sample_logs(db)
    result = await mcp.call_tool("list_sessions", {})
    text = result.content[0].text
    assert "s1" in text
    assert "s2" in text


@pytest.mark.asyncio
async def test_tail_logs_tool(db: Database, mcp):
    for i in range(30):
        await db.insert_log(session_id="s1", timestamp=f"t{i}", level="info", message=f"msg-{i}")
    result = await mcp.call_tool("tail_logs", {"session_id": "s1", "n": 5})
    text = result.content[0].text
    assert "msg-25" in text
    assert "msg-29" in text
    assert "msg-0" not in text


@pytest.mark.asyncio
async def test_search_logs_tool(db: Database, mcp):
    await _insert_sample_logs(db)
    result = await mcp.call_tool("search_logs", {"session_id": "s1", "query": "first"})
    text = result.content[0].text
    assert "first" in text
    assert "second" not in text


@pytest.mark.asyncio
async def test_clear_session_tool(db: Database, mcp):
    await _insert_sample_logs(db)
    result = await mcp.call_tool("clear_session", {"session_id": "s1"})
    text = result.content[0].text
    assert "2" in text  # 2 rows deleted
    logs = await db.get_logs("s1")
    assert len(logs) == 0


@pytest.mark.asyncio
async def test_get_logs_empty_session(db: Database, mcp):
    result = await mcp.call_tool("get_logs", {"session_id": "nonexistent"})
    assert not result.isError
    text = result.content[0].text
    assert "[]" in text or "no logs" in text.lower() or text.strip() == "[]"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL — `hypothex.mcp_server` does not exist.

- [ ] **Step 3: Implement the MCP server**

Create `src/hypothex/mcp_server.py`:

```python
from __future__ import annotations

import json
from typing import Annotated

from mcp.server.fastmcp import FastMCP

from hypothex.db import Database


def create_mcp_server(db: Database) -> FastMCP:
    mcp = FastMCP(name="hypothex")

    @mcp.tool(description="Get logs for a session, optionally filtered by level and time")
    async def get_logs(
        session_id: Annotated[str, "Session ID to query"],
        limit: Annotated[int, "Max number of logs to return"] = 50,
        level: Annotated[str | None, "Filter by log level (debug/info/warn/error)"] = None,
        since: Annotated[str | None, "ISO8601 timestamp — return logs received after this time"] = None,
    ) -> str:
        logs = await db.get_logs(session_id, limit=limit, level=level, since=since)
        return json.dumps(logs, indent=2)

    @mcp.tool(description="List all debugging sessions with log counts")
    async def list_sessions(
        limit: Annotated[int, "Max number of sessions to return"] = 50,
    ) -> str:
        sessions = await db.list_sessions(limit=limit)
        return json.dumps(sessions, indent=2)

    @mcp.tool(description="Get the most recent N logs for a session")
    async def tail_logs(
        session_id: Annotated[str, "Session ID to query"],
        n: Annotated[int, "Number of recent logs to return"] = 20,
    ) -> str:
        logs = await db.tail_logs(session_id, n=n)
        return json.dumps(logs, indent=2)

    @mcp.tool(description="Search logs by text query across message and data fields")
    async def search_logs(
        session_id: Annotated[str, "Session ID to query"],
        query: Annotated[str, "Text to search for in message and data fields"],
    ) -> str:
        logs = await db.search_logs(session_id, query)
        return json.dumps(logs, indent=2)

    @mcp.tool(description="Delete all logs for a session")
    async def clear_session(
        session_id: Annotated[str, "Session ID to clear"],
    ) -> str:
        count = await db.clear_session(session_id)
        return json.dumps({"deleted": count})

    return mcp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: MCP server with all 5 tools"
```

---

## Chunk 3: Entrypoint and Integration

### Task 7: Main entrypoint

**Files:**
- Create: `src/hypothex/main.py`

- [ ] **Step 1: Implement main.py**

```python
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import uvicorn

from hypothex.collector import create_app
from hypothex.db import Database
from hypothex.mcp_server import create_mcp_server

DEFAULT_PORT = 3282


def _get_db_path() -> str:
    db_dir = Path.home() / ".hypothex"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "hypothex.db")


async def _run() -> None:
    db_path = _get_db_path()
    port = int(os.environ.get("HYPOTHEX_PORT", str(DEFAULT_PORT)))

    db = Database(db_path)
    await db.connect()

    shutdown_event = asyncio.Event()

    # FastAPI collector
    app = create_app(db)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    async def run_collector() -> None:
        try:
            await server.serve()
        finally:
            shutdown_event.set()

    # MCP server
    mcp = create_mcp_server(db)

    async def run_mcp() -> None:
        try:
            await mcp.run_async(transport="stdio")
        finally:
            shutdown_event.set()

    # Shutdown watcher
    async def watch_shutdown() -> None:
        await shutdown_event.wait()
        server.should_exit = True

    try:
        await asyncio.gather(
            run_collector(),
            run_mcp(),
            watch_shutdown(),
        )
    except KeyboardInterrupt:
        pass
    finally:
        await db.close()
        print("[hypothex] Shutdown complete.", file=sys.stderr)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the entrypoint imports work**

Run: `python -c "from hypothex.main import main; print('OK')"`
Expected: Prints `OK`.

- [ ] **Step 3: Commit**

```bash
git add src/hypothex/main.py
git commit -m "feat: main entrypoint with asyncio.gather and graceful shutdown"
```

---

### Task 8: End-to-end smoke test

**Files:**
- Modify: `tests/test_collector.py` (or manual test)

- [ ] **Step 1: Manual smoke test**

In one terminal, start Hypothex:

```bash
python -m hypothex.main
```

In another terminal, post a log:

```bash
curl -X POST http://localhost:3282/log -H "Content-Type: application/json" -d '{"session_id":"test","level":"info","message":"smoke test","data":{"a":1}}'
```

Expected: Returns `{"status":"ok"}` with status 201.

Check health:

```bash
curl http://localhost:3282/health
```

Expected: Returns `{"status":"ok"}`.

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit any fixes**

If any fixes were needed, commit them.

```bash
git add -A
git commit -m "fix: address issues found in smoke testing"
```

---

### Task 9: Final cleanup

- [ ] **Step 1: Run full test suite one final time**

Run: `pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 2: Verify project installs cleanly**

Run: `pip install -e ".[dev]"` or `uv sync --all-extras`
Expected: Installs without errors.

- [ ] **Step 3: Final commit if needed**

```bash
git status
```

If there are uncommitted changes, commit them.
