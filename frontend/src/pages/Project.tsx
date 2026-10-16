import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, Play, Plus, Radar, Trash2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, apiUrl, ApiError } from "../api/client";
import type { Example, Project, Run, Source, SourceCandidate, SourceType } from "../api/types";
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
  Textarea,
  useToast,
} from "../components/ui";
import { SOURCE_LABEL, fmtDateTime } from "../lib/format";

type Tab = "general" | "sources" | "examples" | "schedule";

const SOURCE_HELP: Record<SourceType, string> = {
  vk: "Официальный VK API: поиск по всем публичным постам за период свежести. Бесплатно, нужен токен в Настройках → Интеграции.",
  telegram: "Публичные Telegram-каналы через веб-превью t.me — без API, без аккаунта. Закрытые каналы и чаты так читать нельзя.",
  telegram_chat: "Чаты, в которых состоит ваш аккаунт: посёлки, СНТ, регионы. У каждого сообщения виден @ник автора — можно написать лично. Нужен разовый вход: Настройки → Интеграции → Telegram-аккаунт.",
  tenders: "Государственные системы: torgi.gov.ru (земельные лоты) и zakupki.gov.ru (заказы на кадастровые и землеустроительные работы). Без ключей, с официальными контактами заказчика.",
  web_watch: "Следит за страницей со списком новых вопросов или тем на сайтах без RSS (например, Правовед) и читает каждый новый материал.",
  searxng: "Свой метапоиск (Brave и др.). Бесплатно, но с одного IP поисковики ограничивают частоту — запросы идут с паузой.",
  rss: "RSS/Atom-ленты форумов и сервисов вопросов. Стабильно и всегда свежее.",
  ddg: "DuckDuckGo напрямую — резервный вариант, часто отвечает пусто или капчей.",
};

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

export default function ProjectPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>("general");
  const q = useQuery({ queryKey: ["project", id], queryFn: () => api<Project>(`/projects/${id}`) });

  const run = useMutation({
    mutationFn: () => api<Run>(`/projects/${id}/runs`, { method: "POST" }),
    onSuccess: (r) => nav(`/runs/${r.id}`),
    onError: (e) => toast(e instanceof ApiError ? e.message : "Не удалось запустить", "bad"),
  });

  if (q.isLoading) return <Loading />;
  if (!q.data) return <ErrorBox error={q.error ?? "Проект не найден"} />;
  const p = q.data;
  const refresh = (data?: Project) => {
    if (data) qc.setQueryData(["project", id], data);
    else qc.invalidateQueries({ queryKey: ["project", id] });
    qc.invalidateQueries({ queryKey: ["projects"] });
  };

  return (
    <>
      <div className="mb-2 text-sm text-text-3">
        <Link to="/projects" className="hover:text-text">
          Проекты
        </Link>{" "}
        / {p.name}
      </div>
      <PageHeader
        title={p.name}
        subtitle={p.site || p.slug}
        actions={
          <>
            <a href={apiUrl(`/projects/${p.id}/export`)} download>
              <Button icon={<Download className="size-4" />}>YAML</Button>
            </a>
            {can("manager") && (
              <Button variant="primary" icon={<Play className="size-4" />} loading={run.isPending} onClick={() => run.mutate()}>
                Запустить поиск
              </Button>
            )}
          </>
        }
      />
      <div className="mb-6">
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={[
            { id: "general", label: "Кого ищем" },
            { id: "sources", label: "Источники", count: p.sources.filter((s) => s.enabled).length },
            { id: "examples", label: "Примеры", count: p.examples.length },
            { id: "schedule", label: "Расписание и фильтры" },
          ]}
        />
      </div>
      {tab === "general" && <GeneralTab p={p} onSaved={refresh} readOnly={!can("admin")} />}
      {tab === "sources" && <SourcesTab p={p} onSaved={refresh} readOnly={!can("admin")} />}
      {tab === "examples" && <ExamplesTab p={p} onSaved={refresh} readOnly={!can("admin")} />}
      {tab === "schedule" && <ScheduleTab p={p} onSaved={refresh} readOnly={!can("admin")} />}
    </>
  );
}

