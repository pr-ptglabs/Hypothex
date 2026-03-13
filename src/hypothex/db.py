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


class Database:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._write_conn: aiosqlite.Connection | None = None
        self._read_conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        # For :memory: databases, use a shared-cache URI so both connections
        # see the same in-memory database. For file paths, use directly.
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
            row = await cursor.fetchone()
            return {
                "id": row[0],
                "session_id": row[1],
                "description": row[2],
                "status": row[3],
                "created_at": row[4],
            }

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

    async def clear_session(self, session_id: str) -> int:
        if self._write_conn is None:
            raise RuntimeError("Database not connected")
        cursor = await self._write_conn.execute(
            "DELETE FROM logs WHERE session_id = ?",
            (session_id,),
        )
        await self._write_conn.commit()
        return cursor.rowcount
