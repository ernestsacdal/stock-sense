from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, require_role
from app.models.location import Location
from app.models.user import User, UserRole
from app.schemas.location import LocationIn, LocationOut, LocationUpdate

router = APIRouter(prefix="/api/locations", tags=["locations"])

_WRITE = Depends(require_role(UserRole.admin, UserRole.manager))


def _get_owned_location(db: Session, location_id: int, user_id: int) -> Location:
    loc = db.get(Location, location_id)
    if loc is None or loc.owner_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "location not found")
    return loc


@router.get("", response_model=list[LocationOut])
def list_locations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Location]:
    return list(
        db.scalars(
            select(Location)
            .where(Location.owner_id == user.id)
            .order_by(Location.name)
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/{location_id}", response_model=LocationOut)
def get_location(
    location_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Location:
    return _get_owned_location(db, location_id, user.id)


@router.post(
    "",
    response_model=LocationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
def create_location(
    payload: LocationIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Location:
    loc = Location(owner_id=user.id, **payload.model_dump())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


@router.patch("/{location_id}", response_model=LocationOut, dependencies=[_WRITE])
def update_location(
    location_id: int,
    payload: LocationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Location:
    loc = _get_owned_location(db, location_id, user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(loc, field, value)
    db.commit()
    db.refresh(loc)
    return loc


@router.delete(
    "/{location_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_WRITE]
)
def delete_location(
    location_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    loc = _get_owned_location(db, location_id, user.id)
    db.delete(loc)
    db.commit()
