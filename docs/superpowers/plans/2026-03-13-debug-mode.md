# Debug Mode Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hypothesis-driven debugging to Hypothex — create hypotheses, link logs to them via many-to-many, query by hypothesis, and guide Claude through a structured debug loop via a skill file.

**Architecture:** New `hypotheses` and `log_hypotheses` tables in SQLite. Hypothesis CRUD + log linking in db.py. Four new MCP tools + hypothesis_id filter on three existing tools. Collector handles `hypothesis_ids` list on POST /log. Skill file orchestrates the workflow.

**Tech Stack:** Python 3.11+, aiosqlite, FastAPI, FastMCP, Pydantic, pytest

**Spec:** `docs/superpowers/specs/2026-03-13-debug-mode-design.md`

---

## Chunk 1: Data Layer

### Task 1: Schema + Foreign Keys + Model

**Files:**
- Modify: `src/hypothex/models.py`
- Modify: `src/hypothex/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write test for new tables and FK pragma**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_hypotheses_table_exists(db: Database):
    async with db._read_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='hypotheses'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_log_hypotheses_table_exists(db: Database):
    async with db._read_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='log_hypotheses'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_foreign_keys_enabled(db: Database):
    async with db._read_conn.execute("PRAGMA foreign_keys") as cursor:
        row = await cursor.fetchone()
    assert row[0] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py::test_hypotheses_table_exists tests/test_db.py::test_log_hypotheses_table_exists tests/test_db.py::test_foreign_keys_enabled -v`
Expected: FAIL — tables don't exist, pragma not set

- [ ] **Step 3: Add schema and FK pragma to db.py**

In `src/hypothex/db.py`, replace the `_SCHEMA` string with:

```python
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
CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_hypotheses_session ON hypotheses(session_id);
CREATE TABLE IF NOT EXISTS log_hypotheses (
    log_id INTEGER NOT NULL REFERENCES logs(id) ON DELETE CASCADE,
    hypothesis_id TEXT NOT NULL REFERENCES hypotheses(id) ON DELETE CASCADE,
    PRIMARY KEY (log_id, hypothesis_id)
);
CREATE INDEX IF NOT EXISTS idx_log_hyp_hypothesis ON log_hypotheses(hypothesis_id);
"""
```

In the `connect()` method, add FK pragma on both connections after the existing WAL pragma line:

```python
    async def connect(self) -> None:
        if self._db_path == ":memory:":
            connect_path = "file::memory:?cache=shared"
            kwargs: dict = {"uri": True}
        else:
            connect_path = self._db_path
            kwargs = {}
        self._write_conn = await aiosqlite.connect(connect_path, **kwargs)
        self._read_conn = await aiosqlite.connect(connect_path, **kwargs)
        await self._write_conn.execute("PRAGMA journal_mode=WAL")
        await self._write_conn.execute("PRAGMA foreign_keys=ON")
        await self._read_conn.execute("PRAGMA foreign_keys=ON")
        self._read_conn.row_factory = aiosqlite.Row
        for statement in _SCHEMA.strip().split(";"):
            stmt = statement.strip()
            if stmt:
                await self._write_conn.execute(stmt)
        await self._write_conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: ALL PASS (including existing tests)

- [ ] **Step 5: Add hypothesis_ids to LogEntry model**

In `src/hypothex/models.py`, add the field to LogEntry:

```python
class LogEntry(BaseModel):
    session_id: str
    timestamp: str = ""
    level: Literal["debug", "info", "warn", "error"]
    message: str
    data: dict[str, Any] | None = None
    file: str | None = None
    function: str | None = None
    line: int | None = None
    hypothesis_ids: list[str] | None = None
```

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/models.py src/hypothex/db.py tests/test_db.py
git commit -m "feat: add hypotheses schema, FK pragma, and hypothesis_ids field"
```

---

### Task 2: Hypothesis CRUD in Database

**Files:**
- Modify: `src/hypothex/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for create_hypothesis**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_create_hypothesis(db: Database):
    h = await db.create_hypothesis("s1", "Cache is stale after update")
    assert h["id"] == "s1:h1"
    assert h["session_id"] == "s1"
    assert h["description"] == "Cache is stale after update"
    assert h["status"] == "pending"
    assert "created_at" in h


@pytest.mark.asyncio
async def test_create_hypothesis_auto_increments(db: Database):
    h1 = await db.create_hypothesis("s1", "First hypothesis")
    h2 = await db.create_hypothesis("s1", "Second hypothesis")
    assert h1["id"] == "s1:h1"
    assert h2["id"] == "s1:h2"


@pytest.mark.asyncio
async def test_create_hypothesis_scoped_to_session(db: Database):
    h1 = await db.create_hypothesis("s1", "Hypothesis for s1")
    h2 = await db.create_hypothesis("s2", "Hypothesis for s2")
    assert h1["id"] == "s1:h1"
    assert h2["id"] == "s2:h1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py::test_create_hypothesis tests/test_db.py::test_create_hypothesis_auto_increments tests/test_db.py::test_create_hypothesis_scoped_to_session -v`
