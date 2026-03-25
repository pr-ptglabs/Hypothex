from __future__ import annotations

import asyncio
import os
import socket
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


def _port_in_use(port: int) -> bool:
    """Check if a port is already bound (another collector is running)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


async def _run() -> None:
    db_path = _get_db_path()
    port = int(os.environ.get("HYPOTHEX_PORT", str(DEFAULT_PORT)))

    db = Database(db_path)
    await db.connect()

    shutdown_event = asyncio.Event()

    # MCP server
    mcp = create_mcp_server(db)

    async def run_mcp() -> None:
        try:
            await mcp.run_stdio_async()
        finally:
            shutdown_event.set()

    collector_running = _port_in_use(port)

    if collector_running:
        # Another session already owns the HTTP collector on this port.
        # Just run the MCP stdio server — logs still reach the shared DB.
        print(
            f"[hypothex] Collector already running on :{port}, "
            "starting MCP server only.",
            file=sys.stderr,
        )
        try:
            await run_mcp()
        except KeyboardInterrupt:
            pass
        finally:
            await db.close()
            print("[hypothex] Shutdown complete.", file=sys.stderr)
        return

    # First session — start both collector and MCP server.
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
