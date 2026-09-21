from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MemoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str
    timestamp: int | None = None


class AddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=512)
    messages: list[MemoryMessage] = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=512)
    session_id: str = Field(min_length=1, max_length=512)

    def payload_hash(self) -> str:
        payload = {
            "request_id": self.request_id,
            "messages": [message.model_dump() for message in self.messages],
            "user_id": self.user_id,
            "session_id": self.session_id,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class AddResponse(BaseModel):
    success: Literal[True] = True
    request_id: str
    user_id: str
    session_id: str


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=8_000)
    options: list[str] | None = Field(default=None, max_length=100)
    user_id: str = Field(min_length=1, max_length=512)
    top_k: int = Field(ge=1, le=100)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value

    @field_validator("options")
    @classmethod
    def options_must_be_bounded(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if any(len(option) > 2_000 for option in value):
            raise ValueError("each option must be at most 2000 characters")
        return value


class SearchItem(BaseModel):
    id: str
    content: str
    score: float | None = None
    created_at: datetime | None = None


class SearchResponse(BaseModel):
    data: list[SearchItem]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    llm_mode: str
    llm_ready: bool
