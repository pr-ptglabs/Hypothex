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
