from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.deps import get_current_user, get_db
from app.models.user import User, UserRole
from app.schemas.auth import AccessTokenOut, LoginIn, ProfileUpdateIn, RegisterIn
from app.schemas.user import UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


def _set_refresh_cookie(response: Response, token: str) -> None:
    # SameSite policy tracks the Secure flag:
    #  - dev (REFRESH_COOKIE_SECURE=false, http://localhost): use "lax".
    #    Browsers reject SameSite=None cookies without Secure, so Lax is
    #    the only viable option in dev.
    #  - prod (REFRESH_COOKIE_SECURE=true, https): use "none". Required
    #    when the frontend (e.g. *.vercel.app) and backend (e.g.
    #    *.onrender.com) live on different root domains — without it,
    #    the browser drops the refresh cookie on cross-site requests
    #    and the silent-refresh flow silently fails after the access
    #    token's 15-minute TTL.
    samesite: str = "none" if settings.refresh_cookie_secure else "lax"
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=samesite,  # type: ignore[arg-type]
        max_age=settings.jwt_refresh_ttl_days * 24 * 60 * 60,
        path="/api/auth",
        domain=settings.refresh_cookie_domain or None,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path="/api/auth",
        domain=settings.refresh_cookie_domain or None,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, db: Session = Depends(get_db)) -> User:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.staff,
        business_name=payload.business_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=AccessTokenOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)) -> AccessTokenOut:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password"
        )

    _set_refresh_cookie(response, create_refresh_token(user.id))
    return AccessTokenOut(access_token=create_access_token(user.id, user.role.value))


@router.post("/refresh", response_model=AccessTokenOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> AccessTokenOut:
    raw = request.cookies.get(settings.refresh_cookie_name)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing refresh cookie"
        )

    try:
        payload = decode_token(raw, expected_type="refresh")
    except TokenError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    user = db.get(User, int(payload["sub"]))
    if user is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")

    # Rotate the refresh token on every successful refresh.
    _set_refresh_cookie(response, create_refresh_token(user.id))
    return AccessTokenOut(access_token=create_access_token(user.id, user.role.value))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: ProfileUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Update the current user's profile. Email is immutable; password
    rotation requires the current password."""
    update = payload.model_dump(exclude_unset=True)

    if "business_name" in update:
        user.business_name = update["business_name"]

    new_password = update.get("new_password")
    if new_password:
        current_password = update.get("current_password")
        if not current_password:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="current_password is required to set a new password",
            )
        if not verify_password(current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="current password is incorrect",
            )
        user.password_hash = hash_password(new_password)

    db.commit()
    db.refresh(user)
    return user
