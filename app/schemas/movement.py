from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.movement import MovementType


class MovementIn(BaseModel):
    item_id: int
    type: MovementType
    quantity_delta: int
    notes: str | None = None


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: int
    type: MovementType
    quantity_delta: int
    user_id: int | None
    notes: str | None
    created_at: datetime
