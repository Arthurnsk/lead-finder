from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import settings
from app.db import get_db, utcnow
from app.deps import client_ip, csrf_protect, current_user
from app.models import Membership, User
from app.schemas import LoginIn, MembershipOut, MeOut, OrgOut, PasswordChange
from app.security import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    login_limiter,
    new_csrf_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(response: Response, user: User) -> None:
    common = {"secure": settings.cookie_secure, "samesite": "strict"}
    response.set_cookie(
        ACCESS_COOKIE, create_access_token(user.id), httponly=True,
        max_age=settings.access_token_minutes * 60, path="/", **common,
    )
    response.set_cookie(
        REFRESH_COOKIE, create_refresh_token(user.id), httponly=True,
        max_age=settings.refresh_token_days * 86400, path="/api/v1/auth", **common,
    )
    # Readable by JS so the SPA can echo it in X-CSRF-Token
    response.set_cookie(
        CSRF_COOKIE, new_csrf_token(), httponly=False,
        max_age=settings.refresh_token_days * 86400, path="/", **common,
    )


def me_payload(db: Session, user: User) -> MeOut:
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_superadmin=user.is_superadmin,
        memberships=[
            MembershipOut(organization=OrgOut.model_validate(m.organization), role=m.role)
            for m in memberships
            if m.organization.is_active
        ],
    )


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if not login_limiter.allow(f"{ip}:{body.email.lower()}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток, подождите минуту")
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        audit(db, "auth.login_failed", data={"email": body.email.lower()}, ip=ip)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    user.last_login_at = utcnow()
    audit(db, "auth.login", user_id=user.id, ip=ip)
    db.commit()
    _set_session_cookies(response, user)
    return me_payload(db, user)


@router.post("/refresh", response_model=MeOut)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    user_id = decode_token(token, "refresh") if token else None
    user = db.get(User, user_id) if user_id else None
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    _set_session_cookies(response, user)
    return me_payload(db, user)


@router.post("/logout", status_code=204, dependencies=[Depends(csrf_protect)])
def logout(response: Response):
    for name, path in ((ACCESS_COOKIE, "/"), (REFRESH_COOKIE, "/api/v1/auth"), (CSRF_COOKIE, "/")):
        response.delete_cookie(name, path=path)


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return me_payload(db, user)


@router.post("/password", status_code=204, dependencies=[Depends(csrf_protect)])
def change_password(
    body: PasswordChange, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Текущий пароль неверен")
    user.password_hash = hash_password(body.new_password)
    audit(db, "auth.password_changed", user_id=user.id, ip=client_ip(request))
    db.commit()
