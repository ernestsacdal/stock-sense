from collections.abc import Callable, Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.security import TokenError, decode_token
from app.models.user import User, UserRole


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    auth = request.headers.get("authorization") or ""
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token, expected_type="access")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = int(payload["sub"])
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user


def require_role(*allowed: UserRole) -> Callable[[User], User]:
    """Factory: returns a dependency that 403s unless current user is in `allowed`."""

    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {user.role.value!r} cannot access this resource",
            )
        return user

    return _dep
