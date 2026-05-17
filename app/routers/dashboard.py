from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.item import Item
from app.models.movement import StockMovement
from app.models.user import User
from app.schemas.dashboard import (
    ActivityItem,
    DashboardSummary,
    ValueHistoryPoint,
)

router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)


def _today() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(db: Session = Depends(get_db)) -> DashboardSummary:
    # Total value = sum of quantity * unit_cost across active items.
    total_value_row = db.execute(
        select(func.coalesce(func.sum(Item.quantity * Item.unit_cost), 0))
        .where(Item.archived_at.is_(None))
    ).scalar_one()
    total_value = Decimal(total_value_row)

    active_skus = db.scalar(
        select(func.count(Item.id)).where(Item.archived_at.is_(None))
    ) or 0

    today = _today().date()
    cutoff = today + timedelta(days=30)
    expiring_rows = db.execute(
        select(Item.id, Item.quantity, Item.unit_cost)
        .where(Item.archived_at.is_(None))
        .where(Item.expiry_date.is_not(None))
        .where(Item.expiry_date.between(today, cutoff))
    ).all()
    expiring_30d_count = len(expiring_rows)
    expiring_30d_value = sum(
        (Decimal(qty) * (cost or Decimal(0)) for _, qty, cost in expiring_rows),
        Decimal(0),
    )

    on_hand_rows = db.execute(
        select(Item.id, Item.reorder_threshold, Item.quantity)
        .where(Item.archived_at.is_(None))
    ).all()
    low_count = 0
    crit_count = 0
    for _, threshold, on_hand in on_hand_rows:
        if not threshold:
            continue
        if on_hand <= 0:
            crit_count += 1
        elif on_hand <= threshold:
            low_count += 1

    return DashboardSummary(
        total_value=total_value,
        active_skus=active_skus,
        expiring_30d_count=expiring_30d_count,
        expiring_30d_value=expiring_30d_value,
        low_stock_count=low_count + crit_count,
        low_stock_critical=crit_count,
    )


@router.get("/value-history", response_model=list[ValueHistoryPoint])
def value_history(
    db: Session = Depends(get_db),
    days: int = Query(default=30, ge=7, le=365),
) -> list[ValueHistoryPoint]:
    """Walk backward from current total value, undoing each day's net
    quantity delta times the item's current unit_cost (an approximation
    — cost changes over time aren't reconstructed)."""

    cost_by_item = {
        row[0]: row[1] or Decimal(0)
        for row in db.execute(select(Item.id, Item.unit_cost)).all()
    }
    if not cost_by_item:
        return []

    today = _today().date()
    current_value = Decimal(
        db.execute(
            select(func.coalesce(func.sum(Item.quantity * Item.unit_cost), 0))
        ).scalar_one()
    )

    window_start = today - timedelta(days=days - 1)
    rows = db.execute(
        select(
            StockMovement.created_at,
            StockMovement.item_id,
            StockMovement.quantity_delta,
        ).where(
            StockMovement.created_at
            >= datetime.combine(window_start, datetime.min.time(), tzinfo=timezone.utc)
        )
    ).all()

    delta_by_date: dict[str, Decimal] = {}
    for created_at, item_id, qty_delta in rows:
        date_key = created_at.date().isoformat()
        cost = cost_by_item.get(item_id, Decimal(0))
        delta_by_date.setdefault(date_key, Decimal(0))
        delta_by_date[date_key] += Decimal(qty_delta) * cost

    points: list[ValueHistoryPoint] = []
    running = current_value
    for offset in range(days):
        d = today - timedelta(days=offset)
        d_iso = d.isoformat()
        points.append(ValueHistoryPoint(date=d_iso, value=running))
        running -= delta_by_date.get(d_iso, Decimal(0))

    return list(reversed(points))


@router.get("/activity", response_model=list[ActivityItem])
def activity_feed(
    db: Session = Depends(get_db), limit: int = Query(default=20, ge=1, le=100)
) -> list[ActivityItem]:
    rows = db.execute(
        select(
            StockMovement.id,
            StockMovement.type,
            StockMovement.quantity_delta,
            StockMovement.notes,
            StockMovement.created_at,
            Item.id,
            Item.name,
            Item.sku,
            User.email,
        )
        .join(Item, Item.id == StockMovement.item_id)
        .outerjoin(User, User.id == StockMovement.user_id)
        .order_by(StockMovement.created_at.desc())
        .limit(limit)
    ).all()
    return [
        ActivityItem(
            movement_id=row[0],
            type=row[1],
            quantity_delta=row[2],
            notes=row[3],
            created_at=row[4],
            item_id=row[5],
            item_name=row[6],
            item_sku=row[7],
            user_email=row[8],
        )
        for row in rows
    ]
