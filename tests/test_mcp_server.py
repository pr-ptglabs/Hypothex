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
    assert "2" in text
    logs = await db.get_logs("s1")
    assert len(logs) == 0


@pytest.mark.asyncio
async def test_get_logs_empty_session(db: Database, mcp):
    result = await mcp.call_tool("get_logs", {"session_id": "nonexistent"})
    assert not result.isError
    text = result.content[0].text
    assert "[]" in text or "no logs" in text.lower() or text.strip() == "[]"
