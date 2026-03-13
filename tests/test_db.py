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