Expected: FAIL — method doesn't exist

- [ ] **Step 3: Implement create_hypothesis**

Add to `src/hypothex/db.py` in the `Database` class:

```python
    async def create_hypothesis(self, session_id: str, description: str) -> dict:
        if self._write_conn is None:
            raise RuntimeError("Database not connected")
        # Get next hypothesis number for this session using MAX
        async with self._write_conn.execute(
            """\
            SELECT MAX(CAST(SUBSTR(id, INSTR(id, ':h') + 2) AS INTEGER))
            FROM hypotheses WHERE session_id = ?""",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            next_n = (row[0] or 0) + 1
        hyp_id = f"{session_id}:h{next_n}"
        await self._write_conn.execute(
            """\
            INSERT INTO hypotheses (id, session_id, description)
            VALUES (?, ?, ?)""",
            (hyp_id, session_id, description),
        )
        await self._write_conn.commit()
        async with self._write_conn.execute(
            "SELECT * FROM hypotheses WHERE id = ?", (hyp_id,)
        ) as cursor:
            # write_conn doesn't have row_factory, read columns by index
            row = await cursor.fetchone()
            return {
                "id": row[0],
                "session_id": row[1],
                "description": row[2],
                "status": row[3],
                "created_at": row[4],
            }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py::test_create_hypothesis tests/test_db.py::test_create_hypothesis_auto_increments tests/test_db.py::test_create_hypothesis_scoped_to_session -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for list_hypotheses and update_hypothesis**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_list_hypotheses(db: Database):
    await db.create_hypothesis("s1", "First")
    await db.create_hypothesis("s1", "Second")
    await db.create_hypothesis("s2", "Other session")
    result = await db.list_hypotheses("s1")
    assert len(result) == 2
    assert result[0]["id"] == "s1:h1"
    assert result[1]["id"] == "s1:h2"
    assert result[0]["log_count"] == 0


@pytest.mark.asyncio
async def test_list_hypotheses_empty(db: Database):
    result = await db.list_hypotheses("nonexistent")
    assert result == []


@pytest.mark.asyncio
async def test_update_hypothesis(db: Database):
    await db.create_hypothesis("s1", "Test hypothesis")
    h = await db.update_hypothesis("s1:h1", "confirmed")
    assert h["status"] == "confirmed"


@pytest.mark.asyncio
async def test_update_hypothesis_rejected(db: Database):
    await db.create_hypothesis("s1", "Test hypothesis")
    h = await db.update_hypothesis("s1:h1", "rejected")
    assert h["status"] == "rejected"


@pytest.mark.asyncio
async def test_update_hypothesis_invalid_status(db: Database):
    await db.create_hypothesis("s1", "Test hypothesis")
    with pytest.raises(ValueError, match="must be 'confirmed' or 'rejected'"):
        await db.update_hypothesis("s1:h1", "maybe")


@pytest.mark.asyncio
async def test_update_hypothesis_nonexistent(db: Database):
    with pytest.raises(ValueError, match="not found"):
        await db.update_hypothesis("s1:h999", "confirmed")
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_db.py::test_list_hypotheses tests/test_db.py::test_list_hypotheses_empty tests/test_db.py::test_update_hypothesis tests/test_db.py::test_update_hypothesis_rejected -v`
Expected: FAIL

- [ ] **Step 7: Implement list_hypotheses and update_hypothesis**

Add to `src/hypothex/db.py` in the `Database` class:

```python
    async def list_hypotheses(self, session_id: str) -> list[dict]:
        if self._read_conn is None:
            raise RuntimeError("Database not connected")
        async with self._read_conn.execute(
            """\
            SELECT h.id, h.description, h.status, h.created_at,
                   COUNT(lh.log_id) as log_count
            FROM hypotheses h
            LEFT JOIN log_hypotheses lh ON h.id = lh.hypothesis_id
            WHERE h.session_id = ?
            GROUP BY h.id
            ORDER BY h.created_at ASC""",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_hypothesis(self, hypothesis_id: str, status: str) -> dict:
        if self._write_conn is None:
            raise RuntimeError("Database not connected")
        if status not in ("confirmed", "rejected"):
            raise ValueError("status must be 'confirmed' or 'rejected'")
        await self._write_conn.execute(
            "UPDATE hypotheses SET status = ? WHERE id = ?",
            (status, hypothesis_id),
        )
        await self._write_conn.commit()
        # Read back from write_conn (avoids WAL visibility race with read_conn)
        async with self._write_conn.execute(
            "SELECT * FROM hypotheses WHERE id = ?",
            (hypothesis_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Hypothesis '{hypothesis_id}' not found")
            return {
                "id": row[0],
                "session_id": row[1],
                "description": row[2],
                "status": row[3],
                "created_at": row[4],
            }
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add src/hypothex/db.py tests/test_db.py
git commit -m "feat: hypothesis CRUD — create, list, update"
```

