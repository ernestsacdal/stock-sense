from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db, require_role
from app.models.location import Location
from app.models.user import UserRole
from app.schemas.location import LocationIn, LocationOut, LocationUpdate

router = APIRouter(prefix="/api/locations", tags=["locations"])

_WRITE = Depends(require_role(UserRole.admin, UserRole.manager))


@router.get("", response_model=list[LocationOut], dependencies=[Depends(get_current_user)])
def list_locations(
    db: Session = Depends(get_db),
    limit: int = Query(default=500, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Location]:
    return list(
        db.scalars(
            select(Location).order_by(Location.name).limit(limit).offset(offset)
        )
    )


@router.get(
    "/{location_id}", response_model=LocationOut, dependencies=[Depends(get_current_user)]
)
def get_location(location_id: int, db: Session = Depends(get_db)) -> Location:
    loc = db.get(Location, location_id)
    if loc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "location not found")
    return loc


@router.post(
    "",
    response_model=LocationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
def create_location(payload: LocationIn, db: Session = Depends(get_db)) -> Location:
    loc = Location(**payload.model_dump())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


@router.patch("/{location_id}", response_model=LocationOut, dependencies=[_WRITE])
def update_location(
    location_id: int, payload: LocationUpdate, db: Session = Depends(get_db)
) -> Location:
    loc = db.get(Location, location_id)
    if loc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "location not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(loc, field, value)
    db.commit()
    db.refresh(loc)
    return loc


@router.delete(
    "/{location_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_WRITE]
)
def delete_location(location_id: int, db: Session = Depends(get_db)) -> None:
    loc = db.get(Location, location_id)
    if loc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "location not found")
    db.delete(loc)
    db.commit()
