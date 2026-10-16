import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.deps import OrgContext, client_ip, csrf_protect, org_context, require_role, require_superadmin
from app.models import Membership, Organization, User
from app.schemas import MemberCreate, MemberOut, MemberUpdate, OrgCreate, OrgOut
from app.security import hash_password

router = APIRouter(tags=["organizations"], dependencies=[Depends(csrf_protect)])


# ---------------------------------------------------------------- superadmin: tenants


@router.get("/admin/orgs", response_model=list[OrgOut])
def list_orgs(_: User = Depends(require_superadmin), db: Session = Depends(get_db)):
    return db.scalars(select(Organization).order_by(Organization.created_at)).all()


@router.post("/admin/orgs", response_model=OrgOut, status_code=201)
def create_org(
    body: OrgCreate, request: Request, admin: User = Depends(require_superadmin), db: Session = Depends(get_db)
):
    if db.scalar(select(Organization).where(Organization.slug == body.slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Организация с таким slug уже есть")
    org = Organization(name=body.name, slug=body.slug)
    db.add(org)
    db.flush()
    owner = db.scalar(select(User).where(func.lower(User.email) == body.owner_email.lower()))
    if owner is None:
        if not body.owner_password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Для нового владельца нужен пароль")
        owner = User(
            email=body.owner_email.lower(),
            full_name=body.owner_name,
            password_hash=hash_password(body.owner_password),
        )
        db.add(owner)
        db.flush()
    db.add(Membership(user_id=owner.id, organization_id=org.id, role="owner"))
    audit(db, "org.created", org_id=org.id, user_id=admin.id, entity="organization", entity_id=org.id,
          data={"slug": org.slug, "owner": owner.email}, ip=client_ip(request))
    db.commit()
    return org


@router.patch("/admin/orgs/{org_id}", response_model=OrgOut)
def set_org_active(
    org_id: uuid.UUID, is_active: bool, request: Request,
    admin: User = Depends(require_superadmin), db: Session = Depends(get_db),
):
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    org.is_active = is_active
    audit(db, "org.activated" if is_active else "org.deactivated", org_id=org.id, user_id=admin.id,
          entity="organization", entity_id=org.id, ip=client_ip(request))
    db.commit()
    return org


# ---------------------------------------------------------------- members of the current org


def _member_out(m: Membership) -> MemberOut:
    return MemberOut(user_id=m.user_id, email=m.user.email, full_name=m.user.full_name,
                     role=m.role, is_active=m.user.is_active)


@router.get("/members", response_model=list[MemberOut])
def list_members(ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db)):
    rows = db.scalars(select(Membership).where(Membership.organization_id == ctx.org.id)).all()
    return [_member_out(m) for m in rows]


@router.post("/members", response_model=MemberOut, status_code=201)
def add_member(
    body: MemberCreate, request: Request,
    ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    if body.role == "owner" and not ctx.can("owner"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только владелец может назначать владельцев")
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None:
        user = User(email=body.email.lower(), full_name=body.full_name, password_hash=hash_password(body.password))
        db.add(user)
        db.flush()
    elif db.scalar(select(Membership).where(Membership.user_id == user.id,
                                            Membership.organization_id == ctx.org.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь уже в организации")
    m = Membership(user_id=user.id, organization_id=ctx.org.id, role=body.role)
    db.add(m)
    audit(db, "member.added", org_id=ctx.org.id, user_id=ctx.user.id, entity="user", entity_id=user.id,
          data={"email": user.email, "role": body.role}, ip=client_ip(request))
    db.commit()
    db.refresh(m)
    return _member_out(m)


def _get_membership(db: Session, ctx: OrgContext, user_id: uuid.UUID) -> Membership:
    m = db.scalar(select(Membership).where(Membership.user_id == user_id,
                                          Membership.organization_id == ctx.org.id))
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return m


def _owners_count(db: Session, org_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(Membership)
                     .where(Membership.organization_id == org_id, Membership.role == "owner")) or 0


@router.patch("/members/{user_id}", response_model=MemberOut)
def update_member(
    user_id: uuid.UUID, body: MemberUpdate, request: Request,
    ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    m = _get_membership(db, ctx, user_id)
    if body.role is not None and body.role != m.role:
        if "owner" in (body.role, m.role) and not ctx.can("owner"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Только владелец меняет роль владельца")
        if m.role == "owner" and _owners_count(db, ctx.org.id) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя понизить последнего владельца")
        m.role = body.role
    if body.is_active is not None:
        if m.user_id == ctx.user.id and not body.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя отключить себя")
        m.user.is_active = body.is_active
    audit(db, "member.updated", org_id=ctx.org.id, user_id=ctx.user.id, entity="user", entity_id=user_id,
          data=body.model_dump(exclude_none=True), ip=client_ip(request))
    db.commit()
    return _member_out(m)


@router.delete("/members/{user_id}", status_code=204)
def remove_member(
    user_id: uuid.UUID, request: Request,
    ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    m = _get_membership(db, ctx, user_id)
    if m.role == "owner" and (not ctx.can("owner") or _owners_count(db, ctx.org.id) <= 1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя удалить последнего владельца")
    db.delete(m)
    audit(db, "member.removed", org_id=ctx.org.id, user_id=ctx.user.id, entity="user", entity_id=user_id,
          ip=client_ip(request))
    db.commit()