function useSave(p: Project, onSaved: (d?: Project) => void) {
  const toast = useToast();
  return useMutation({
    mutationFn: (patch: Partial<Project>) => api<Project>(`/projects/${p.id}`, { method: "PATCH", json: patch }),
    onSuccess: (d) => {
      onSaved(d);
      toast("Сохранено");
    },
  });
}

function SaveBar({ onSave, loading, error, disabled }: { onSave: () => void; loading: boolean; error: unknown; disabled?: boolean }) {
  return (
    <div className="flex items-center justify-end gap-3 border-t border-border px-5 py-3">
      <div className="flex-1">
        <ErrorBox error={error} />
      </div>
      <Button variant="primary" onClick={onSave} loading={loading} disabled={disabled}>
        Сохранить
      </Button>
    </div>
  );
}

type TabProps = { p: Project; onSaved: (d?: Project) => void; readOnly: boolean };

function GeneralTab({ p, onSaved, readOnly }: TabProps) {
  const [f, setF] = useState({ name: p.name, site: p.site, offer: p.offer, icp: p.icp });
  const save = useSave(p, onSaved);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Card>
      <CardHeader title="Описание ниши" subtitle="Модель читает эти поля при оценке каждого кандидата" />
      <div className="grid gap-4 px-5 py-4 md:grid-cols-2">
        <Field label="Название">
          <Input value={f.name} onChange={set("name")} disabled={readOnly} />
        </Field>
        <Field label="Сайт компании">
          <Input value={f.site} onChange={set("site")} disabled={readOnly} />
        </Field>
        <Field label="Что продаёт компания" className="md:col-span-2" hint="Коротко: услуги и продукты, которые закрывают запросы лидов">
          <Textarea rows={3} value={f.offer} onChange={set("offer")} disabled={readOnly} />
        </Field>
        <Field
          label="Идеальный клиент (ICP)"
          className="md:col-span-2"
          hint="Кто лид (ДА) и кто нет (НЕТ). Чем конкретнее — тем точнее отбор."
        >
          <Textarea rows={16} value={f.icp} onChange={set("icp")} disabled={readOnly} className="font-mono text-[13px]" />
        </Field>
      </div>
      {!readOnly && <SaveBar onSave={() => save.mutate(f)} loading={save.isPending} error={save.error} />}
    </Card>
  );
}

function SourcesTab({ p, onSaved, readOnly }: TabProps) {
  const [adding, setAdding] = useState<SourceType | "">("");
  const [finder, setFinder] = useState(false);
  const add = useMutation({
    mutationFn: (type: SourceType) =>
      api(`/projects/${p.id}/sources`, {
        method: "POST",
        json: { type, name: SOURCE_LABEL[type], config: type === "rss" ? { feeds: [] } : { queries: [] } },
      }),
    onSuccess: () => {
      setAdding("");
      onSaved();
    },
  });
  return (
    <div className="space-y-4">
      {p.sources.map((s) => (
        <SourceCard key={s.id} projectId={p.id} s={s} onSaved={onSaved} readOnly={readOnly} />
      ))}
      {!readOnly && (
        <Card>
          <CardHeader
            title="Не хватает источников?"
            subtitle="Программа сама поищет Telegram-каналы и RSS-ленты форумов по вашей нише и оценит каждую площадку"
            actions={
              <Button variant="primary" icon={<Radar className="size-4" />} onClick={() => setFinder(true)}>
                Найти источники
              </Button>
            }
          />
        </Card>
      )}
      {finder && <SourceFinder projectId={p.id} onClose={() => setFinder(false)} onAdded={onSaved} />}
      {!readOnly && (
        <div className="flex items-center gap-2">
          <Select value={adding} onChange={(e) => setAdding(e.target.value as SourceType)} className="w-56">
            <option value="">Добавить источник…</option>
            {(Object.keys(SOURCE_HELP) as SourceType[]).map((t) => (
              <option key={t} value={t}>
                {SOURCE_LABEL[t]}
              </option>
            ))}
          </Select>
          <Button icon={<Plus className="size-4" />} disabled={!adding} loading={add.isPending} onClick={() => adding && add.mutate(adding)}>
            Добавить
          </Button>
        </div>
      )}
    </div>
  );
}

