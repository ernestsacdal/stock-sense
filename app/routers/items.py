from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, require_role
from app.models.category import Category
from app.models.item import Item
from app.models.location import Location
from app.models.movement import MovementType, StockMovement
from app.models.user import User, UserRole
from app.schemas.item import (
    IssueIn,
    ItemIn,
    ItemOut,
    ItemSummaryOut,
    ItemUpdate,
    RestockIn,
)

router = APIRouter(prefix="/api/items", tags=["items"])

_WRITE = Depends(require_role(UserRole.admin, UserRole.manager))


def _summarize(item: Item, location_name: str | None = None) -> ItemSummaryOut:
    threshold = item.reorder_threshold or 0
    on_hand = item.quantity
    if threshold and on_hand <= 0:
        status_str = "crit"
    elif threshold and on_hand <= threshold:
        status_str = "low"
    else:
        status_str = "ok"
    return ItemSummaryOut(
        id=item.id,
        sku=item.sku,
        name=item.name,
        category_id=item.category_id,
        supplier_id=item.supplier_id,
        location_id=item.location_id,
        location_name=location_name,
        reorder_threshold=item.reorder_threshold,
        archived_at=item.archived_at,
        on_hand=on_hand,
        stock_status=status_str,
        nearest_expiry=item.expiry_date.isoformat() if item.expiry_date else None,
    )


@router.get("", response_model=list[ItemSummaryOut], dependencies=[Depends(get_current_user)])
def list_items(
    db: Session = Depends(get_db),
    q: str | None = Query(default=None, description="Match against name or sku"),
    category_id: int | None = None,
    supplier_id: int | None = None,
    location_id: int | None = None,
    stock_status: str | None = Query(
        default=None, description="ok / low / crit (post-aggregate filter)"
    ),
    include_archived: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ItemSummaryOut]:
    # Outer-join Location so the list can display location_name without an
    # N+1 — matches the supplier_id filter pattern but adds the joined name
    # for the FE table.
    stmt = (
        select(Item, Location.name)
        .outerjoin(Location, Item.location_id == Location.id)
    )
    if not include_archived:
        stmt = stmt.where(Item.archived_at.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where((Item.name.ilike(like)) | (Item.sku.ilike(like)))
    if category_id is not None:
        stmt = stmt.where(Item.category_id == category_id)
    if supplier_id is not None:
        stmt = stmt.where(Item.supplier_id == supplier_id)
    if location_id is not None:
        stmt = stmt.where(Item.location_id == location_id)
    stmt = stmt.order_by(Item.name).limit(limit).offset(offset)
    rows = db.execute(stmt).all()

    summaries = [_summarize(item, loc_name) for item, loc_name in rows]
    if stock_status:
        summaries = [s for s in summaries if s.stock_status == stock_status]
    return summaries


@router.get("/{item_id}", response_model=ItemOut, dependencies=[Depends(get_current_user)])
def get_item(item_id: int, db: Session = Depends(get_db)) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    return item


@router.post(
    "", response_model=ItemOut, status_code=status.HTTP_201_CREATED, dependencies=[_WRITE]
)
def create_item(
    payload: ItemIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Item:
    if db.get(Category, payload.category_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "category not found")

    item = Item(
        sku=payload.sku,
        name=payload.name,
        category_id=payload.category_id,
        supplier_id=payload.supplier_id,
        location_id=payload.location_id,
        reorder_threshold=payload.reorder_threshold,
        quantity=payload.quantity,
        unit_cost=payload.unit_cost,
        expiry_date=payload.expiry_date,
        notes=payload.notes,
    )
    db.add(item)
    try:
        db.flush()
        # If the item was created with non-zero opening stock, log it as an
        # "added" movement so the audit trail starts from the right place
        # rather than appearing to materialise out of nowhere.
        if payload.quantity and payload.quantity > 0:
            db.add(
                StockMovement(
                    item_id=item.id,
                    type=MovementType.added,
                    quantity_delta=payload.quantity,
                    user_id=user.id,
                    notes=None,
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "sku already exists") from exc
    db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=ItemOut, dependencies=[_WRITE])
def update_item(
    item_id: int, payload: ItemUpdate, db: Session = Depends(get_db)
) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")

    update = payload.model_dump(exclude_unset=True)
    if "category_id" in update and db.get(Category, update["category_id"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "category not found")

    for field, value in update.items():
        setattr(item, field, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "sku already exists") from exc
    db.refresh(item)
    return item


@router.delete("/{item_id}", response_model=ItemOut, dependencies=[_WRITE])
def archive_item(item_id: int, db: Session = Depends(get_db)) -> Item:
    """Soft delete: items are never hard-removed (audit-critical)."""
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    item.archived_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return item


@router.post(
    "/{item_id}/restock",
    response_model=ItemOut,
    dependencies=[_WRITE],
)
def restock(
    item_id: int,
    payload: RestockIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Item:
    """Add stock: increment quantity, optionally overwrite unit_cost and
    expiry_date with the new shipment's values, log a received movement."""
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")

    item.quantity += payload.quantity
    if payload.unit_cost is not None:
        item.unit_cost = payload.unit_cost
    if payload.expiry_date is not None:
        item.expiry_date = payload.expiry_date

    db.add(
        StockMovement(
            item_id=item.id,
            type=MovementType.received,
            quantity_delta=payload.quantity,
            user_id=user.id,
            notes=payload.notes,
        )
    )
    db.commit()
    db.refresh(item)
    return item


@router.post(
    "/{item_id}/issue",
    response_model=ItemOut,
    dependencies=[_WRITE],
)
def issue(
    item_id: int,
    payload: IssueIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Item:
    """Remove stock: decrement quantity (refuses negative), log an issued
    movement."""
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    if item.quantity - payload.quantity < 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"not enough stock: on hand {item.quantity}, tried to issue {payload.quantity}",
        )

    item.quantity -= payload.quantity
    db.add(
        StockMovement(
            item_id=item.id,
            type=MovementType.issued,
            quantity_delta=-payload.quantity,
            user_id=user.id,
            notes=payload.notes,
        )
    )
    db.commit()
    db.refresh(item)
    return item
