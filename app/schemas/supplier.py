from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SupplierBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    contact: str | None = None
    notes: str | None = None


class SupplierIn(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    contact: str | None = None
    notes: str | None = None


class SupplierOut(SupplierBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
