import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.projects import get_project
from app.audit import audit
from app.db import SessionLocal, get_db, utcnow
from app.deps import OrgContext, client_ip, csrf_protect, org_context, require_role
from app.models import Run, RunEvent
from app.schemas import RunEventOut, RunOut

router = APIRouter(tags=["runs"], dependencies=[Depends(csrf_protect)])

FINAL = {"succeeded", "failed", "cancelled"}


def _get_run(db: Session, ctx: OrgContext, run_id: uuid.UUID) -> Run:
    run = db.scalar(select(Run).where(Run.id == run_id, Run.organization_id == ctx.org.id))
    if not run:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return run


@router.post("/projects/{project_id}/runs", response_model=RunOut, status_code=201)
def start_run(
    project_id: uuid.UUID, request: Request,
    ctx: OrgContext = Depends(require_role("manager")), db: Session = Depends(get_db),
):
    project = get_project(db, ctx, project_id)
    active = db.scalar(select(Run).where(Run.project_id == project.id, Run.status.in_(["queued", "running"])))
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Запуск уже идёт — дождитесь окончания или остановите его")
    run = Run(organization_id=ctx.org.id, project_id=project.id, trigger="manual", created_by_id=ctx.user.id)
    db.add(run)
    audit(db, "run.started", org_id=ctx.org.id, user_id=ctx.user.id, entity="project", entity_id=project.id,
          ip=client_ip(request))
    db.commit()
    return run


@router.get("/runs", response_model=list[RunOut])
def list_runs(
    project_id: uuid.UUID | None = None, limit: int = Query(50, le=200),
    ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db),
):
    stmt = select(Run).where(Run.organization_id == ctx.org.id)
    if project_id:
        stmt = stmt.where(Run.project_id == project_id)
    return db.scalars(stmt.order_by(Run.created_at.desc()).limit(limit)).all()


@router.get("/runs/{run_id}", response_model=RunOut)
def read_run(run_id: uuid.UUID, ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db)):
    return _get_run(db, ctx, run_id)


@router.get("/runs/{run_id}/events", response_model=list[RunEventOut])
def run_events(
    run_id: uuid.UUID, after: int = 0, ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db),
):
    _get_run(db, ctx, run_id)
    return db.scalars(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.id > after)
                      .order_by(RunEvent.id).limit(1000)).all()


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
def cancel_run(
    run_id: uuid.UUID, request: Request,
    ctx: OrgContext = Depends(require_role("manager")), db: Session = Depends(get_db),
):
    run = _get_run(db, ctx, run_id)
    if run.status in FINAL:
        return run
    if run.status == "queued":
        run.finished_at = utcnow()
    run.status = "cancelled"  # a running worker notices this between candidates
    audit(db, "run.cancelled", org_id=ctx.org.id, user_id=ctx.user.id, entity="run", entity_id=run.id,
          ip=client_ip(request))
    db.commit()
    return run


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: uuid.UUID, request: Request, ctx: OrgContext = Depends(org_context),
                     db: Session = Depends(get_db)):
    """Server-Sent Events: new log lines + final status."""
    _get_run(db, ctx, run_id)

    async def gen():
        last_id = int(request.headers.get("last-event-id") or 0)
        while True:
            if await request.is_disconnected():
                return
            with SessionLocal() as s:
                events = s.scalars(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.id > last_id)
                                   .order_by(RunEvent.id).limit(500)).all()
                run = s.get(Run, run_id)
                for e in events:
                    last_id = e.id
                    data = json.dumps({"id": e.id, "ts": e.ts.isoformat(), "level": e.level, "message": e.message},
                                      ensure_ascii=False)
                    yield f"id: {e.id}\nevent: log\ndata: {data}\n\n"
                if run.status in FINAL and not events:
                    payload = json.dumps({"status": run.status, "stats": run.stats, "error": run.error},
                                         ensure_ascii=False)
                    yield f"event: done\ndata: {payload}\n\n"
                    return
            yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