---

### Task 3: Log-Hypothesis Linking

**Files:**
- Modify: `src/hypothex/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for insert_log returning ID and linking**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_insert_log_returns_id(db: Database):
    log_id = await db.insert_log(
        session_id="s1", timestamp="t1", level="info", message="test"
    )
    assert isinstance(log_id, int)
    assert log_id > 0


@pytest.mark.asyncio
async def test_link_log_hypotheses(db: Database):
    await db.create_hypothesis("s1", "Hypothesis A")
    await db.create_hypothesis("s1", "Hypothesis B")
    log_id = await db.insert_log(
        session_id="s1", timestamp="t1", level="debug", message="test"
    )
    await db.link_log_hypotheses(log_id, ["s1:h1", "s1:h2"])
    # Verify via raw query
    async with db._read_conn.execute(
        "SELECT hypothesis_id FROM log_hypotheses WHERE log_id = ? ORDER BY hypothesis_id",
        (log_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    assert len(rows) == 2
    assert rows[0]["hypothesis_id"] == "s1:h1"
    assert rows[1]["hypothesis_id"] == "s1:h2"


@pytest.mark.asyncio
async def test_link_log_hypotheses_skips_invalid(db: Database):
    await db.create_hypothesis("s1", "Valid hypothesis")
    log_id = await db.insert_log(
        session_id="s1", timestamp="t1", level="debug", message="test"
    )
    await db.link_log_hypotheses(log_id, ["s1:h1", "s1:h999"])
    async with db._read_conn.execute(
        "SELECT hypothesis_id FROM log_hypotheses WHERE log_id = ?",
        (log_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    # Only the valid one should be linked
    assert len(rows) == 1
    assert rows[0]["hypothesis_id"] == "s1:h1"


@pytest.mark.asyncio
async def test_get_hypothesis_logs(db: Database):
    await db.create_hypothesis("s1", "Test hyp")
    log_id = await db.insert_log(
        session_id="s1", timestamp="t1", level="debug", message="linked log"
    )
    await db.link_log_hypotheses(log_id, ["s1:h1"])
    # Also insert a log NOT linked to the hypothesis
    await db.insert_log(session_id="s1", timestamp="t2", level="info", message="unlinked")
    logs = await db.get_hypothesis_logs("s1:h1")
    assert len(logs) == 1
    assert logs[0]["message"] == "linked log"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py::test_insert_log_returns_id tests/test_db.py::test_link_log_hypotheses tests/test_db.py::test_link_log_hypotheses_skips_invalid tests/test_db.py::test_get_hypothesis_logs -v`
Expected: FAIL

- [ ] **Step 3: Update insert_log to return ID, add link_log_hypotheses and get_hypothesis_logs**

In `src/hypothex/db.py`, update `insert_log` return type and implementation:

```python
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
    ) -> int:
        if self._write_conn is None:
            raise RuntimeError("Database not connected")
        cursor = await self._write_conn.execute(
            """\
            INSERT INTO logs (session_id, timestamp, level, message, data, file, function, line)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, timestamp, level, message, data, file, function, line),
        )
        await self._write_conn.commit()
        return cursor.lastrowid
```

Add new methods:

```python
    async def link_log_hypotheses(self, log_id: int, hypothesis_ids: list[str]) -> None:
        if self._write_conn is None:
            raise RuntimeError("Database not connected")
        for hyp_id in hypothesis_ids:
            try:
                await self._write_conn.execute(
                    """\
                    INSERT INTO log_hypotheses (log_id, hypothesis_id)
                    SELECT ?, ? WHERE EXISTS (SELECT 1 FROM hypotheses WHERE id = ?)""",
                    (log_id, hyp_id, hyp_id),
                )
            except Exception:
                pass  # fire-and-forget: skip invalid IDs
        await self._write_conn.commit()

    async def get_hypothesis_logs(self, hypothesis_id: str) -> list[dict]:
        if self._read_conn is None:
            raise RuntimeError("Database not connected")
        async with self._read_conn.execute(
            """\
            SELECT l.* FROM logs l
            JOIN log_hypotheses lh ON l.id = lh.log_id
            WHERE lh.hypothesis_id = ?
            ORDER BY l.id ASC""",
            (hypothesis_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/db.py tests/test_db.py
git commit -m "feat: log-hypothesis linking with many-to-many join"
```

---

### Task 4: Hypothesis Filtering on Existing Queries

