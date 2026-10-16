import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Cloud, KeyRound, Plus, RefreshCw, Server, Trash2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AuditEntry, Integration, LlmSettings, LlmTestResult, Member, Project, Provider, Role } from "../api/types";
import { useAuth } from "../auth";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ErrorBox,
  Field,
  Input,
  Loading,
  Modal,
  PageHeader,
  Select,
  Switch,
  Tabs,
  useToast,
} from "../components/ui";
import { ROLE, fmtDateTime } from "../lib/format";

type Tab = "team" | "llm" | "integrations" | "health" | "audit" | "profile";

export default function SettingsPage() {
  const { can, org } = useAuth();
  const admin = can("admin");
  const [tab, setTab] = useState<Tab>(admin ? "team" : "profile");
  const tabs = [
    ...(admin
      ? [
          { id: "team" as const, label: "Команда" },
          { id: "llm" as const, label: "Модель" },
          { id: "integrations" as const, label: "Интеграции" },
          { id: "health" as const, label: "Диагностика" },
          { id: "audit" as const, label: "Журнал действий" },
        ]
      : []),
    { id: "profile" as const, label: "Профиль" },
  ];
  return (
    <>
      <PageHeader title="Настройки" subtitle={org?.name} />
      <div className="mb-6">
        <Tabs tabs={tabs} value={tab} onChange={setTab} />
      </div>
      {tab === "team" && <TeamTab />}
      {tab === "llm" && <LlmTab />}
      {tab === "integrations" && <IntegrationsTab />}
      {tab === "health" && <HealthTab />}
      {tab === "audit" && <AuditTab />}
      {tab === "profile" && <ProfileTab />}
    </>
  );
}

function TeamTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const { me, can } = useAuth();
  const members = useQuery({ queryKey: ["members"], queryFn: () => api<Member[]>("/members") });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ email: "", full_name: "", role: "manager" as Role, password: "" });
  const add = useMutation({
    mutationFn: () => api("/members", { method: "POST", json: f }),
    onSuccess: () => {
      setOpen(false);
      setF({ email: "", full_name: "", role: "manager", password: "" });
      qc.invalidateQueries({ queryKey: ["members"] });
      toast("Пользователь добавлен");
    },
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: object }) => api(`/members/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members"] }),
    onError: (e) => toast(e instanceof Error ? e.message : "Ошибка", "bad"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/members/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["members"] }),
    onError: (e) => toast(e instanceof Error ? e.message : "Ошибка", "bad"),
  });
  const roles = (Object.keys(ROLE) as Role[]).filter((r) => r !== "owner" || can("owner"));

  return (
    <Card>
      <CardHeader
        title="Пользователи"
        subtitle="Менеджер разбирает лиды и запускает поиск; администратор настраивает проекты и интеграции"
        actions={<Button size="sm" variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>Добавить</Button>}
      />
      {members.isLoading ? (
        <Loading />
      ) : (
        <ul className="divide-y divide-border">
          {members.data?.map((m) => (
            <li key={m.user_id} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <div className="min-w-0 flex-1">
                <div className="font-medium">{m.full_name || m.email}</div>
                <div className="text-[13px] text-text-3">{m.email}</div>
              </div>
              {!m.is_active && <Badge tone="warn">Отключён</Badge>}
              <Select
                className="w-44"
                value={m.role}
                disabled={m.user_id === me?.id}
                onChange={(e) => patch.mutate({ id: m.user_id, body: { role: e.target.value } })}
              >
                {(Object.keys(ROLE) as Role[]).map((r) => (
                  <option key={r} value={r} disabled={!roles.includes(r)}>
                    {ROLE[r]}
                  </option>
                ))}
              </Select>
              {m.user_id !== me?.id && (
                <>
                  <Switch checked={m.is_active} onChange={(v) => patch.mutate({ id: m.user_id, body: { is_active: v } })} label="Активен" />
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label="Удалить из организации"
                    icon={<Trash2 className="size-4" />}
                    onClick={() => confirm(`Удалить ${m.email} из организации?`) && remove.mutate(m.user_id)}
                  />
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Новый пользователь"
        footer={
          <>
            <Button onClick={() => setOpen(false)}>Отмена</Button>
            <Button variant="primary" loading={add.isPending} onClick={() => add.mutate()}>
              Добавить
            </Button>
          </>
        }
      >
        <Field label="Email">
          <Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        </Field>
        <Field label="Имя">
          <Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
        </Field>
        <Field label="Роль">
          <Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
            {roles.map((r) => (
              <option key={r} value={r}>
                {ROLE[r]}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Временный пароль" hint="Минимум 10 символов. Передайте его пользователю, он сменит его в профиле.">
          <Input type="text" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        </Field>
        <ErrorBox error={add.error} />
      </Modal>
    </Card>
  );
}

function LlmTab() {
  const toast = useToast();
  const q = useQuery({ queryKey: ["llm"], queryFn: () => api<LlmSettings>("/settings/llm") });
  const providers = useQuery({ queryKey: ["llm-providers"], queryFn: () => api<Provider[]>("/settings/llm/providers") });
  const [f, setF] = useState({
    base_url: "",
    model: "",
    api_key: "",
    disable_thinking: true,
    fallback_base_url: "",
    fallback_model: "",
    fallback_api_key: "",
  });
  const [editingKey, setEditingKey] = useState(false);
  useEffect(() => {
    if (q.data) {
      setF({
        base_url: q.data.base_url,
        model: q.data.model,
        api_key: "",
        disable_thinking: q.data.disable_thinking,
        fallback_base_url: q.data.fallback_base_url,
        fallback_model: q.data.fallback_model,
        fallback_api_key: "",
      });
      setEditingKey(!q.data.has_api_key);
    }
  }, [q.data]);

  const save = useMutation({
    mutationFn: () =>
      api<LlmSettings>("/settings/llm", {
        method: "PUT",
        json: { ...f, api_key: f.api_key || null, fallback_api_key: f.fallback_api_key || null },
      }),
    onSuccess: () => {
      q.refetch();
      toast("Сохранено");
    },
  });
  type ModelList = { ok: boolean; models: string[]; chat_models: string[]; error?: string };
  const models = useQuery({
    queryKey: ["llm-models", "primary", q.data?.base_url],
    queryFn: () => api<ModelList>("/settings/llm/models?which=primary"),
    enabled: false,
  });
  const fallbackModels = useQuery({
    queryKey: ["llm-models", "fallback", q.data?.fallback_base_url],
    queryFn: () => api<ModelList>("/settings/llm/models?which=fallback"),
    enabled: false,
  });
  const test = useMutation({
    mutationFn: (which: "primary" | "fallback" = "primary") =>
      api<LlmTestResult>(`/settings/llm/test?which=${which}`, { method: "POST" }),
  });

  if (q.isLoading || !q.data) return <Loading />;
  const saved = q.data;
  // Detected live from what is typed, so the badge reacts before saving
  const typed = providers.data?.find((p) => p.base_url && f.base_url.startsWith(p.base_url.replace(/\/v1$/, "")));
  const provider = typed ?? saved.provider;
  const dirty =
    f.base_url !== saved.base_url ||
    f.model !== saved.model ||
    f.disable_thinking !== saved.disable_thinking ||
    f.fallback_base_url !== saved.fallback_base_url ||
    f.fallback_model !== saved.fallback_model ||
    !!f.api_key ||
    !!f.fallback_api_key;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Языковая модель"
          subtitle="Любой OpenAI-совместимый сервер: локальная Qwen на этом Mac или облачный API"
          actions={
            <Badge tone={provider.kind === "local" ? "good" : "accent"} icon={provider.kind === "local" ? <Server className="size-3.5" /> : <Cloud className="size-3.5" />}>
              {provider.label}
            </Badge>
          }
        />

        <div className="grid gap-4 px-5 py-4 md:grid-cols-2">
          <Field label="Провайдер" hint={provider.note || undefined}>
            <Select
              value={providers.data?.some((p) => p.base_url === f.base_url) ? f.base_url : ""}
              onChange={(e) => e.target.value && setF({ ...f, base_url: e.target.value, model: "" })}
            >
              <option value="">Свой адрес…</option>
              {providers.data?.map((p) => (
                <option key={p.id} value={p.base_url}>
                  {p.label} {p.kind === "local" ? "· локально" : ""}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Адрес API">
            <Input value={f.base_url} onChange={(e) => setF({ ...f, base_url: e.target.value })} className="font-mono text-[13px]" />
          </Field>

          <Field
            label="API-ключ"
            hint={
              provider.docs_url ? (
                <a href={provider.docs_url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                  Где взять ключ {provider.label} ↗
                </a>
              ) : provider.needs_key ? undefined : (
                "Локальному серверу ключ не нужен"
              )
            }
          >
            {saved.has_api_key && !editingKey ? (
              <div className="flex items-center gap-2">
                <Badge tone="good" icon={<KeyRound className="size-3.5" />}>
                  Ключ сохранён · {saved.key_hint}
                </Badge>
                <Button size="sm" onClick={() => setEditingKey(true)}>
                  Заменить
                </Button>
                <Button size="sm" variant="danger" onClick={() => { setF({ ...f, api_key: "" }); save.mutate(); }}>
                  Удалить
                </Button>
              </div>
            ) : (
              <div className="flex gap-2">
                <Input
                  type="password"
                  autoComplete="off"
                  placeholder={provider.key_prefix ? `${provider.key_prefix}…` : "ключ провайдера"}
                  value={f.api_key}
                  onChange={(e) => setF({ ...f, api_key: e.target.value })}
                />
                {saved.has_api_key && (
                  <Button size="sm" onClick={() => { setEditingKey(false); setF({ ...f, api_key: "" }); }}>
                    Отмена
                  </Button>
                )}
              </div>
            )}
          </Field>

          <Field label="Модель" hint={saved.model_source === "auto" ? "Сейчас берётся первая текстовая модель провайдера" : undefined}>
            <div className="flex gap-2">
              {models.data?.chat_models?.length ? (
                <Select value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })}>
                  <option value="">Автоматически</option>
                  {models.data.chat_models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} placeholder="Автоматически" className="font-mono text-[13px]" />
              )}
              <Button onClick={() => models.refetch()} loading={models.isFetching} icon={<RefreshCw className="size-4" />}>
                Список
              </Button>
            </div>
          </Field>

          <div className="flex items-start gap-3 md:col-span-2">
            <Switch checked={f.disable_thinking} onChange={(v) => setF({ ...f, disable_thinking: v })} label="Отключить рассуждения" />
            <div className="text-sm">
              Отключить «рассуждения» модели
              <div className="text-xs text-text-3">
                Для классификации они не нужны и тратят весь лимит ответа. Если провайдер не принимает этот параметр,
                запрос повторяется без него автоматически.
              </div>
            </div>
          </div>

          {models.data && !models.data.ok && (
            <div className="md:col-span-2">
              <ErrorBox error={models.data.error} />
            </div>
          )}
          {saved.warnings.length > 0 && (
            <ul className="space-y-1 md:col-span-2">
              {saved.warnings.map((w) => (
                <li key={w} className="flex items-start gap-2 text-[13px] text-text-2">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" />
                  {w}
                </li>
              ))}
            </ul>
          )}
          <ErrorBox error={save.error || test.error} />
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
          <div className="min-h-6 text-sm">
            {test.data &&
              test.variables !== "fallback" &&
              (test.data.ok ? (
                <span className="flex flex-wrap items-center gap-2">
                  <Badge tone="good" icon={<CheckCircle2 className="size-3.5" />}>Связь есть</Badge>
                  <span className="text-text-2">
                    {test.data.provider} · <span className="font-mono text-[12.5px]">{test.data.model}</span> · {test.data.latency_ms} мс
                  </span>
                </span>
              ) : (
                <Badge tone="bad" icon={<XCircle className="size-3.5" />} className="whitespace-normal">
                  {test.data.error}
                </Badge>
              ))}
          </div>
          <div className="flex shrink-0 gap-2">
            <Button loading={test.isPending} onClick={() => test.mutate("primary")} disabled={dirty}>
              Проверить связь
            </Button>
            <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()} disabled={!dirty}>
              Сохранить
            </Button>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Резервная модель"
          subtitle="Если основная не отвечает или упёрлась в лимит запросов, движок автоматически продолжит на резервной и напишет об этом в журнале запуска"
          actions={
            saved.fallback_provider && (
              <Badge tone="neutral" icon={<Cloud className="size-3.5" />}>
                {saved.fallback_provider.label}
              </Badge>
            )
          }
        />
        <div className="grid gap-4 px-5 py-4 md:grid-cols-2">
          <Field label="Провайдер">
            <Select
              value={providers.data?.some((pr) => pr.base_url === f.fallback_base_url) ? f.fallback_base_url : ""}
              onChange={(e) => setF({ ...f, fallback_base_url: e.target.value, fallback_model: "" })}
            >
              <option value="">Не использовать / свой адрес</option>
              {providers.data?.map((pr) => (
                <option key={pr.id} value={pr.base_url}>
                  {pr.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Адрес API">
            <Input
              value={f.fallback_base_url}
              onChange={(e) => setF({ ...f, fallback_base_url: e.target.value })}
              placeholder="например https://generativelanguage.googleapis.com/v1beta/openai/"
              className="font-mono text-[13px]"
            />
          </Field>
          <Field
            label="Модель"
            hint={
              fallbackModels.data && !fallbackModels.data.ok
                ? undefined
                : "Нажмите «Список», чтобы получить модели по сохранённому ключу"
            }
          >
            <div className="flex gap-2">
              {fallbackModels.data?.chat_models?.length ? (
                <Select value={f.fallback_model} onChange={(e) => setF({ ...f, fallback_model: e.target.value })}>
                  <option value="">Автоматически</option>
                  {fallbackModels.data.chat_models.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  value={f.fallback_model}
                  onChange={(e) => setF({ ...f, fallback_model: e.target.value })}
                  placeholder="Автоматически"
                  className="font-mono text-[13px]"
                />
              )}
              <Button
                onClick={() => fallbackModels.refetch()}
                loading={fallbackModels.isFetching}
                disabled={dirty || !saved.fallback_base_url}
                icon={<RefreshCw className="size-4" />}
              >
                Список
              </Button>
            </div>
          </Field>
          {fallbackModels.data && !fallbackModels.data.ok && (
            <div className="md:col-span-2">
              <ErrorBox error={fallbackModels.data.error} />
            </div>
          )}
          <Field
            label="API-ключ"
            hint={saved.fallback_has_api_key ? `Сохранён: ${saved.fallback_key_hint}. Пусто — не менять.` : undefined}
          >
            <Input
              type="password"
              autoComplete="off"
              value={f.fallback_api_key}
              onChange={(e) => setF({ ...f, fallback_api_key: e.target.value })}
            />
          </Field>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3">
          <div className="min-h-6 text-sm">
            {dirty ? (
              <span className="text-text-3">Сначала сохраните — потом можно проверить связь</span>
            ) : (
              test.data &&
              test.variables === "fallback" &&
              (test.data.ok ? (
                <span className="flex flex-wrap items-center gap-2">
                  <Badge tone="good" icon={<CheckCircle2 className="size-3.5" />}>Резерв работает</Badge>
                  <span className="text-text-2">
                    {test.data.provider} · <span className="font-mono text-[12.5px]">{test.data.model}</span> ·{" "}
                    {test.data.latency_ms} мс
                  </span>
                </span>
              ) : (
                <Badge tone="bad" icon={<XCircle className="size-3.5" />} className="whitespace-normal">
                  {test.data.error}
                </Badge>
              ))
            )}
          </div>
          <div className="flex shrink-0 gap-2">
            <Button
              loading={test.isPending}
              disabled={dirty || !saved.fallback_base_url}
              onClick={() => test.mutate("fallback")}
            >
              Проверить резервную
            </Button>
            <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()} disabled={!dirty}>
              Сохранить
            </Button>
          </div>
        </div>
      </Card>

      {provider.kind === "cloud" && (
        <p className="text-[13px] text-text-3">
          Облачный провайдер получает тексты найденных постов. Если это нежелательно, используйте локальную модель:
          данные тогда не покидают компьютер.
        </p>
      )}
    </div>
  );
}

const INTEGRATION_FIELDS: Record<Integration["type"], { label: string; help: string; fields: { key: string; label: string; secret?: boolean }[] }> = {
  vk_token: {
    label: "VK-токен",
    help: "Нужен источнику «ВКонтакте» (newsfeed.search). Один на организацию, хранится зашифрованным.",
    fields: [{ key: "token", label: "Access token", secret: true }],
  },
  telegram: {
    label: "Telegram",
    help: "Новые лиды приходят сообщением. Токен — у @BotFather, chat_id — ваш или группы.",
    fields: [
      { key: "bot_token", label: "Токен бота", secret: true },
      { key: "chat_id", label: "chat_id" },
    ],
  },
  webhook: {
    label: "Webhook (CRM)",
    help: "POST JSON на ваш https-адрес при каждом лиде; подпись HMAC-SHA256 в X-LeadFinder-Signature.",
    fields: [
      { key: "url", label: "URL (https://…)" },
      { key: "secret", label: "Секрет для подписи", secret: true },
    ],
  },
};

function IntegrationsTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const list = useQuery({ queryKey: ["integrations"], queryFn: () => api<Integration[]>("/integrations") });
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const [type, setType] = useState<Integration["type"] | null>(null);
  const [cfg, setCfg] = useState<Record<string, string>>({});
  const [projectId, setProjectId] = useState("");
  const add = useMutation({
    mutationFn: () => api("/integrations", { method: "POST", json: { type, config: cfg, project_id: projectId || null } }),
    onSuccess: () => {
      setType(null);
      setCfg({});
      qc.invalidateQueries({ queryKey: ["integrations"] });
      toast("Интеграция добавлена");
    },
  });
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api(`/integrations/${id}?enabled=${enabled}`, { method: "PATCH" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["integrations"] }),
  });
  const del = useMutation({
    mutationFn: (id: string) => api(`/integrations/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["integrations"] }),
  });

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        {(Object.keys(INTEGRATION_FIELDS) as Integration["type"][]).map((t) => (
          <Card key={t} className="flex flex-col p-5">
            <div className="font-semibold">{INTEGRATION_FIELDS[t].label}</div>
            <p className="mt-1 flex-1 text-[13px] text-text-2">{INTEGRATION_FIELDS[t].help}</p>
            <Button size="sm" className="mt-4 self-start" icon={<Plus className="size-4" />} onClick={() => setType(t)}>
              Подключить
            </Button>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader title="Подключено" subtitle="Секреты не показываются — только маска" />
        {list.isLoading ? (
          <Loading />
        ) : !list.data?.length ? (
          <p className="px-5 py-8 text-center text-sm text-text-3">Пока ничего не подключено</p>
        ) : (
          <ul className="divide-y divide-border">
            {list.data.map((i) => (
              <li key={i.id} className="flex items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{INTEGRATION_FIELDS[i.type].label}</div>
                  <div className="truncate text-[13px] text-text-3">
                    {i.summary}
                    {i.project_id && ` · только проект «${projects.data?.find((p) => p.id === i.project_id)?.name ?? "?"}»`}
                  </div>
                </div>
                <Switch checked={i.enabled} onChange={(v) => toggle.mutate({ id: i.id, enabled: v })} label="Включена" />
                <Button variant="ghost" size="sm" aria-label="Удалить" icon={<Trash2 className="size-4" />} onClick={() => confirm("Удалить интеграцию?") && del.mutate(i.id)} />
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Modal
        open={!!type}
        onClose={() => setType(null)}
        title={type ? INTEGRATION_FIELDS[type].label : ""}
        footer={
          <>
            <Button onClick={() => setType(null)}>Отмена</Button>
            <Button variant="primary" loading={add.isPending} onClick={() => add.mutate()}>
              Сохранить
            </Button>
          </>
        }
      >
        {type &&
          INTEGRATION_FIELDS[type].fields.map((fd) => (
            <Field key={fd.key} label={fd.label}>
              <Input
                type={fd.secret ? "password" : "text"}
                autoComplete="off"
                value={cfg[fd.key] ?? ""}
                onChange={(e) => setCfg({ ...cfg, [fd.key]: e.target.value })}
              />
            </Field>
          ))}
        {type && type !== "vk_token" && (
          <Field label="Для проекта" hint="Пусто — для всех проектов организации">
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">Все проекты</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <ErrorBox error={add.error} />
      </Modal>
    </div>
  );
}

interface HealthCheck {
  name: string;
  ok: boolean;
  detail: string;
  ms: number | null;
  hint: string;
}

function HealthTab() {
  const q = useQuery({
    queryKey: ["diagnostics"],
    queryFn: () => api<{ checked_at: string; ok: boolean; checks: HealthCheck[] }>("/diagnostics"),
    refetchOnMount: true,
  });
  const failed = q.data?.checks.filter((c) => !c.ok).length ?? 0;
  return (
    <Card>
      <CardHeader
        title="Диагностика системы"
        subtitle="Проверяет всё разом: базу, фоновый worker, обе модели и каждый включённый источник"
        actions={
          <Button loading={q.isFetching} onClick={() => q.refetch()} icon={<RefreshCw className="size-4" />}>
            Проверить
          </Button>
        }
      />
      {q.isLoading ? (
        <Loading />
      ) : (
        <>
          <div className="border-b border-border px-5 py-3">
            {q.data?.ok ? (
              <Badge tone="good" icon={<CheckCircle2 className="size-3.5" />}>Всё исправно</Badge>
            ) : (
              <Badge tone="bad" icon={<XCircle className="size-3.5" />}>Проблем: {failed}</Badge>
            )}
            <span className="ml-2 text-xs text-text-3">проверено {fmtDateTime(q.data?.checked_at)}</span>
          </div>
          <ul className="divide-y divide-border">
            {q.data?.checks.map((c) => (
              <li key={c.name} className="flex items-start gap-3 px-5 py-3">
                {c.ok ? (
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-good" />
                ) : (
                  <XCircle className="mt-0.5 size-4 shrink-0 text-bad" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{c.name}</span>
                    {c.ms !== null && <span className="text-xs text-text-3">{c.ms} мс</span>}
                  </div>
                  <div className="text-[13px] text-text-2">{c.detail}</div>
                  {!c.ok && c.hint && <div className="mt-0.5 text-[13px] text-warn">{c.hint}</div>}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

function AuditTab() {
  const q = useQuery({ queryKey: ["audit"], queryFn: () => api<AuditEntry[]>("/audit?limit=300") });
  const members = useQuery({ queryKey: ["members"], queryFn: () => api<Member[]>("/members") });
  const who = (id: string | null) => members.data?.find((m) => m.user_id === id)?.email ?? (id ? id.slice(0, 8) : "система");
  return (
    <Card>
      <CardHeader title="Журнал действий" subtitle="Кто и что менял в организации" />
      {q.isLoading ? (
        <Loading />
      ) : (
        <div className="scroll-thin overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-text-3">
                <th className="px-5 py-2.5">Когда</th>
                <th className="px-2 py-2.5">Кто</th>
                <th className="px-2 py-2.5">Действие</th>
                <th className="px-5 py-2.5">Детали</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {q.data?.map((a) => (
                <tr key={a.id}>
                  <td className="whitespace-nowrap px-5 py-2.5 text-text-2">{fmtDateTime(a.ts)}</td>
                  <td className="px-2 py-2.5">{who(a.user_id)}</td>
                  <td className="px-2 py-2.5 font-mono text-[12.5px]">{a.action}</td>
                  <td className="max-w-md truncate px-5 py-2.5 text-[13px] text-text-3">
                    {Object.keys(a.data).length ? JSON.stringify(a.data) : ""} {a.ip && `· ${a.ip}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ProfileTab() {
  const toast = useToast();
  const { me } = useAuth();
  const [f, setF] = useState({ current_password: "", new_password: "", repeat: "" });
  const save = useMutation({
    mutationFn: () => {
      if (f.new_password !== f.repeat) throw new Error("Пароли не совпадают");
      return api("/auth/password", { method: "POST", json: { current_password: f.current_password, new_password: f.new_password } });
    },
    onSuccess: () => {
      setF({ current_password: "", new_password: "", repeat: "" });
      toast("Пароль изменён");
    },
  });
  return (
    <Card className="max-w-lg">
      <CardHeader title="Смена пароля" subtitle={me?.email} />
      <div className="space-y-4 px-5 py-4">
        <Field label="Текущий пароль">
          <Input type="password" autoComplete="current-password" value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} />
        </Field>
        <Field label="Новый пароль" hint="Минимум 10 символов">
          <Input type="password" autoComplete="new-password" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} />
        </Field>
        <Field label="Повторите">
          <Input type="password" autoComplete="new-password" value={f.repeat} onChange={(e) => setF({ ...f, repeat: e.target.value })} />
        </Field>
        <ErrorBox error={save.error} />
      </div>
      <div className="flex justify-end border-t border-border px-5 py-3">
        <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
          Сменить пароль
        </Button>
      </div>
    </Card>
  );
}
