from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.supplier import SupplierIn, SupplierOut, SupplierUpdate

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


def _get_owned_supplier(db: Session, supplier_id: int, user_id: int) -> Supplier:
    s = db.get(Supplier, supplier_id)
    if s is None or s.owner_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "supplier not found")
    return s


@router.get("", response_model=list[SupplierOut])
def list_suppliers(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Supplier]:
    return list(
        db.scalars(
            select(Supplier)
            .where(Supplier.owner_id == user.id)
            .order_by(Supplier.name)
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/{supplier_id}", response_model=SupplierOut)
def get_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Supplier:
    return _get_owned_supplier(db, supplier_id, user.id)


@router.post(
    "",
    response_model=SupplierOut,
    status_code=status.HTTP_201_CREATED,
)
def create_supplier(
    payload: SupplierIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Supplier:
    s = Supplier(owner_id=user.id, **payload.model_dump())
    db.add(s)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "supplier name already exists") from exc
    db.refresh(s)
    return s


@router.patch("/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Supplier:
    s = _get_owned_supplier(db, supplier_id, user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "supplier name already exists") from exc
    db.refresh(s)
    return s


@router.delete("/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    s = _get_owned_supplier(db, supplier_id, user.id)
    db.delete(s)
    db.commit()
