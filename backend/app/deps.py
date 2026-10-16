"""Request dependencies: current user, tenant scoping, role checks, CSRF."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ROLE_RANK, Membership, Organization, User
from app.security import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, decode_token

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def csrf_protect(request: Request) -> None:
    """Double-submit: unsafe requests must echo the CSRF cookie in a header."""
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or cookie != header:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    user_id = decode_token(token, "access") if token else None
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


@dataclass
class OrgContext:
    user: User
    org: Organization
    role: str

    def can(self, min_role: str) -> bool:
        return self.user.is_superadmin or ROLE_RANK[self.role] >= ROLE_RANK[min_role]


def org_context(
    request: Request,
    x_org_id: str | None = Header(default=None, alias="X-Org-Id"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> OrgContext:
    """Resolve the active organization for this request.

    Every tenant-scoped endpoint depends on this; queries must filter by ctx.org.id.
    EventSource can't send headers, so GET requests may pass ?org=<id> instead.
    """
    if not x_org_id and request.method == "GET":
        x_org_id = request.query_params.get("org")
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    membership = None
    if x_org_id:
        try:
            org_id = uuid.UUID(x_org_id)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid X-Org-Id")
        membership = next((m for m in memberships if m.organization_id == org_id), None)
        if membership is None and user.is_superadmin:
            org = db.get(Organization, org_id)
            if org:
                return OrgContext(user, org, "owner")
        if membership is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this organization")
    elif memberships:
        membership = memberships[0]
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User has no organization")

    org = db.get(Organization, membership.organization_id)
    if not org or not org.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Organization is disabled")
    return OrgContext(user, org, membership.role)


def require_role(min_role: str):
    def dep(ctx: OrgContext = Depends(org_context)) -> OrgContext:
        if not ctx.can(min_role):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role {min_role} or higher")
        return ctx

    return dep


def require_superadmin(user: User = Depends(current_user)) -> User:
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Superadmin only")
    return user


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]
