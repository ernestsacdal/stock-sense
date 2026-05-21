from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.category import Category
from app.models.user import User
from app.schemas.category import CategoryIn, CategoryOut, CategoryUpdate

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _get_owned_category(db: Session, category_id: int, user_id: int) -> Category:
    cat = db.get(Category, category_id)
    if cat is None or cat.owner_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "category not found")
    return cat


@router.get("", response_model=list[CategoryOut])
def list_categories(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Category]:
    return list(
        db.scalars(
            select(Category)
            .where(Category.owner_id == user.id)
            .order_by(Category.name)
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/{category_id}", response_model=CategoryOut)
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Category:
    return _get_owned_category(db, category_id, user.id)


@router.post(
    "",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_category(
    payload: CategoryIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Category:
    category = Category(
        owner_id=user.id,
        name=payload.name,
        description=payload.description,
    )
    db.add(category)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "category name already exists") from exc
    db.refresh(category)
    return category


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Category:
    category = _get_owned_category(db, category_id, user.id)

    if payload.name is not None:
        category.name = payload.name
    if payload.description is not None:
        category.description = payload.description

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "category name already exists") from exc
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    category = _get_owned_category(db, category_id, user.id)
    try:
        db.delete(category)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "category is in use by items; archive those first",
        ) from exc
