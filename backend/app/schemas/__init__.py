from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["owner", "admin", "manager", "viewer"]
SourceType = Literal["vk", "telegram", "telegram_chat", "tenders", "web_watch", "rss", "searxng", "ddg"]
LeadStatus = Literal["new", "in_progress", "contacted", "won", "lost", "spam"]
Feedback = Literal["", "good", "bad"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth / users / orgs


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class OrgOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool


class MembershipOut(BaseModel):
    organization: OrgOut
    role: Role


class MeOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    is_superadmin: bool
    memberships: list[MembershipOut] = []


class OrgCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,78}$")
    owner_email: EmailStr
    owner_password: str | None = Field(default=None, min_length=10)
    owner_name: str = ""


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool


class MemberCreate(BaseModel):
    email: EmailStr
    full_name: str = ""
    role: Role = "manager"
    password: str = Field(min_length=10)


class MemberUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)


# ---------------------------------------------------------------- projects / sources


class SourceIn(BaseModel):
    type: SourceType
    name: str = ""
    enabled: bool = True
    config: dict = {}


class SourceUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    config: dict | None = None


class DiscoverIn(BaseModel):
    kinds: list[Literal["telegram", "rss"]] = ["telegram", "rss"]
    max_per_kind: int = Field(default=6, ge=1, le=15)


class SourceCandidateOut(BaseModel):
    type: Literal["telegram", "rss"]
    name: str
    ref: str
    url: str
    sample: str = ""
    score: float = 0
    reason: str = ""
    stats: dict = {}


class AddDiscoveredIn(BaseModel):
    candidates: list[SourceCandidateOut]
    keywords: list[str] = []  # for Telegram channels: keep only posts containing one of these


class SourceOut(ORM):
    id: uuid.UUID
    type: str
    name: str
    enabled: bool
    config: dict
    last_ok_at: datetime | None = None
    last_error: str = ""
    fail_streak: int = 0
    last_items: int = 0


class ProjectBase(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    site: str = ""
    offer: str = ""
    icp: str = ""
    examples: list[dict] = []
    blocked_hosts: list[str] = []
    demand_patterns: list[str] = []
    exclude_patterns: list[str] = []
    region: str = "ru-ru"
    timelimit: Literal["", "d", "w", "m", "y"] = "m"
    max_age_days: int = Field(default=90, ge=0, le=3650)
    min_score: float = Field(default=0.65, ge=0, le=1)
    max_leads_per_run: int = Field(default=30, ge=1, le=500)
    schedule_cron: str = ""
    schedule_enabled: bool = False
    is_active: bool = True


class ProjectCreate(ProjectBase):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,78}$")


class ProjectUpdate(BaseModel):
    name: str | None = None
    site: str | None = None
    offer: str | None = None
    icp: str | None = None
    examples: list[dict] | None = None
    blocked_hosts: list[str] | None = None
    demand_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None
    region: str | None = None
    timelimit: Literal["", "d", "w", "m", "y"] | None = None
    max_age_days: int | None = Field(default=None, ge=0, le=3650)
    min_score: float | None = Field(default=None, ge=0, le=1)
    max_leads_per_run: int | None = Field(default=None, ge=1, le=500)
    schedule_cron: str | None = None
    schedule_enabled: bool | None = None
    is_active: bool | None = None


class ProjectOut(ProjectBase, ORM):
    id: uuid.UUID
    slug: str
    next_run_at: datetime | None
    created_at: datetime
    sources: list[SourceOut] = []


# ---------------------------------------------------------------- runs / leads


class RunOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    trigger: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    stats: dict
    error: str


class RunEventOut(ORM):
    id: int
    ts: datetime
    level: str
    message: str


class LeadOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID | None
    source: str
    platform: str
    url: str
    title: str
    text: str
    query: str
    posted_at: date | None
    score: float
    reason: str
    segment: str
    interest_signal: str
    display_name: str
    contact_hint: str
    contacts: dict
    status: str
    feedback: str
    assignee_id: uuid.UUID | None
    notes: str
    found_at: datetime


class LeadUpdate(BaseModel):
    status: LeadStatus | None = None
    feedback: Feedback | None = None
    assignee_id: uuid.UUID | None = None
    notes: str | None = None


class LeadPage(BaseModel):
    items: list[LeadOut]
    total: int


# ---------------------------------------------------------------- settings / integrations / audit


class ProviderOut(BaseModel):
    id: str
    label: str
    kind: Literal["cloud", "local"]
    base_url: str = ""
    docs_url: str = ""
    key_prefix: str = ""
    needs_key: bool = True
    note: str = ""


class LlmSettingsOut(BaseModel):
    base_url: str
    model: str
    model_source: Literal["explicit", "auto", "unset"] = "unset"
    has_api_key: bool
    key_hint: str = ""
    disable_thinking: bool
    provider: ProviderOut
    fallback_base_url: str = ""
    fallback_model: str = ""
    fallback_has_api_key: bool = False
    fallback_key_hint: str = ""
    fallback_provider: ProviderOut | None = None
    warnings: list[str] = []
    is_org_override: bool = False


class LlmSettingsIn(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key: str | None = None  # None = keep existing
    disable_thinking: bool = True
    fallback_base_url: str = ""
    fallback_model: str = ""
    fallback_api_key: str | None = None


class IntegrationIn(BaseModel):
    type: Literal["telegram", "webhook", "vk_token", "telegram_account"]
    project_id: uuid.UUID | None = None
    enabled: bool = True
    config: dict = {}  # telegram: bot_token, chat_id; webhook: url, secret; vk_token: token


class IntegrationOut(BaseModel):
    id: uuid.UUID
    type: str
    project_id: uuid.UUID | None
    enabled: bool
    summary: str  # masked, never the secret itself


class AuditOut(ORM):
    id: int
    ts: datetime
    user_id: uuid.UUID | None
    action: str
    entity: str
    entity_id: str
    data: dict
    ip: str
