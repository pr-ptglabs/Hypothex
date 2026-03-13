from __future__ import annotations

import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from hypothex.db import Database
from hypothex.models import LogEntry

MAX_PAYLOAD_BYTES = 1024 * 1024  # 1MB


def create_app(db: Database) -> FastAPI:
    app = FastAPI(title="Hypothex Collector")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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
            await db.insert_log(
                session_id=entry.session_id,
                timestamp=entry.timestamp,
                level=entry.level,
                message=entry.message,
                data=entry.data_json(),
                file=entry.file,
                function=entry.function,
                line=entry.line,
            )
        except Exception as exc:
            print(f"[hypothex] DB write error: {exc}", file=sys.stderr)
            return JSONResponse(
                content={"detail": "Internal server error"},
                status_code=500,
            )
        return JSONResponse(content={"status": "ok"}, status_code=201)

    return app
