import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class QueryStatus(str, enum.Enum):
    ok = "ok"
    llm_error = "llm_error"
    safety_rejected = "safety_rejected"
    exec_error = "exec_error"
    timeout = "timeout"


class QueryLog(Base):
    """Append-only audit log for every Ask StockSense turn — successful or
    not. Doubles as the per-user conversation history surfaced in the
    chat UI's recent-sessions sidebar."""

    __tablename__ = "query_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    generated_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Natural-language answer the model produces after running the SQL.
    # Null for safety-rejected / exec-error turns (nothing to summarize).
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[QueryStatus] = mapped_column(
        Enum(QueryStatus, name="query_status"), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