**Files:**
- Modify: `src/hypothex/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for hypothesis_id filter**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_get_logs_filter_by_hypothesis(db: Database):
    await db.create_hypothesis("s1", "Hyp A")
    id1 = await db.insert_log(session_id="s1", timestamp="t1", level="debug", message="linked")
    await db.link_log_hypotheses(id1, ["s1:h1"])
    await db.insert_log(session_id="s1", timestamp="t2", level="info", message="unlinked")
    logs = await db.get_logs("s1", hypothesis_id="s1:h1")
    assert len(logs) == 1
    assert logs[0]["message"] == "linked"


@pytest.mark.asyncio
async def test_tail_logs_filter_by_hypothesis(db: Database):
    await db.create_hypothesis("s1", "Hyp A")
    for i in range(10):
        log_id = await db.insert_log(
            session_id="s1", timestamp=f"t{i}", level="info", message=f"msg-{i}"
        )
        if i >= 5:
            await db.link_log_hypotheses(log_id, ["s1:h1"])
    logs = await db.tail_logs("s1", n=3, hypothesis_id="s1:h1")
    assert len(logs) == 3
    assert logs[0]["message"] == "msg-7"
    assert logs[2]["message"] == "msg-9"


@pytest.mark.asyncio
async def test_search_logs_filter_by_hypothesis(db: Database):
    await db.create_hypothesis("s1", "Hyp A")
    id1 = await db.insert_log(
        session_id="s1", timestamp="t1", level="debug", message="hello world"
    )
    await db.link_log_hypotheses(id1, ["s1:h1"])
    await db.insert_log(
        session_id="s1", timestamp="t2", level="info", message="hello again"
    )
    logs = await db.search_logs("s1", "hello", hypothesis_id="s1:h1")
    assert len(logs) == 1
    assert logs[0]["message"] == "hello world"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py::test_get_logs_filter_by_hypothesis tests/test_db.py::test_tail_logs_filter_by_hypothesis tests/test_db.py::test_search_logs_filter_by_hypothesis -v`
Expected: FAIL — unexpected keyword argument

- [ ] **Step 3: Add hypothesis_id filter to get_logs, tail_logs, search_logs**

Update `get_logs` in `src/hypothex/db.py`:

```python
    async def get_logs(
        self,
        session_id: str,
        *,
        limit: int = 50,
        level: str | None = None,
        since: str | None = None,
        hypothesis_id: str | None = None,
    ) -> list[dict]:
        if self._read_conn is None:
            raise RuntimeError("Database not connected")
        if hypothesis_id:
            query = """\
                SELECT l.* FROM logs l
                JOIN log_hypotheses lh ON l.id = lh.log_id
                WHERE l.session_id = ? AND lh.hypothesis_id = ?"""
            params: list = [session_id, hypothesis_id]
        else:
            query = "SELECT * FROM logs WHERE session_id = ?"
            params = [session_id]
        if level:
            query += " AND l.level = ?" if hypothesis_id else " AND level = ?"
            params.append(level)
        if since:
            query += " AND l.created_at > ?" if hypothesis_id else " AND created_at > ?"
            params.append(since)
        query += " ORDER BY l.id ASC LIMIT ?" if hypothesis_id else " ORDER BY id ASC LIMIT ?"
        params.append(limit)
        async with self._read_conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
```

Update `tail_logs`:

```python
    async def tail_logs(
        self, session_id: str, *, n: int = 20, hypothesis_id: str | None = None
    ) -> list[dict]:
        if self._read_conn is None:
            raise RuntimeError("Database not connected")
        if hypothesis_id:
            query = """\
                SELECT * FROM (
                    SELECT l.* FROM logs l
                    JOIN log_hypotheses lh ON l.id = lh.log_id
                    WHERE l.session_id = ? AND lh.hypothesis_id = ?
                    ORDER BY l.id DESC
                    LIMIT ?
                ) sub ORDER BY id ASC"""
            params = (session_id, hypothesis_id, n)
        else:
            query = """\
                SELECT * FROM (
                    SELECT * FROM logs
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) sub ORDER BY id ASC"""
            params = (session_id, n)
        async with self._read_conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
```

Update `search_logs`:

```python
    async def search_logs(
        self,
        session_id: str,
        query: str,
        *,
        limit: int = 100,
        hypothesis_id: str | None = None,
    ) -> list[dict]:
        if self._read_conn is None:
            raise RuntimeError("Database not connected")
        pattern = f"%{query}%"
        if hypothesis_id:
            sql = """\
                SELECT l.* FROM logs l
                JOIN log_hypotheses lh ON l.id = lh.log_id
                WHERE l.session_id = ?
                  AND lh.hypothesis_id = ?
                  AND (l.message LIKE ? OR l.data LIKE ?)
                ORDER BY l.id ASC
                LIMIT ?"""
            params = (session_id, hypothesis_id, pattern, pattern, limit)
        else:
            sql = """\
                SELECT * FROM logs
                WHERE session_id = ?
                  AND (message LIKE ? OR data LIKE ?)
                ORDER BY id ASC
                LIMIT ?"""
            params = (session_id, pattern, pattern, limit)
        async with self._read_conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/db.py tests/test_db.py
git commit -m "feat: hypothesis_id filter on get_logs, tail_logs, search_logs"
```

