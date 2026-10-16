import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db, utcnow
from app.deps import OrgContext, org_context
from app.models import Lead, Run

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(
    project_id: uuid.UUID | None = None, days: int = Query(30, ge=1, le=365),
    ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db),
):
    since = utcnow() - timedelta(days=days)
    base = [Lead.organization_id == ctx.org.id, Lead.found_at >= since]
    if project_id:
        base.append(Lead.project_id == project_id)

    def grouped(col):
        return {k or "—": v for k, v in db.execute(select(col, func.count()).where(*base).group_by(col)).all()}

    day = func.date(Lead.found_at)  # portable: Postgres returns date, SQLite a string
    per_day = [{"date": d if isinstance(d, str) else d.isoformat(), "count": c}
               for d, c in db.execute(select(day, func.count()).where(*base).group_by(day).order_by(day)).all()]
    feedback = grouped(Lead.feedback)
    rated = feedback.get("good", 0) + feedback.get("bad", 0)

    run_filter = [Run.organization_id == ctx.org.id]
    if project_id:
        run_filter.append(Run.project_id == project_id)
    last_runs = db.scalars(select(Run).where(*run_filter).order_by(Run.created_at.desc()).limit(5)).all()

    return {
        "days": days,
        "total": sum(c["count"] for c in per_day),
        "per_day": per_day,
        "by_status": grouped(Lead.status),
        "by_source": grouped(Lead.source),
        "by_segment": grouped(Lead.segment),
        "feedback": {"good": feedback.get("good", 0), "bad": feedback.get("bad", 0), "unrated": feedback.get("—", 0),
                     "precision": round(feedback.get("good", 0) / rated, 3) if rated else None},
        "last_runs": [{"id": str(r.id), "status": r.status, "created_at": r.created_at.isoformat(),
                       "leads": (r.stats or {}).get("leads", 0), "trigger": r.trigger} for r in last_runs],
    }
