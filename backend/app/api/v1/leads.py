import csv
import io
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.deps import OrgContext, client_ip, csrf_protect, org_context, require_role
from app.models import Lead, Membership
from app.schemas import LeadOut, LeadPage, LeadUpdate

router = APIRouter(prefix="/leads", tags=["leads"], dependencies=[Depends(csrf_protect)])

SORTS = {
    "found_desc": Lead.found_at.desc(),
    "score_desc": Lead.score.desc(),
    "posted_desc": Lead.posted_at.desc().nulls_last(),
}


def _filtered(ctx: OrgContext, project_id, status_, feedback, source, q, min_score, found_from, assignee_id):
    stmt = select(Lead).where(Lead.organization_id == ctx.org.id)
    if project_id:
        stmt = stmt.where(Lead.project_id == project_id)
    if status_:
        stmt = stmt.where(Lead.status.in_(status_))
    if feedback is not None:
        stmt = stmt.where(Lead.feedback == feedback)
    if source:
        stmt = stmt.where(Lead.source == source)
    if min_score is not None:
        stmt = stmt.where(Lead.score >= min_score)
    if found_from:
        stmt = stmt.where(Lead.found_at >= found_from)
    if assignee_id:
        stmt = stmt.where(Lead.assignee_id == assignee_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Lead.title).like(like), func.lower(Lead.text).like(like),
                              func.lower(Lead.interest_signal).like(like)))
    return stmt


def _params(
    project_id: uuid.UUID | None = None,
    status_: list[str] | None = Query(None, alias="status"),
    feedback: str | None = None,
    source: str | None = None,
    q: str | None = Query(None, max_length=200),
    min_score: float | None = Query(None, ge=0, le=1),
    found_from: date | None = None,
    assignee_id: uuid.UUID | None = None,
):
    return dict(project_id=project_id, status_=status_, feedback=feedback, source=source, q=q,
                min_score=min_score, found_from=found_from, assignee_id=assignee_id)


@router.get("", response_model=LeadPage)
def list_leads(
    params: dict = Depends(_params),
    sort: str = "found_desc",
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db),
):
    stmt = _filtered(ctx, **params)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(SORTS.get(sort, SORTS["found_desc"])).offset(offset).limit(limit)).all()
    return LeadPage(items=items, total=total)


@router.get("/export.csv")
def export_leads(params: dict = Depends(_params), ctx: OrgContext = Depends(org_context),
                 db: Session = Depends(get_db)):
    rows = db.scalars(_filtered(ctx, **params).order_by(Lead.found_at.desc()).limit(10000)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["found_at", "posted_at", "score", "status", "feedback", "segment", "source", "platform",
                "interest", "reason", "title", "url"])
    for r in rows:
        w.writerow([r.found_at.date(), r.posted_at or "", f"{r.score:.2f}", r.status, r.feedback, r.segment,
                    r.source, r.platform, r.interest_signal, r.reason, r.title, r.url])
    data = "﻿" + buf.getvalue()  # BOM so Excel opens UTF-8 correctly
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="leads.csv"'})


def _get_lead(db: Session, ctx: OrgContext, lead_id: uuid.UUID) -> Lead:
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.organization_id == ctx.org.id))
    if not lead:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    return lead


@router.get("/{lead_id}", response_model=LeadOut)
def read_lead(lead_id: uuid.UUID, ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db)):
    return _get_lead(db, ctx, lead_id)


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: uuid.UUID, body: LeadUpdate, request: Request,
    ctx: OrgContext = Depends(require_role("manager")), db: Session = Depends(get_db),
):
    lead = _get_lead(db, ctx, lead_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("assignee_id"):
        member = db.scalar(select(Membership).where(Membership.organization_id == ctx.org.id,
                                                    Membership.user_id == changes["assignee_id"]))
        if not member:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ответственный не состоит в организации")
    for key, value in changes.items():
        setattr(lead, key, value)
    audit(db, "lead.updated", org_id=ctx.org.id, user_id=ctx.user.id, entity="lead", entity_id=lead.id,
          data={k: str(v) for k, v in changes.items() if k != "notes"}, ip=client_ip(request))
    db.commit()
    return lead
