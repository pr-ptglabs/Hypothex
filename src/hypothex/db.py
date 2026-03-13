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
