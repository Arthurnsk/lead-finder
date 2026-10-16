"""All ORM models. Every tenant-owned table carries organization_id."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin, utcnow


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------- tenancy / auth

ROLES = ("owner", "admin", "manager", "viewer")
ROLE_RANK = {r: i for i, r in enumerate(reversed(ROLES))}  # viewer=0 … owner=3


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="viewer")

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship()


# ---------------------------------------------------------------- projects (niches)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("organization_id", "slug"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    site: Mapped[str] = mapped_column(String(300), default="")
    offer: Mapped[str] = mapped_column(Text, default="")
    icp: Mapped[str] = mapped_column(Text, default="")
    examples: Mapped[list] = mapped_column(JSON, default=list)
    blocked_hosts: Mapped[list] = mapped_column(JSON, default=list)
    demand_patterns: Mapped[list] = mapped_column(JSON, default=list)
    exclude_patterns: Mapped[list] = mapped_column(JSON, default=list)  # hard topic stop-list before the LLM
    region: Mapped[str] = mapped_column(String(20), default="ru-ru")
    timelimit: Mapped[str] = mapped_column(String(4), default="m")  # d/w/m/y/""
    max_age_days: Mapped[int] = mapped_column(Integer, default=90)
    min_score: Mapped[float] = mapped_column(Float, default=0.65)
    max_leads_per_run: Mapped[int] = mapped_column(Integer, default=30)
    schedule_cron: Mapped[str] = mapped_column(String(100), default="")  # "" = manual only
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    sources: Mapped[list[ProjectSource]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectSource.created_at"
    )


SOURCE_TYPES = ("vk", "telegram", "telegram_chat", "tenders", "web_watch", "rss", "searxng", "ddg")


class ProjectSource(TimestampMixin, Base):
    __tablename__ = "project_sources"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # vk/searxng/ddg: {"queries": [...]}; rss: {"feeds": [...]}; telegram: {"channels": [...]}
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    # health, so a silently broken source is visible instead of quietly returning nothing
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="")
    fail_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_items: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Project] = relationship(back_populates="sources")


# ---------------------------------------------------------------- runs (also the job queue)

RUN_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")


class Run(TimestampMixin, Base):
    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual / schedule
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str] = mapped_column(String(100), default="")
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(10), default="info")  # info / lead / warn / error
    message: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------- leads

LEAD_STATUSES = ("new", "in_progress", "contacted", "won", "lost", "spam")
FEEDBACK = ("", "good", "bad")


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("project_id", "url"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(20), default="")
    platform: Mapped[str] = mapped_column(String(40), default="")
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    query: Mapped[str] = mapped_column(Text, default="")
    posted_at: Mapped[date | None] = mapped_column(Date)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    segment: Mapped[str] = mapped_column(String(80), default="")
    interest_signal: Mapped[str] = mapped_column(Text, default="")
    display_name: Mapped[str] = mapped_column(String(200), default="")
    contact_hint: Mapped[str] = mapped_column(String(200), default="")
    contacts: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    feedback: Mapped[str] = mapped_column(String(10), default="")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str] = mapped_column(Text, default="")
    found_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SeenUrl(Base):
    __tablename__ = "seen_urls"
    __table_args__ = (UniqueConstraint("project_id", "url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    verdict: Mapped[str] = mapped_column(String(10), default="")  # lead / reject
    score: Mapped[float] = mapped_column(Float, default=0.0)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- settings / integrations / audit


class LlmSettings(TimestampMixin, Base):
    __tablename__ = "llm_settings"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), unique=True
    )
    base_url: Mapped[str] = mapped_column(String(500), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    api_key_enc: Mapped[str] = mapped_column(Text, default="")
    disable_thinking: Mapped[bool] = mapped_column(Boolean, default=True)
    # Backup provider: used automatically when the primary one is down or rate-limited
    fallback_base_url: Mapped[str] = mapped_column(String(500), default="")
    fallback_model: Mapped[str] = mapped_column(String(200), default="")
    fallback_api_key_enc: Mapped[str] = mapped_column(Text, default="")


INTEGRATION_TYPES = ("telegram", "webhook", "vk_token", "telegram_account")


class Integration(TimestampMixin, Base):
    __tablename__ = "integrations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config_enc: Mapped[str] = mapped_column(Text, default="")  # Fernet-encrypted JSON (tokens)


class Heartbeat(Base):
    """Worker liveness: the API can tell «worker is alive» from «nothing is running»."""

    __tablename__ = "heartbeats"
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    info: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")