---

### Task 5: Updated clear_session

**Files:**
- Modify: `src/hypothex/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing test for clear_session with hypotheses**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_clear_session_deletes_hypotheses_and_links(db: Database):
    await db.create_hypothesis("s1", "Hyp A")
    log_id = await db.insert_log(
        session_id="s1", timestamp="t1", level="debug", message="linked"
    )
    await db.link_log_hypotheses(log_id, ["s1:h1"])
    # Also add data for s2 to ensure it's not affected
    await db.create_hypothesis("s2", "Hyp B")
    count = await db.clear_session("s1")
    assert count == 1
    # Hypotheses for s1 should be gone
    hyps = await db.list_hypotheses("s1")
    assert hyps == []
    # log_hypotheses should be empty for s1 (cascade)
    async with db._read_conn.execute(
        "SELECT * FROM log_hypotheses WHERE hypothesis_id = 's1:h1'"
    ) as cursor:
        rows = await cursor.fetchall()
    assert len(rows) == 0
    # s2 data untouched
    hyps_s2 = await db.list_hypotheses("s2")
    assert len(hyps_s2) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_clear_session_deletes_hypotheses_and_links -v`
Expected: FAIL — hypotheses still exist after clear_session

- [ ] **Step 3: Update clear_session to delete hypotheses**

In `src/hypothex/db.py`, replace `clear_session`:

```python
    async def clear_session(self, session_id: str) -> int:
        if self._write_conn is None:
            raise RuntimeError("Database not connected")
        cursor = await self._write_conn.execute(
            "DELETE FROM logs WHERE session_id = ?",
            (session_id,),
        )
        count = cursor.rowcount
        await self._write_conn.execute(
            "DELETE FROM hypotheses WHERE session_id = ?",
            (session_id,),
        )
        await self._write_conn.commit()
        return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/db.py tests/test_db.py
git commit -m "feat: clear_session also deletes hypotheses and cascades links"
```

---

## Chunk 2: Collector + MCP Tools

### Task 6: Collector Handles hypothesis_ids

**Files:**
- Modify: `src/hypothex/collector.py`
- Modify: `tests/test_collector.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_collector.py`:

```python
@pytest.mark.asyncio
async def test_post_log_with_hypothesis_ids(db: Database):
    # Pre-create hypothesis
    await db.create_hypothesis("s1", "Test hypothesis")
    app = create_app(db)
    client = TestClient(app)
    resp = client.post(
        "/log",
        json={
            "session_id": "s1",
            "level": "debug",
            "message": "linked log",
            "hypothesis_ids": ["s1:h1"],
        },
    )
    assert resp.status_code == 201
    logs = await db.get_hypothesis_logs("s1:h1")
    assert len(logs) == 1
    assert logs[0]["message"] == "linked log"


@pytest.mark.asyncio
async def test_post_log_with_invalid_hypothesis_ids(db: Database):
    app = create_app(db)
    client = TestClient(app)
    resp = client.post(
        "/log",
        json={
            "session_id": "s1",
            "level": "debug",
            "message": "test",
            "hypothesis_ids": ["s1:h999"],
        },
    )
    # Should still succeed (fire-and-forget), just skip linking
    assert resp.status_code == 201
    logs = await db.get_logs("s1")
    assert len(logs) == 1


def test_post_log_without_hypothesis_ids(client: TestClient):
    resp = client.post(
        "/log",
        json={
            "session_id": "s1",
            "level": "info",
            "message": "no hypothesis",
        },
    )
    assert resp.status_code == 201
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_collector.py::test_post_log_with_hypothesis_ids tests/test_collector.py::test_post_log_with_invalid_hypothesis_ids -v`
Expected: FAIL

- [ ] **Step 3: Update collector to handle hypothesis_ids**

In `src/hypothex/collector.py`, update the `post_log` handler:

```python
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
                content={"detail": exc.errors(include_input=False)},
                status_code=422,
            )
        try:
            log_id = await db.insert_log(
                session_id=entry.session_id,
                timestamp=entry.timestamp,
                level=entry.level,
                message=entry.message,
                data=entry.data_json(),
                file=entry.file,
                function=entry.function,
                line=entry.line,
            )
            if entry.hypothesis_ids:
                await db.link_log_hypotheses(log_id, entry.hypothesis_ids)
        except Exception as exc:
            print(f"[hypothex] DB write error: {exc}", file=sys.stderr)
            return JSONResponse(
                content={"detail": "Internal server error"},
                status_code=500,
            )
        return JSONResponse(content={"status": "ok"}, status_code=201)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_collector.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/collector.py tests/test_collector.py
git commit -m "feat: collector links logs to hypotheses on POST /log"
```