function SourceCard({ projectId, s, onSaved, readOnly }: { projectId: string; s: Source; onSaved: () => void; readOnly: boolean }) {
  const toast = useToast();
  const KEY_BY_TYPE: Record<string, "feeds" | "channels" | "chats" | "pages" | "queries"> = {
    rss: "feeds",
    telegram: "channels",
    telegram_chat: "chats",
    web_watch: "pages",
  };
  const key = KEY_BY_TYPE[s.type] ?? "queries";
  const listLabel = {
    feeds: "RSS-ленты",
    channels: "Каналы (@name)",
    chats: "Чаты (@name или ссылка)",
    pages: "Страницы со списками",
    queries: "Запросы",
  }[key];
  const listHint = {
    feeds: "По одному URL в строке",
    channels: "По одному каналу в строке, без @ или ссылкой t.me/...",
    chats: "По одному чату в строке. Ваш аккаунт должен состоять в чате.",
    pages: "По одному адресу в строке: страница «новые вопросы» или «новые темы»",
    queries: "По одному запросу в строке",
  }[key];
  const [text, setText] = useState(((s.config[key] as string[] | undefined) ?? []).join("\n"));
  const [keywords, setKeywords] = useState((s.config.keywords ?? []).join("\n"));
  useEffect(() => {
    setText(((s.config[key] as string[] | undefined) ?? []).join("\n"));
    setKeywords((s.config.keywords ?? []).join("\n"));
  }, [s, key]);
  const patch = useMutation({
    mutationFn: (body: Partial<Source>) => api(`/projects/${projectId}/sources/${s.id}`, { method: "PATCH", json: body }),
    onSuccess: () => {
      onSaved();
      toast("Источник сохранён");
    },
  });
  const del = useMutation({
    mutationFn: () => api(`/projects/${projectId}/sources/${s.id}`, { method: "DELETE" }),
    onSuccess: () => onSaved(),
  });
  const n = lines(text).length;
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {s.name || SOURCE_LABEL[s.type]}
            <Badge tone={s.enabled ? "good" : "neutral"}>{s.enabled ? "Включён" : "Выключен"}</Badge>
            {s.fail_streak > 0 ? (
              <Badge tone="bad" icon={<AlertTriangle className="size-3" />}>
                Сбоев подряд: {s.fail_streak}
              </Badge>
            ) : s.last_ok_at ? (
              <Badge tone="neutral">
                Последний сбор: {fmtDateTime(s.last_ok_at)} · {s.last_items} шт.
              </Badge>
            ) : null}
          </span>
        }
        subtitle={s.last_error ? `Последняя ошибка: ${s.last_error.slice(0, 180)}` : SOURCE_HELP[s.type]}
        actions={
          !readOnly && (
            <>
              <Switch checked={s.enabled} onChange={(v) => patch.mutate({ enabled: v })} label="Включить источник" />
              <Button
                variant="ghost"
                size="sm"
                aria-label="Удалить источник"
                onClick={() => confirm("Удалить источник?") && del.mutate()}
                icon={<Trash2 className="size-4" />}
              />
            </>
          )
        }
      />
      <div className="space-y-4 px-5 py-4">
        <Field label={`${listLabel} (${n})`} hint={listHint}>
          <Textarea rows={Math.min(14, Math.max(4, n + 1))} value={text} onChange={(e) => setText(e.target.value)} disabled={readOnly} className="font-mono text-[13px]" />
        </Field>
        {s.type === "tenders" && (
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Система" hint="torgi — земельные лоты, zakupki — заказы на работы">
              <Select
                value={(s.config.provider as string) || "torgi"}
                disabled={readOnly}
                onChange={(e) => patch.mutate({ config: { ...s.config, provider: e.target.value } })}
              >
                <option value="torgi">torgi.gov.ru — торги по земле</option>
                <option value="zakupki">zakupki.gov.ru — закупки работ</option>
              </Select>
            </Field>
            <Field label="Коды регионов" hint="Через запятую, например 50,77. Пусто — вся Россия.">
              <Input
                defaultValue={(s.config.regions ?? []).join(",")}
                disabled={readOnly}
                onBlur={(e) =>
                  patch.mutate({
                    config: { ...s.config, regions: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) },
                  })
                }
              />
            </Field>
          </div>
        )}
        {(s.type === "telegram" || s.type === "telegram_chat") && (
          <Field label="Ключевые слова" hint="Необязательно: оставлять только посты с этими словами. По одному в строке.">
            <Textarea rows={3} value={keywords} onChange={(e) => setKeywords(e.target.value)} disabled={readOnly} className="font-mono text-[13px]" />
          </Field>
        )}
      </div>
      {!readOnly && (
        <SaveBar
          loading={patch.isPending}
          error={patch.error}
          onSave={() =>
            patch.mutate({
              config: {
                ...s.config,
                [key]: lines(text),
                ...(s.type === "telegram" || s.type === "telegram_chat" ? { keywords: lines(keywords) } : {}),
              },
            })
          }
        />
      )}
    </Card>
  );
}

