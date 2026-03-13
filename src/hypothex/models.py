from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class LogEntry(BaseModel):
    session_id: str
    timestamp: str = ""
    level: Literal["debug", "info", "warn", "error"]
    message: str
    data: dict[str, Any] | None = None
    file: str | None = None
    function: str | None = None
    line: int | None = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def default_timestamp(cls, v: str) -> str:
        if not v:
            return datetime.now(timezone.utc).isoformat()
        return v

    def data_json(self) -> str | None:
        if self.data is None:
            return None
        return json.dumps(self.data)
