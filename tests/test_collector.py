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
