export type Role = "owner" | "admin" | "manager" | "viewer";
export type LeadStatus = "new" | "in_progress" | "contacted" | "won" | "lost" | "spam";
export type Feedback = "" | "good" | "bad";
export type SourceType = "vk" | "telegram" | "telegram_chat" | "tenders" | "web_watch" | "rss" | "searxng" | "ddg";

export interface Org {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  is_superadmin: boolean;
  memberships: { organization: Org; role: Role }[];
}

export interface Member {
  user_id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
}

export interface Source {
  id: string;
  type: SourceType;
  name: string;
  enabled: boolean;
  config: { queries?: string[]; feeds?: string[]; channels?: string[]; chats?: string[]; pages?: string[]; keywords?: string[]; provider?: string; regions?: string[]; engines?: string; interval_sec?: number; [k: string]: unknown };
  last_ok_at: string | null;
  last_error: string;
  fail_streak: number;
  last_items: number;
}

export interface Example {
  text: string;
  is_fit: boolean;
  why?: string;
}

export interface Project {
  id: string;
  slug: string;
  name: string;
  site: string;
  offer: string;
  icp: string;
  examples: Example[];
  blocked_hosts: string[];
  demand_patterns: string[];
  exclude_patterns: string[];
  region: string;
  timelimit: "" | "d" | "w" | "m" | "y";
  max_age_days: number;
  min_score: number;
  max_leads_per_run: number;
  schedule_cron: string;
  schedule_enabled: boolean;
  is_active: boolean;
  next_run_at: string | null;
  created_at: string;
  sources: Source[];
}

export interface RunStats {
  candidates?: number;
  evaluated?: number;
  leads?: number;
  rejected?: number;
  skipped_seen?: number;
  source_errors?: number;
  llm_errors?: number;
  dropped?: Record<string, number>;
  leads_by_source?: Record<string, number>;
}

export interface Run {
  id: string;
  project_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  trigger: "manual" | "schedule";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  stats: RunStats;
  error: string;
}

export interface RunEvent {
  id: number;
  ts: string;
  level: "info" | "lead" | "warn" | "error";
  message: string;
}

export interface Lead {
  id: string;
  project_id: string;
  run_id: string | null;
  source: string;
  platform: string;
  url: string;
  title: string;
  text: string;
  query: string;
  posted_at: string | null;
  score: number;
  reason: string;
  segment: string;
  interest_signal: string;
  display_name: string;
  contact_hint: string;
  contacts: Record<string, unknown>;
  status: LeadStatus;
  feedback: Feedback;
  assignee_id: string | null;
  notes: string;
  found_at: string;
}

export interface Dashboard {
  days: number;
  total: number;
  per_day: { date: string; count: number }[];
  by_status: Record<string, number>;
  by_source: Record<string, number>;
  by_segment: Record<string, number>;
  feedback: { good: number; bad: number; unrated: number; precision: number | null };
  last_runs: { id: string; status: Run["status"]; created_at: string; leads: number; trigger: string }[];
}

export interface Integration {
  id: string;
  type: "telegram" | "webhook" | "vk_token";
  project_id: string | null;
  enabled: boolean;
  summary: string;
}

export interface Provider {
  id: string;
  label: string;
  kind: "cloud" | "local";
  base_url: string;
  docs_url: string;
  key_prefix: string;
  needs_key: boolean;
  note: string;
}

export interface SourceCandidate {
  type: "telegram" | "rss";
  name: string;
  ref: string;
  url: string;
  sample: string;
  score: number;
  reason: string;
  stats: Record<string, string | number>;
}

export interface LlmSettings {
  base_url: string;
  model: string;
  model_source: "explicit" | "auto" | "unset";
  has_api_key: boolean;
  key_hint: string;
  disable_thinking: boolean;
  provider: Provider;
  fallback_base_url: string;
  fallback_model: string;
  fallback_has_api_key: boolean;
  fallback_key_hint: string;
  fallback_provider: Provider | null;
  warnings: string[];
  is_org_override: boolean;
}

export interface LlmTestResult {
  ok: boolean;
  provider: string;
  base_url: string;
  model?: string;
  reply?: string;
  latency_ms?: number;
  error?: string;
}

export interface AuditEntry {
  id: number;
  ts: string;
  user_id: string | null;
  action: string;
  entity: string;
  entity_id: string;
  data: Record<string, unknown>;
  ip: string;
}
