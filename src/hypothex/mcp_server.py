from __future__ import annotations

import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from hypothex.db import Database


class HypothexMCP(FastMCP):
    """FastMCP subclass whose call_tool returns a CallToolResult for easy testing."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:  # type: ignore[override]
        try:
            result = await super().call_tool(name, arguments)
            # FastMCP 1.x returns a tuple (list[ContentBlock], dict) or a list[ContentBlock]
            if isinstance(result, tuple):
                content_blocks = result[0]
            else:
                content_blocks = list(result)
            return CallToolResult(content=content_blocks, isError=False)
        except Exception as exc:
            return CallToolResult(
                content=[TextContent(type="text", text=str(exc))],
                isError=True,
            )


def create_mcp_server(db: Database) -> HypothexMCP:
    mcp = HypothexMCP(name="hypothex")

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
