from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.models.user import User, UserRole
from app.schemas.user import UserOut

router = APIRouter(prefix="/api/admin", tags=["admin"])


class RoleUpdateIn(BaseModel):
    role: UserRole


@router.get(
    "/users",
    response_model=list[UserOut],
    dependencies=[Depends(require_role(UserRole.admin))],
)
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))


@router.patch(
    "/users/{user_id}/role",
    response_model=UserOut,
    dependencies=[Depends(require_role(UserRole.admin))],
)
def update_user_role(
    user_id: int, payload: RoleUpdateIn, db: Session = Depends(get_db)
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    user.role = payload.role
    db.commit()
    db.refresh(user)
    return user
