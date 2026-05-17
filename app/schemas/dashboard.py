from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.movement import MovementType


class DashboardSummary(BaseModel):
    total_value: Decimal
    active_skus: int
    expiring_30d_count: int
    expiring_30d_value: Decimal
    low_stock_count: int
    low_stock_critical: int


class ValueHistoryPoint(BaseModel):
    date: str  # YYYY-MM-DD
    value: Decimal


class ActivityItem(BaseModel):
    movement_id: int
    type: MovementType
    quantity_delta: int
    item_id: int
    item_name: str
    item_sku: str
    user_email: str | None
    notes: str | None
    created_at: datetime
