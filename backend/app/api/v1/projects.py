import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import audit
from app.db import get_db
from app.deps import OrgContext, client_ip, csrf_protect, org_context, require_role
from app.models import Project, ProjectSource
from app.niche_yaml import build_sources, next_run, parse_niche_yaml, project_to_yaml, validate_cron
from app.engine.discovery import discover_sources
from app.engine.llm import LlmClient
from app.engine.pipeline import llm_config_for
from app.schemas import (
    AddDiscoveredIn,
    DiscoverIn,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    SourceCandidateOut,
    SourceIn,
    SourceOut,
    SourceUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[Depends(csrf_protect)])


def get_project(db: Session, ctx: OrgContext, project_id: uuid.UUID) -> Project:
    project = db.scalar(
        select(Project)
        .options(selectinload(Project.sources))
        .where(Project.id == project_id, Project.organization_id == ctx.org.id)
    )
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


def _apply_schedule(project: Project) -> None:
    try:
        validate_cron(project.schedule_cron)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    project.next_run_at = next_run(project.schedule_cron) if project.schedule_enabled else None


def _ensure_unique_slug(db: Session, ctx: OrgContext, slug: str) -> None:
    if db.scalar(select(Project).where(Project.organization_id == ctx.org.id, Project.slug == slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Проект со slug «{slug}» уже есть")


@router.get("", response_model=list[ProjectOut])
def list_projects(ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db)):
    return db.scalars(
        select(Project)
        .options(selectinload(Project.sources))
        .where(Project.organization_id == ctx.org.id)
        .order_by(Project.created_at)
    ).all()


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate, request: Request,
    ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    _ensure_unique_slug(db, ctx, body.slug)
    project = Project(organization_id=ctx.org.id, **body.model_dump())
    _apply_schedule(project)
    db.add(project)
    audit(db, "project.created", org_id=ctx.org.id, user_id=ctx.user.id, entity="project",
          entity_id=project.id, data={"slug": body.slug}, ip=client_ip(request))
    db.commit()
    return get_project(db, ctx, project.id)


@router.post("/import", response_model=ProjectOut, status_code=201)
async def import_project(
    file: UploadFile, request: Request,
    ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    """Create a project from a niche YAML template (the pilot's niches/*.yaml format)."""
    raw = (await file.read()).decode("utf-8")
    try:
        fields, sources = parse_niche_yaml(raw)
        payload = ProjectCreate(**fields)
    except Exception as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Некорректный YAML: {exc}")
    _ensure_unique_slug(db, ctx, payload.slug)
    project = Project(organization_id=ctx.org.id, **payload.model_dump())
    db.add(project)
    db.flush()
    db.add_all(build_sources(project, sources))
    audit(db, "project.imported", org_id=ctx.org.id, user_id=ctx.user.id, entity="project",
          entity_id=project.id, data={"slug": payload.slug}, ip=client_ip(request))
    db.commit()
    return get_project(db, ctx, project.id)


@router.get("/{project_id}", response_model=ProjectOut)
def read_project(project_id: uuid.UUID, ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db)):
    return get_project(db, ctx, project_id)


@router.get("/{project_id}/export", response_class=PlainTextResponse)
def export_project(project_id: uuid.UUID, ctx: OrgContext = Depends(org_context), db: Session = Depends(get_db)):
    project = get_project(db, ctx, project_id)
    return PlainTextResponse(
        project_to_yaml(project),
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{project.slug}.yaml"'},
    )


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, request: Request,
    ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    project = get_project(db, ctx, project_id)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(project, key, value)
    if {"schedule_cron", "schedule_enabled"} & changes.keys():
        _apply_schedule(project)
    audit(db, "project.updated", org_id=ctx.org.id, user_id=ctx.user.id, entity="project",
          entity_id=project.id, data={"fields": sorted(changes)}, ip=client_ip(request))
    db.commit()
    return get_project(db, ctx, project.id)


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: uuid.UUID, request: Request,
    ctx: OrgContext = Depends(require_role("owner")), db: Session = Depends(get_db),
):
    project = get_project(db, ctx, project_id)
    audit(db, "project.deleted", org_id=ctx.org.id, user_id=ctx.user.id, entity="project",
          entity_id=project.id, data={"slug": project.slug}, ip=client_ip(request))
    db.delete(project)
    db.commit()


