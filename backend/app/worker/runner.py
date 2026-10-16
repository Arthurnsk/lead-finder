"""Background worker: `python -m app.worker.runner`.

Queue = `runs` rows with status 'queued', claimed with SELECT … FOR UPDATE SKIP LOCKED so several
workers can run safely. A scheduler tick enqueues projects whose cron is due.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, engine, utcnow
from app.engine.pipeline import execute_run
from app.models import Heartbeat, Project, Run, RunEvent
from app.niche_yaml import next_run

log = logging.getLogger("worker")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
_stop = False


def _handle_stop(*_):
    global _stop
    _stop = True
    log.info("stop requested, finishing current run…")


def beat(db: Session, state: str) -> None:
    row = db.get(Heartbeat, "worker") or Heartbeat(name="worker")
    row.ts, row.info = utcnow(), {"worker": WORKER_ID, "state": state}
    db.merge(row)
    db.commit()


def claim_next(db: Session) -> Run | None:
    stmt = select(Run).where(Run.status == "queued").order_by(Run.created_at).limit(1)
    if engine.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    run = db.scalar(stmt)
    if run is None:
        db.rollback()
        return None
    run.status = "running"
    run.started_at = utcnow()
    run.locked_by = WORKER_ID
    db.commit()
    return run


def enqueue_due_projects(db: Session) -> int:
    now = utcnow()
    due = db.scalars(select(Project).where(
        Project.schedule_enabled, Project.is_active, Project.next_run_at.is_not(None), Project.next_run_at <= now,
    )).all()
    created = 0
    for p in due:
        p.next_run_at = next_run(p.schedule_cron, now)
        busy = db.scalar(select(Run.id).where(Run.project_id == p.id, Run.status.in_(["queued", "running"])))
        if busy:
            continue  # don't pile up runs if the previous one is still going
        db.add(Run(organization_id=p.organization_id, project_id=p.id, trigger="schedule"))
        created += 1
    db.commit()
    return created


def recover_orphans(db: Session) -> None:
    """Runs left 'running' by a crashed worker on this host are marked failed."""
    host = socket.gethostname()
    orphans = db.scalars(select(Run).where(Run.status == "running", Run.locked_by.like(f"{host}:%"),
                                           Run.locked_by != WORKER_ID)).all()
    for r in orphans:
        r.status, r.finished_at, r.error = "failed", utcnow(), "Worker перезапустился во время запуска"
        db.add(RunEvent(run_id=r.id, level="error", message=r.error))
    if orphans:
        log.warning("recovered %d orphaned runs", len(orphans))
    db.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    log.info("worker %s started (LLM default %s)", WORKER_ID, settings.llm_base_url)
    with SessionLocal() as db:
        recover_orphans(db)

    last_schedule = 0.0
    while not _stop:
        try:
            with SessionLocal() as db:
                beat(db, "idle")
                if time.monotonic() - last_schedule > 30:
                    n = enqueue_due_projects(db)
                    if n:
                        log.info("scheduled %d runs", n)
                    last_schedule = time.monotonic()
                run = claim_next(db)
                if run:
                    beat(db, f"run {run.id}")
                    log.info("run %s (project %s) started", run.id, run.project_id)
                    execute_run(db, run)
                    log.info("run %s finished: %s", run.id, run.status)
                    continue
        except Exception:
            log.exception("worker loop error")
        time.sleep(settings.worker_poll_seconds)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
