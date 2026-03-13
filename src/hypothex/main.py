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
