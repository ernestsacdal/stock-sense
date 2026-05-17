import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MovementType(str, enum.Enum):
    added = "added"
    received = "received"
    issued = "issued"
    disposed = "disposed"
    adjusted = "adjusted"
    transferred = "transferred"


class StockMovement(Base):
    """Append-only audit log. Never updated, never deleted —
    reversals are recorded as compensating entries with the opposite sign."""

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    type: Mapped[MovementType] = mapped_column(
        Enum(MovementType, name="movement_type"), nullable=False
    )
    # Signed delta: positive for received / transferred-in / positive adjustments,
    # negative for issued / disposed / transferred-out / negative adjustments.
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