# ---------------------------------------------------------------- source discovery


@router.post("/{project_id}/discover", response_model=list[SourceCandidateOut])
def discover(
    project_id: uuid.UUID, body: DiscoverIn, request: Request,
    ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    """Find Telegram channels and forum RSS feeds that match this project, and rate them."""
    project = get_project(db, ctx, project_id)
    known = {ref for s in project.sources for ref in
             [*(s.config.get("channels") or []), *(s.config.get("feeds") or [])]}
    llm = LlmClient(llm_config_for(db, ctx.org.id), timeout=120)
    ok, why = llm.health()
    if not ok:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"LLM недоступна: {why}")
    lines: list[str] = []
    found = discover_sources(llm, project, body.kinds, lambda level, msg: lines.append(msg),
                             max_per_kind=body.max_per_kind, known_refs=known)
    audit(db, "sources.discovered", org_id=ctx.org.id, user_id=ctx.user.id, entity="project",
          entity_id=project.id, data={"kinds": body.kinds, "found": len(found)}, ip=client_ip(request))
    db.commit()
    return [SourceCandidateOut(**c.to_dict()) for c in found]


@router.post("/{project_id}/sources/discovered", response_model=list[SourceOut], status_code=201)
def add_discovered(
    project_id: uuid.UUID, body: AddDiscoveredIn, request: Request,
    ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    """Add chosen candidates: Telegram channels and RSS feeds are merged into one source each."""
    project = get_project(db, ctx, project_id)
    touched: list[ProjectSource] = []
    for kind, key in (("telegram", "channels"), ("rss", "feeds")):
        refs = [c.ref for c in body.candidates if c.type == kind]
        if not refs:
            continue
        source = next((s for s in project.sources if s.type == kind), None)
        if source is None:
            source = ProjectSource(organization_id=ctx.org.id, project_id=project.id, type=kind,
                                   name={"telegram": "Telegram: публичные каналы",
                                         "rss": "RSS-ленты"}[kind], config={})
            db.add(source)
            db.flush()
        config = dict(source.config or {})
        config[key] = list(dict.fromkeys([*(config.get(key) or []), *refs]))
        if kind == "telegram" and body.keywords:
            config["keywords"] = list(dict.fromkeys([*(config.get("keywords") or []), *body.keywords]))
        source.config = config
        source.enabled = True
        touched.append(source)
    audit(db, "sources.added_discovered", org_id=ctx.org.id, user_id=ctx.user.id, entity="project",
          entity_id=project.id, data={"count": len(body.candidates)}, ip=client_ip(request))
    db.commit()
    return touched


# ---------------------------------------------------------------- sources


def _get_source(project: Project, source_id: uuid.UUID) -> ProjectSource:
    source = next((s for s in project.sources if s.id == source_id), None)
    if not source:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    return source


@router.post("/{project_id}/sources", response_model=SourceOut, status_code=201)
def add_source(
    project_id: uuid.UUID, body: SourceIn, request: Request,
    ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    project = get_project(db, ctx, project_id)
    source = ProjectSource(organization_id=ctx.org.id, project_id=project.id, **body.model_dump())
    db.add(source)
    audit(db, "source.added", org_id=ctx.org.id, user_id=ctx.user.id, entity="project",
          entity_id=project.id, data={"type": body.type}, ip=client_ip(request))
    db.commit()
    return source


@router.patch("/{project_id}/sources/{source_id}", response_model=SourceOut)
def update_source(
    project_id: uuid.UUID, source_id: uuid.UUID, body: SourceUpdate, request: Request,
    ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    source = _get_source(get_project(db, ctx, project_id), source_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(source, key, value)
    audit(db, "source.updated", org_id=ctx.org.id, user_id=ctx.user.id, entity="source",
          entity_id=source.id, ip=client_ip(request))
    db.commit()
    return source


@router.delete("/{project_id}/sources/{source_id}", status_code=204)
def delete_source(
    project_id: uuid.UUID, source_id: uuid.UUID, request: Request,
    ctx: OrgContext = Depends(require_role("admin")), db: Session = Depends(get_db),
):
    source = _get_source(get_project(db, ctx, project_id), source_id)
    db.delete(source)
    audit(db, "source.deleted", org_id=ctx.org.id, user_id=ctx.user.id, entity="source",
          entity_id=source_id, ip=client_ip(request))
    db.commit()