---

### Task 7: New MCP Tools

**Files:**
- Modify: `src/hypothex/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing tests for new tools**

Add to `tests/test_mcp_server.py`:

```python
@pytest.mark.asyncio
async def test_create_hypothesis_tool(db: Database, mcp):
    result = await mcp.call_tool(
        "create_hypothesis", {"session_id": "s1", "description": "Cache is stale"}
    )
    assert not result.isError
    import json
    data = json.loads(result.content[0].text)
    assert data["id"] == "s1:h1"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_list_hypotheses_tool(db: Database, mcp):
    await db.create_hypothesis("s1", "First")
    await db.create_hypothesis("s1", "Second")
    result = await mcp.call_tool("list_hypotheses", {"session_id": "s1"})
    assert not result.isError
    import json
    data = json.loads(result.content[0].text)
    assert len(data) == 2


@pytest.mark.asyncio
async def test_update_hypothesis_tool(db: Database, mcp):
    await db.create_hypothesis("s1", "Test")
    result = await mcp.call_tool(
        "update_hypothesis", {"hypothesis_id": "s1:h1", "status": "confirmed"}
    )
    assert not result.isError
    import json
    data = json.loads(result.content[0].text)
    assert data["status"] == "confirmed"


@pytest.mark.asyncio
async def test_get_hypothesis_logs_tool(db: Database, mcp):
    await db.create_hypothesis("s1", "Test")
    log_id = await db.insert_log(
        session_id="s1", timestamp="t1", level="debug", message="linked"
    )
    await db.link_log_hypotheses(log_id, ["s1:h1"])
    await db.insert_log(session_id="s1", timestamp="t2", level="info", message="unlinked")
    result = await mcp.call_tool("get_hypothesis_logs", {"hypothesis_id": "s1:h1"})
    assert not result.isError
    import json
    data = json.loads(result.content[0].text)
    assert len(data) == 1
    assert data[0]["message"] == "linked"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py::test_create_hypothesis_tool tests/test_mcp_server.py::test_list_hypotheses_tool tests/test_mcp_server.py::test_update_hypothesis_tool tests/test_mcp_server.py::test_get_hypothesis_logs_tool -v`
Expected: FAIL — tools don't exist

- [ ] **Step 3: Implement new MCP tools**

Add to `src/hypothex/mcp_server.py` in `create_mcp_server`, before the `return mcp`:

```python
    @mcp.tool(description="Create a new debugging hypothesis for a session")
    async def create_hypothesis(
        session_id: Annotated[str, "Session ID to create hypothesis for"],
        description: Annotated[str, "What you think the bug's root cause is"],
    ) -> str:
        hypothesis = await db.create_hypothesis(session_id, description)
        return json.dumps(hypothesis, indent=2)

    @mcp.tool(description="List all hypotheses for a debugging session with their status and log counts")
    async def list_hypotheses(
        session_id: Annotated[str, "Session ID to list hypotheses for"],
    ) -> str:
        hypotheses = await db.list_hypotheses(session_id)
        return json.dumps(hypotheses, indent=2)

    @mcp.tool(description="Update a hypothesis status to confirmed or rejected")
    async def update_hypothesis(
        hypothesis_id: Annotated[str, "Hypothesis ID (e.g. 'session:h1')"],
        status: Annotated[str, "New status: 'confirmed' or 'rejected'"],
    ) -> str:
        hypothesis = await db.update_hypothesis(hypothesis_id, status)
        return json.dumps(hypothesis, indent=2)

    @mcp.tool(description="Get all logs linked to a specific hypothesis")
    async def get_hypothesis_logs(
        hypothesis_id: Annotated[str, "Hypothesis ID (e.g. 'session:h1')"],
    ) -> str:
        logs = await db.get_hypothesis_logs(hypothesis_id)
        return json.dumps(logs, indent=2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/hypothex/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: MCP tools — create, list, update hypothesis + get hypothesis logs"
```

---

### Task 8: hypothesis_id Filter on Existing MCP Tools

**Files:**
- Modify: `src/hypothex/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write failing tests for hypothesis_id filter on existing tools**

Add to `tests/test_mcp_server.py`:

```python
async def _setup_hypothesis_logs(db: Database):
    """Helper: creates a hypothesis and links some logs to it."""
    await db.create_hypothesis("s1", "Test hypothesis")
    id1 = await db.insert_log(session_id="s1", timestamp="t1", level="debug", message="linked")
    await db.link_log_hypotheses(id1, ["s1:h1"])
    await db.insert_log(session_id="s1", timestamp="t2", level="info", message="unlinked")


@pytest.mark.asyncio
async def test_get_logs_with_hypothesis_filter(db: Database, mcp):
    await _setup_hypothesis_logs(db)
    result = await mcp.call_tool(
        "get_logs", {"session_id": "s1", "hypothesis_id": "s1:h1"}
    )
    import json
    data = json.loads(result.content[0].text)
    assert len(data) == 1
    assert data[0]["message"] == "linked"


@pytest.mark.asyncio
async def test_tail_logs_with_hypothesis_filter(db: Database, mcp):
    await db.create_hypothesis("s1", "Test")
    for i in range(10):
        log_id = await db.insert_log(
            session_id="s1", timestamp=f"t{i}", level="info", message=f"msg-{i}"
        )
        if i >= 5:
            await db.link_log_hypotheses(log_id, ["s1:h1"])
    result = await mcp.call_tool(
        "tail_logs", {"session_id": "s1", "n": 3, "hypothesis_id": "s1:h1"}
    )
    import json
    data = json.loads(result.content[0].text)
    assert len(data) == 3
    assert data[0]["message"] == "msg-7"


@pytest.mark.asyncio
async def test_search_logs_with_hypothesis_filter(db: Database, mcp):
    await _setup_hypothesis_logs(db)
    result = await mcp.call_tool(
        "search_logs", {"session_id": "s1", "query": "linked", "hypothesis_id": "s1:h1"}
    )
    import json
    data = json.loads(result.content[0].text)
    assert len(data) == 1
    assert data[0]["message"] == "linked"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py::test_get_logs_with_hypothesis_filter tests/test_mcp_server.py::test_tail_logs_with_hypothesis_filter tests/test_mcp_server.py::test_search_logs_with_hypothesis_filter -v`
Expected: FAIL — unexpected keyword argument

- [ ] **Step 3: Add hypothesis_id parameter to existing MCP tools**

In `src/hypothex/mcp_server.py`, update the three existing tools:

```python
    @mcp.tool(description="Get logs for a session, optionally filtered by level, time, or hypothesis")
    async def get_logs(
        session_id: Annotated[str, "Session ID to query"],
        limit: Annotated[int, "Max number of logs to return"] = 50,
        level: Annotated[str | None, "Filter by log level (debug/info/warn/error)"] = None,
        since: Annotated[str | None, "ISO8601 timestamp — return logs received after this time"] = None,
        hypothesis_id: Annotated[str | None, "Filter to logs linked to this hypothesis"] = None,
    ) -> str:
        logs = await db.get_logs(
            session_id, limit=limit, level=level, since=since, hypothesis_id=hypothesis_id
        )
        return json.dumps(logs, indent=2)

    @mcp.tool(description="Get the most recent N logs for a session, optionally filtered by hypothesis")
    async def tail_logs(
        session_id: Annotated[str, "Session ID to query"],
        n: Annotated[int, "Number of recent logs to return"] = 20,
        hypothesis_id: Annotated[str | None, "Filter to logs linked to this hypothesis"] = None,
    ) -> str:
        logs = await db.tail_logs(session_id, n=n, hypothesis_id=hypothesis_id)
        return json.dumps(logs, indent=2)

    @mcp.tool(description="Search logs by text query across message and data fields, optionally filtered by hypothesis")
    async def search_logs(
        session_id: Annotated[str, "Session ID to query"],
        query: Annotated[str, "Text to search for in message and data fields"],
        hypothesis_id: Annotated[str | None, "Filter to logs linked to this hypothesis"] = None,
    ) -> str:
        logs = await db.search_logs(session_id, query, hypothesis_id=hypothesis_id)
        return json.dumps(logs, indent=2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run all tests**

Run: `pytest -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/hypothex/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add hypothesis_id filter to get_logs, tail_logs, search_logs MCP tools"
```

---

## Chunk 3: Debug Skill

### Task 9: Debug Skill File

**Files:**
- Create: `debug-skill.md`

- [ ] **Step 1: Write debug-skill.md**

Create `debug-skill.md` at project root:

```markdown
# Hypothex: Debug Mode Skill

You have access to the Hypothex debug mode — a structured debugging workflow that uses runtime evidence to find and fix bugs. Follow this workflow exactly.

## When to Use

Use Debug Mode when you need to find a bug's root cause. Do NOT guess at fixes — use runtime evidence.

## Workflow

### Step 1: Understand the Bug

- Read the user's bug description
- Examine relevant code, error messages, stack traces
- Summarize what you know and what's unclear

### Step 2: Generate Hypotheses

Create 2-4 hypotheses about the root cause. For each one, call:

```
create_hypothesis(session_id, description)
```

Example:
```
create_hypothesis("debug-auth-bug", "Session token not refreshed after password change")
create_hypothesis("debug-auth-bug", "Middleware caches old auth state across requests")
```

Rank them by likelihood and explain your reasoning.

### Step 3: Instrument

For each hypothesis (starting with most likely), inject logging at strategic points. Always use:

1. **Comment markers** for cleanup: `# hypothex:start <id>` / `# hypothex:end <id>`
2. **hypothesis_ids** in the log payload to link logs to hypotheses
3. **Fire-and-forget** pattern — never crash the host

#### Python template:

```python
# hypothex:start {session}:h{n}
try:
    import httpx, os
    httpx.post(f"http://localhost:{os.environ.get('HYPOTHEX_PORT', '3282')}/log", json={
        "session_id": os.environ.get("HYPOTHEX_SESSION_ID", "default"),
        "hypothesis_ids": ["{session}:h{n}"],
        "level": "debug",
        "message": "describe what you're observing",
        "data": {"relevant_variable": value},
        "file": __file__,
        "function": "function_name",
        "line": 42
    })
except Exception:
    pass
# hypothex:end {session}:h{n}
```

#### JavaScript template:

```javascript
// hypothex:start {session}:h{n}
try {
    fetch(`http://localhost:${process.env.HYPOTHEX_PORT || '3282'}/log`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: process.env.HYPOTHEX_SESSION_ID || 'default',
            hypothesis_ids: ['{session}:h{n}'],
            level: 'debug',
            message: 'describe what you are observing',
            data: { relevantVariable: value },
            file: __filename,
            function: 'functionName',
            line: 42
        })
    }).catch(() => {});
} catch {}
// hypothex:end {session}:h{n}
```

**Placement guidelines:**
- Log at decision points (if/else branches, switch cases)
- Log variable values at data boundaries (before/after transforms)
- Log function entry/exit for suspected call path issues
- Use `data` field for structured values, not string interpolation

Tell the user what to do to reproduce the bug.

### Step 4: Reproduce & Analyze

After the user reproduces the bug, query the logs:

```
get_hypothesis_logs("{session}:h{n}")
```

Or use filtered queries:
```
get_logs(session_id, hypothesis_id="{session}:h{n}")
tail_logs(session_id, hypothesis_id="{session}:h{n}")
```

Based on the evidence:

- **If confirmed:** `update_hypothesis("{session}:h{n}", "confirmed")`
- **If rejected:** `update_hypothesis("{session}:h{n}", "rejected")` → instrument for next hypothesis

Review all hypotheses: `list_hypotheses(session_id)`

### Step 5: Fix

Once you have a confirmed hypothesis with supporting runtime evidence:

1. Explain the root cause with references to the log data
2. Propose and apply the fix
3. Ask the user to reproduce the bug again to verify

**CRITICAL: Do NOT propose a fix without runtime evidence from Step 4.** If you're tempted to skip ahead, stop and instrument first.

### Step 6: Cleanup

After the user confirms the fix works:

1. **Remove all instrumentation** — search for `hypothex:start` / `hypothex:end` markers and delete those blocks
2. **Clear the session** — `clear_session(session_id)`
3. **Verify clean diff** — the only remaining changes should be the actual fix

## Available MCP Tools

### Hypothesis Management
- `create_hypothesis(session_id, description)` — create a new hypothesis
- `list_hypotheses(session_id)` — list all hypotheses with status and log counts
- `update_hypothesis(hypothesis_id, status)` — set to "confirmed" or "rejected"

### Log Queries
- `get_logs(session_id, limit?, level?, since?, hypothesis_id?)` — fetch logs
- `tail_logs(session_id, n?, hypothesis_id?)` — most recent N logs
- `search_logs(session_id, query, hypothesis_id?)` — text search
- `get_hypothesis_logs(hypothesis_id)` — all logs for a hypothesis

### Session Management
- `list_sessions(limit?)` — see active sessions
- `clear_session(session_id)` — delete all session data

## Key Principles

1. **Evidence before fixes** — never skip instrumentation
2. **One hypothesis at a time** — don't instrument everything at once
3. **Always clean up** — no instrumentation in the final diff
4. **Fire-and-forget** — instrumentation must never crash the host
5. **Link logs to hypotheses** — always include hypothesis_ids for traceability
```

- [ ] **Step 2: Commit**

```bash
git add debug-skill.md
git commit -m "feat: add debug-skill.md with structured debug loop workflow"
```

---

### Task 10: Update skill.md References

**Files:**
- Modify: `skill.md`

- [ ] **Step 1: Add pointer to debug-skill.md in skill.md**

Add at the end of `skill.md`:

```markdown

## Debug Mode

For structured hypothesis-driven debugging, see [debug-skill.md](debug-skill.md). Debug Mode adds:

- **Hypothesis tracking** — create and manage hypotheses about bug root causes
- **Log-hypothesis linking** — correlate runtime logs with the hypothesis they test
- **Structured workflow** — observe → hypothesize → instrument → reproduce → analyze → fix → cleanup
```

- [ ] **Step 2: Commit**

```bash
git add skill.md
git commit -m "docs: add debug mode reference to skill.md"
```

- [ ] **Step 3: Run full test suite one final time**

Run: `pytest -v`
Expected: ALL PASS
