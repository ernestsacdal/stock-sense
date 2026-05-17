from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ItemBase(BaseModel):
    sku: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=255)
    category_id: int
    supplier_id: int | None = None
    location_id: int | None = None
    reorder_threshold: int | None = None
    quantity: int = Field(default=0, ge=0)
    unit_cost: Decimal | None = None
    expiry_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ItemIn(ItemBase):
    pass


class ItemUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=60)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: int | None = None
    supplier_id: int | None = None
    location_id: int | None = None
    reorder_threshold: int | None = None
    quantity: int | None = Field(default=None, ge=0)
    unit_cost: Decimal | None = None
    expiry_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class RestockIn(BaseModel):
    quantity: int = Field(gt=0)
    unit_cost: Decimal | None = None
    expiry_date: date | None = None
    notes: str | None = None


class IssueIn(BaseModel):
    quantity: int = Field(gt=0)
    notes: str | None = None


class ItemSummaryOut(BaseModel):
    """Compact view used in list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    category_id: int
    supplier_id: int | None
    location_id: int | None
    location_name: str | None = None
    reorder_threshold: int | None
    archived_at: datetime | None
    on_hand: int = 0
    stock_status: str = "ok"  # ok / low / crit
    nearest_expiry: str | None = None  # ISO date or None


class ItemOut(ItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
