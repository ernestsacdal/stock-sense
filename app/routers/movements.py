from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.item import Item
from app.models.movement import MovementType, StockMovement
from app.models.user import User
from app.schemas.movement import MovementIn, MovementOut

router = APIRouter(prefix="/api/movements", tags=["movements"])


@router.get("", response_model=list[MovementOut])
def list_movements(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    item_id: int | None = Query(default=None),
    type: MovementType | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[StockMovement]:
    stmt = (
        select(StockMovement)
        .where(StockMovement.owner_id == user.id)
        .order_by(StockMovement.created_at.desc())
    )
    if item_id is not None:
        stmt = stmt.where(StockMovement.item_id == item_id)
    if type is not None:
        stmt = stmt.where(StockMovement.type == type)
    return list(db.scalars(stmt.limit(limit).offset(offset)))


@router.post("", response_model=MovementOut, status_code=status.HTTP_201_CREATED)
def create_movement(
    payload: MovementIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StockMovement:
    """Append a movement and apply its delta to the item's quantity.
    Movements are append-only — no edit/delete. Reversals are new movements
    with the opposite-sign delta. For everyday +/- use the item's restock
    and issue endpoints; this endpoint is for manual / unusual entries
    (disposed, adjusted, transferred)."""
    # Item must exist AND belong to this user — otherwise you could
    # log movements against someone else's inventory.
    item = db.get(Item, payload.item_id)
    if item is None or item.owner_id != user.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "item not found")

    new_quantity = item.quantity + payload.quantity_delta
    if new_quantity < 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"movement would drive quantity negative ({item.quantity} + {payload.quantity_delta})",
        )

    movement = StockMovement(
        owner_id=user.id,
        item_id=payload.item_id,
        type=payload.type,
        quantity_delta=payload.quantity_delta,
        user_id=user.id,
        notes=payload.notes,
    )
    item.quantity = new_quantity
    db.add(movement)
    db.commit()
    db.refresh(movement)
    return movement
