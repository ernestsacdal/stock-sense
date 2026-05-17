from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.query_log import QueryStatus


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AskResultPayload(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


class AskTurnOut(BaseModel):
    """Non-streaming response shape — also the shape persisted in query_logs."""

    log_id: int
    question: str
    sql: str | None
    answer_text: str | None
    status: QueryStatus
    error_message: str | None
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    duration_ms: int


class QueryLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    generated_sql: str | None
    answer_text: str | None
    status: QueryStatus
    error_message: str | None
    row_count: int | None
    duration_ms: int
    created_at: datetime