function SourceFinder({ projectId, onClose, onAdded }: { projectId: string; onClose: () => void; onAdded: () => void }) {
  const toast = useToast();
  const [kinds, setKinds] = useState<("telegram" | "rss")[]>(["telegram", "rss"]);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const find = useMutation({
    mutationFn: () => api<SourceCandidate[]>(`/projects/${projectId}/discover`, { method: "POST", json: { kinds } }),
    onSuccess: (list) => setPicked(Object.fromEntries(list.map((c) => [c.ref, c.score >= 0.6]))),
    onError: (e) => toast(e instanceof Error ? e.message : "Поиск не удался", "bad"),
  });
  const add = useMutation({
    mutationFn: () =>
      api(`/projects/${projectId}/sources/discovered`, {
        method: "POST",
        json: { candidates: (find.data ?? []).filter((c) => picked[c.ref]) },
      }),
    onSuccess: () => {
      toast("Источники добавлены");
      onAdded();
      onClose();
    },
  });
  const chosen = (find.data ?? []).filter((c) => picked[c.ref]).length;

  return (
    <Modal
      open
      onClose={onClose}
      title="Поиск источников"
      footer={
        <>
          <Button onClick={onClose}>Закрыть</Button>
          <Button variant="primary" disabled={!chosen} loading={add.isPending} onClick={() => add.mutate()}>
            Добавить выбранные ({chosen})
          </Button>
        </>
      }
    >
      <div className="flex flex-wrap items-center gap-3">
        {(["telegram", "rss"] as const).map((k) => (
          <label key={k} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={kinds.includes(k)}
              onChange={(e) => setKinds(e.target.checked ? [...kinds, k] : kinds.filter((x) => x !== k))}
            />
            {k === "telegram" ? "Telegram-каналы" : "Форумы и RSS"}
          </label>
        ))}
        <Button loading={find.isPending} disabled={!kinds.length} onClick={() => find.mutate()} icon={<Radar className="size-4" />}>
          {find.data ? "Искать ещё" : "Искать"}
        </Button>
      </div>
      {find.isPending && (
        <p className="text-sm text-text-2">
          Идёт поиск: модель придумывает запросы, программа проверяет площадки и читает их свежие сообщения. Это занимает
          1–3 минуты.
        </p>
      )}
      <ErrorBox error={find.error || add.error} />
      {find.data?.length === 0 && (
        <p className="text-sm text-text-2">
          Ничего не нашлось. Поисковые движки временами ограничивают запросы — попробуйте ещё раз через несколько минут.
        </p>
      )}
      {!!find.data?.length && (
        <ul className="max-h-[50vh] space-y-2 overflow-y-auto">
          {find.data.map((c) => (
            <li key={c.ref} className="rounded-lg border border-border p-3">
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={!!picked[c.ref]}
                  onChange={(e) => setPicked({ ...picked, [c.ref]: e.target.checked })}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={c.score >= 0.6 ? "good" : c.score >= 0.3 ? "warn" : "neutral"}>
                      {Math.round(c.score * 100)}%
                    </Badge>
                    <Badge>{c.type === "telegram" ? "Telegram" : "RSS"}</Badge>
                    <span className="truncate font-medium">{c.name}</span>
                  </div>
                  <div className="mt-1 text-[13px] text-text-2">{c.reason}</div>
                  <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-xs text-accent hover:underline">
                    {c.url}
                  </a>
                  {!!c.stats.subscribers && <span className="ml-2 text-xs text-text-3">{c.stats.subscribers} подписчиков</span>}
                  {!!c.stats.expected_leads && <span className="ml-2 text-xs text-text-3">лиды: {c.stats.expected_leads}</span>}
                </div>
              </label>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}

function ExamplesTab({ p, onSaved, readOnly }: TabProps) {
  const [items, setItems] = useState<Example[]>(p.examples);
  const save = useSave(p, onSaved);
  const upd = (i: number, patch: Partial<Example>) => setItems(items.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  return (
    <Card>
      <CardHeader
        title="Эталонные примеры"
        subtitle="Показываются модели как образцы разметки. Плюс к ним автоматически добавляются последние лиды с вашей оценкой 👍/👎."
        actions={!readOnly && <Button size="sm" icon={<Plus className="size-4" />} onClick={() => setItems([...items, { text: "", is_fit: true, why: "" }])}>Пример</Button>}
      />
      <div className="divide-y divide-border">
        {items.map((ex, i) => (
          <div key={i} className="grid gap-3 px-5 py-4 md:grid-cols-[1fr_140px_220px_36px]">
            <Textarea rows={2} value={ex.text} disabled={readOnly} onChange={(e) => upd(i, { text: e.target.value })} placeholder="Текст поста" />
            <Select value={ex.is_fit ? "1" : "0"} disabled={readOnly} onChange={(e) => upd(i, { is_fit: e.target.value === "1" })}>
              <option value="1">✓ Лид</option>
              <option value="0">✗ Не лид</option>
            </Select>
            <Input value={ex.why ?? ""} disabled={readOnly} onChange={(e) => upd(i, { why: e.target.value })} placeholder="Почему" />
            {!readOnly && (
              <Button variant="ghost" aria-label="Удалить пример" onClick={() => setItems(items.filter((_, j) => j !== i))} icon={<Trash2 className="size-4" />} />
            )}
          </div>
        ))}
        {!items.length && <p className="px-5 py-8 text-center text-sm text-text-3">Примеров нет</p>}
      </div>
      {!readOnly && (
        <SaveBar loading={save.isPending} error={save.error} onSave={() => save.mutate({ examples: items.filter((x) => x.text.trim()) })} />
      )}
    </Card>
  );
}

const CRON_PRESETS: { label: string; cron: string }[] = [
  { label: "Каждый час", cron: "0 * * * *" },
  { label: "Каждые 3 часа", cron: "0 */3 * * *" },
  { label: "3 раза в день (9, 14, 19)", cron: "0 9,14,19 * * *" },
  { label: "Каждый день в 9:00", cron: "0 9 * * *" },
  { label: "По будням в 9:00", cron: "0 9 * * 1-5" },
];

function ScheduleTab({ p, onSaved, readOnly }: TabProps) {
  const [f, setF] = useState({
    schedule_enabled: p.schedule_enabled,
    schedule_cron: p.schedule_cron || "0 */3 * * *",
    timelimit: p.timelimit,
    max_age_days: p.max_age_days,
    min_score: p.min_score,
    max_leads_per_run: p.max_leads_per_run,
    blocked_hosts: p.blocked_hosts.join("\n"),
    demand_patterns: p.demand_patterns.join("\n"),
    exclude_patterns: p.exclude_patterns.join("\n"),
    is_active: p.is_active,
  });
  const save = useSave(p, onSaved);
  const row = (label: string, hint: string, control: ReactNode) => (
    <div className="grid gap-2 px-5 py-4 md:grid-cols-[1fr_320px] md:items-center">
      <div>
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-text-3">{hint}</div>
      </div>
      <div>{control}</div>
    </div>
  );
  return (
    <Card>
      <CardHeader title="Расписание и фильтры" subtitle={p.next_run_at ? `Следующий запуск: ${fmtDateTime(p.next_run_at)} (UTC-расписание)` : undefined} />
      <div className="divide-y divide-border">
        {row("Запуск по расписанию", "Worker сам запускает поиск; новые лиды приходят в Telegram/webhook", (
          <Switch checked={f.schedule_enabled} disabled={readOnly} onChange={(v) => setF({ ...f, schedule_enabled: v })} label="Расписание" />
        ))}
        {row("Как часто", "Cron-выражение, время в UTC (Москва = UTC+3)", (
          <div className="space-y-2">
            <Select value={CRON_PRESETS.find((c) => c.cron === f.schedule_cron)?.cron ?? ""} disabled={readOnly} onChange={(e) => e.target.value && setF({ ...f, schedule_cron: e.target.value })}>
              <option value="">Своё выражение…</option>
              {CRON_PRESETS.map((c) => (
                <option key={c.cron} value={c.cron}>
                  {c.label}
                </option>
              ))}
            </Select>
            <Input value={f.schedule_cron} disabled={readOnly} onChange={(e) => setF({ ...f, schedule_cron: e.target.value })} className="font-mono" />
          </div>
        ))}
        {row("Свежесть выдачи поиска", "Ограничение по времени для веб-поиска", (
          <Select value={f.timelimit} disabled={readOnly} onChange={(e) => setF({ ...f, timelimit: e.target.value as Project["timelimit"] })}>
            <option value="d">За сутки</option>
            <option value="w">За неделю</option>
            <option value="m">За месяц</option>
            <option value="y">За год</option>
            <option value="">Без ограничения</option>
          </Select>
        ))}
        {row("Максимальный возраст поста, дней", "Старше — отбрасывается до модели (0 = не проверять)", (
          <Input type="number" min={0} value={f.max_age_days} disabled={readOnly} onChange={(e) => setF({ ...f, max_age_days: Number(e.target.value) })} />
        ))}
        {row("Минимальная уверенность модели", "Ниже — не считается лидом", (
          <Input type="number" step={0.05} min={0} max={1} value={f.min_score} disabled={readOnly} onChange={(e) => setF({ ...f, min_score: Number(e.target.value) })} />
        ))}
        {row("Лидов за запуск, максимум", "Защита от лавины при первом запуске", (
          <Input type="number" min={1} value={f.max_leads_per_run} disabled={readOnly} onChange={(e) => setF({ ...f, max_leads_per_run: Number(e.target.value) })} />
        ))}
        {row("Стоп-лист сайтов", "Свой сайт, конкуренты, каталоги — по одному домену в строке", (
          <Textarea rows={5} value={f.blocked_hosts} disabled={readOnly} onChange={(e) => setF({ ...f, blocked_hosts: e.target.value })} className="font-mono text-[13px]" />
        ))}
        {row("Доп. сигналы спроса (regex)", "Фразы, которые пропускают кандидата к модели", (
          <Textarea rows={4} value={f.demand_patterns} disabled={readOnly} onChange={(e) => setF({ ...f, demand_patterns: e.target.value })} className="font-mono text-[13px]" />
        ))}
        {row("Стоп-темы (regex)", "Кандидаты с этими словами не доходят до модели: чужие темы, быт, реклама", (
          <Textarea rows={6} value={f.exclude_patterns} disabled={readOnly} onChange={(e) => setF({ ...f, exclude_patterns: e.target.value })} className="font-mono text-[13px]" />
        ))}
        {row("Проект активен", "Выключенный проект не запускается по расписанию", (
          <Switch checked={f.is_active} disabled={readOnly} onChange={(v) => setF({ ...f, is_active: v })} label="Активен" />
        ))}
      </div>
      {!readOnly && (
        <SaveBar
          loading={save.isPending}
          error={save.error}
          onSave={() =>
            save.mutate({
              ...f,
              blocked_hosts: lines(f.blocked_hosts),
              demand_patterns: lines(f.demand_patterns),
              exclude_patterns: lines(f.exclude_patterns),
            })
          }
        />
      )}
    </Card>
  );
}
