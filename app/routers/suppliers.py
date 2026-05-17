from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, require_role
from app.models.supplier import Supplier
from app.models.user import UserRole
from app.schemas.supplier import SupplierIn, SupplierOut, SupplierUpdate

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])

_WRITE = Depends(require_role(UserRole.admin, UserRole.manager))


@router.get("", response_model=list[SupplierOut], dependencies=[Depends(get_current_user)])
def list_suppliers(
    db: Session = Depends(get_db),
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Supplier]:
    return list(
        db.scalars(
            select(Supplier).order_by(Supplier.name).limit(limit).offset(offset)
        )
    )


@router.get(
    "/{supplier_id}", response_model=SupplierOut, dependencies=[Depends(get_current_user)]
)
def get_supplier(supplier_id: int, db: Session = Depends(get_db)) -> Supplier:
    s = db.get(Supplier, supplier_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "supplier not found")
    return s


@router.post(
    "",
    response_model=SupplierOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
def create_supplier(payload: SupplierIn, db: Session = Depends(get_db)) -> Supplier:
    s = Supplier(**payload.model_dump())
    db.add(s)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "supplier name already exists") from exc
    db.refresh(s)
    return s


@router.patch("/{supplier_id}", response_model=SupplierOut, dependencies=[_WRITE])
def update_supplier(
    supplier_id: int, payload: SupplierUpdate, db: Session = Depends(get_db)
) -> Supplier:
    s = db.get(Supplier, supplier_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "supplier not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "supplier name already exists") from exc
    db.refresh(s)
    return s


@router.delete(
    "/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_WRITE]
)
def delete_supplier(supplier_id: int, db: Session = Depends(get_db)) -> None:
    s = db.get(Supplier, supplier_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "supplier not found")
    db.delete(s)
    db.commit()
