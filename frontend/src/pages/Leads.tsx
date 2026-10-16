import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Download, ExternalLink, Inbox, Search, ThumbsDown, ThumbsUp, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { api, apiUrl, qs } from "../api/client";
import type { Lead, LeadStatus, Member, Project } from "../api/types";
import { useAuth } from "../auth";
import { FeedbackIcon, LeadStatusBadge, ScorePill } from "../components/status";
import {
  Badge,
  Button,
  Card,
  Drawer,
  EmptyState,
  ErrorBox,
  Field,
  Input,
  Loading,
  PageHeader,
  Select,
  Tabs,
  Textarea,
  useToast,
} from "../components/ui";
import { LEAD_STATUS, SOURCE_LABEL, fmtDate, fmtDateTime, relTime } from "../lib/format";

type StatusTab = "open" | LeadStatus | "all";
const STATUS_TABS: { id: StatusTab; label: string }[] = [
  { id: "open", label: "Входящие" },
  { id: "in_progress", label: "В работе" },
  { id: "contacted", label: "Связались" },
  { id: "won", label: "Клиенты" },
  { id: "lost", label: "Отказ" },
  { id: "spam", label: "Мусор" },
  { id: "all", label: "Все" },
];
const PAGE = 50;

function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function LeadsPage() {
  const [tab, setTab] = useState<StatusTab>("open");
  const [search, setSearch] = useState("");
  const [projectId, setProjectId] = useState("");
  const [source, setSource] = useState("");
  const [feedback, setFeedback] = useState<string>("any");
  const [sort, setSort] = useState("found_desc");
  const [page, setPage] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const q = useDebounced(search);

  const params = {
    project_id: projectId,
    status: tab === "open" ? ["new"] : tab === "all" ? undefined : [tab],
    source,
    feedback: feedback === "any" ? undefined : feedback,
    q,
  };
  useEffect(() => setPage(0), [tab, projectId, source, feedback, q, sort]);

  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const leads = useQuery({
    queryKey: ["leads", params, sort, page],
    queryFn: () => api<{ items: Lead[]; total: number }>(`/leads${qs({ ...params, sort, offset: page * PAGE, limit: PAGE })}`),
    placeholderData: keepPreviousData,
  });
  const projectName = (id: string) => projects.data?.find((p) => p.id === id)?.name ?? "";
  const total = leads.data?.total ?? 0;

  return (
    <>
      <PageHeader
        title="Лиды"
        subtitle="Свежие запросы людей, отобранные моделью. Разберите входящие и отметьте качество 👍/👎 — модель учится на ваших оценках."
        actions={
          <a href={apiUrl("/leads/export.csv", params)} download>
            <Button icon={<Download className="size-4" />}>CSV</Button>
          </a>
        }
      />

      <Card>
        <div className="px-4 pt-2">
          <Tabs tabs={STATUS_TABS} value={tab} onChange={setTab} />
        </div>
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <div className="relative min-w-56 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-text-3" />
            <Input placeholder="Поиск по тексту" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-8" />
          </div>
          <Select value={projectId} onChange={(e) => setProjectId(e.target.value)} className="w-44">
            <option value="">Все проекты</option>
            {projects.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
          <Select value={source} onChange={(e) => setSource(e.target.value)} className="w-40">
            <option value="">Все источники</option>
            {Object.entries(SOURCE_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </Select>
          <Select value={feedback} onChange={(e) => setFeedback(e.target.value)} className="w-36">
            <option value="any">Любая оценка</option>
            <option value="">Без оценки</option>
            <option value="good">👍 Хорошие</option>
            <option value="bad">👎 Плохие</option>
          </Select>
          <Select value={sort} onChange={(e) => setSort(e.target.value)} className="w-44">
            <option value="found_desc">Сначала новые</option>
            <option value="score_desc">По уверенности</option>
            <option value="posted_desc">По дате поста</option>
          </Select>
        </div>

        <ErrorBox error={leads.error} />
        {leads.isLoading ? (
          <Loading />
        ) : !leads.data?.items.length ? (
          <EmptyState icon={<Inbox className="size-8" />} title="Здесь пусто">
            {tab === "open" ? "Все входящие разобраны. Новые лиды появятся после следующего запуска." : "Нет лидов с такими фильтрами."}
          </EmptyState>
        ) : (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[860px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-text-3">
                  <th className="w-16 px-4 py-2.5">Score</th>
                  <th className="px-2 py-2.5">Запрос</th>
                  <th className="w-36 px-2 py-2.5">Источник</th>
                  <th className="w-28 px-2 py-2.5">Пост</th>
                  <th className="w-28 px-2 py-2.5">Найден</th>
                  <th className="w-32 px-4 py-2.5">Статус</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {leads.data.items.map((l) => (
                  <tr
                    key={l.id}
                    onClick={() => setOpenId(l.id)}
                    className={clsx("cursor-pointer hover:bg-surface-2", openId === l.id && "bg-accent-soft/50")}
                  >
                    <td className="px-4 py-3 align-top">
                      <ScorePill score={l.score} />
                    </td>
                    <td className="px-2 py-3 align-top">
                      <div className="flex items-center gap-1.5 font-medium">
                        <span className="line-clamp-1">{l.interest_signal || l.title}</span>
                        <FeedbackIcon feedback={l.feedback} />
                      </div>
                      <div className="mt-0.5 line-clamp-1 text-[13px] text-text-2">{l.text || l.title}</div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {l.segment && <Badge>{l.segment}</Badge>}
                        {!projectId && (projects.data?.length ?? 0) > 1 && <Badge tone="accent">{projectName(l.project_id)}</Badge>}
                      </div>
                    </td>
                    <td className="px-2 py-3 align-top text-[13px]">
                      <div>{SOURCE_LABEL[l.source] ?? l.source}</div>
                      <div className="text-text-3">{l.platform}</div>
                    </td>
                    <td className="px-2 py-3 align-top text-[13px] text-text-2">{l.posted_at ? fmtDate(l.posted_at) : "—"}</td>
                    <td className="px-2 py-3 align-top text-[13px] text-text-2">{relTime(l.found_at)}</td>
                    <td className="px-4 py-3 align-top">
                      <LeadStatusBadge status={l.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {total > PAGE && (
          <div className="flex items-center justify-between border-t border-border px-4 py-3 text-sm text-text-2">
            <span>
              {page * PAGE + 1}–{Math.min(total, (page + 1) * PAGE)} из {total}
            </span>
            <div className="flex gap-2">
              <Button size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                Назад
              </Button>
              <Button size="sm" disabled={(page + 1) * PAGE >= total} onClick={() => setPage((p) => p + 1)}>
                Дальше
              </Button>
            </div>
          </div>
        )}
      </Card>

      <LeadDrawer id={openId} onClose={() => setOpenId(null)} projectName={projectName} />
    </>
  );
}

function LeadDrawer({ id, onClose, projectName }: { id: string | null; onClose: () => void; projectName: (id: string) => string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useAuth();
  const editable = can("manager");
  const lead = useQuery({ queryKey: ["lead", id], queryFn: () => api<Lead>(`/leads/${id}`), enabled: !!id });
  const members = useQuery({ queryKey: ["members"], queryFn: () => api<Member[]>("/members"), enabled: !!id });
  const [notes, setNotes] = useState("");
  useEffect(() => setNotes(lead.data?.notes ?? ""), [lead.data?.id, lead.data?.notes]);

  const update = useMutation({
    mutationFn: (patch: Partial<Lead>) => api<Lead>(`/leads/${id}`, { method: "PATCH", json: patch }),
    onSuccess: (data) => {
      qc.setQueryData(["lead", id], data);
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Ошибка", "bad"),
  });

  const l = lead.data;
  return (
    <Drawer
      open={!!id}
      onClose={onClose}
      title={
        l ? (
          <div>
            <div className="flex items-center gap-2">
              <ScorePill score={l.score} />
              <LeadStatusBadge status={l.status} />
              <span className="text-xs text-text-3">{projectName(l.project_id)}</span>
            </div>
            <h2 className="mt-2 text-base font-semibold leading-snug">{l.interest_signal || l.title}</h2>
          </div>
        ) : (
          "Лид"
        )
      }
      footer={
        l && (
          <a href={l.url} target="_blank" rel="noopener noreferrer" className="block">
            <Button variant="primary" className="w-full" icon={<ExternalLink className="size-4" />}>
              Открыть источник и ответить
            </Button>
          </a>
        )
      }
    >
      {!l ? (
        <Loading />
      ) : (
        <div className="space-y-5">
          <section>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-3">Почему это лид</h3>
            <p className="text-sm">{l.reason || "—"}</p>
            {l.segment && <Badge className="mt-2">{l.segment}</Badge>}
          </section>

          <section>
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-3">Текст</h3>
            {l.title && l.title !== l.text && <p className="mb-1 text-sm font-medium">{l.title}</p>}
            <p className="whitespace-pre-line rounded-lg bg-surface-2 p-3 text-sm leading-relaxed">{l.text || "—"}</p>
          </section>

          <section className="rounded-lg border border-border p-3">
            <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-text-3">Как связаться</h3>
            {(() => {
              const o = (l.contacts?.outreach ?? {}) as Record<string, string>;
              const emails = (l.contacts?.emails as string[] | undefined) ?? [];
              const phones = (l.contacts?.phones as string[] | undefined) ?? [];
              return (
                <div className="space-y-2 text-sm">
                  <p>{o.how || "Открыть источник и ответить там"}</p>
                  {(o.author || l.display_name) && (
                    <p className="text-text-2">
                      Автор: <span className="font-medium text-text">{o.author || l.display_name}</span>
                    </p>
                  )}
                  {(emails.length > 0 || phones.length > 0) && (
                    <p className="text-text-2">Контакты: {[...phones, ...emails].join(", ")}</p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <a href={o.action_url || l.url} target="_blank" rel="noopener noreferrer">
                      <Button size="sm" variant="primary" icon={<ExternalLink className="size-3.5" />}>
                        Открыть и ответить
                      </Button>
                    </a>
                    {o.profile_url && (
                      <a href={o.profile_url} target="_blank" rel="noopener noreferrer">
                        <Button size="sm" icon={<UserRound className="size-3.5" />}>
                          Профиль автора
                        </Button>
                      </a>
                    )}
                  </div>
                </div>
              );
            })()}
          </section>

          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-text-3">Источник</dt>
            <dd>
              {SOURCE_LABEL[l.source] ?? l.source} · {l.platform}
            </dd>
            <dt className="text-text-3">Автор</dt>
            <dd>{l.display_name || l.contact_hint || "—"}</dd>
            <dt className="text-text-3">Дата поста</dt>
            <dd>{fmtDate(l.posted_at)}</dd>
            <dt className="text-text-3">Найден</dt>
            <dd>{fmtDateTime(l.found_at)}</dd>
            <dt className="text-text-3">Запрос</dt>
            <dd className="break-words text-text-2">{l.query || "—"}</dd>
          </dl>

          <section className="space-y-3 border-t border-border pt-4">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Качество лида:</span>
              <Button
                size="sm"
                variant={l.feedback === "good" ? "primary" : "secondary"}
                disabled={!editable}
                onClick={() => update.mutate({ feedback: l.feedback === "good" ? "" : "good" })}
                icon={<ThumbsUp className="size-3.5" />}
              >
                Хороший
              </Button>
              <Button
                size="sm"
                variant={l.feedback === "bad" ? "danger" : "secondary"}
                disabled={!editable}
                onClick={() => update.mutate({ feedback: l.feedback === "bad" ? "" : "bad" })}
                icon={<ThumbsDown className="size-3.5" />}
              >
                Мимо
              </Button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Статус">
                <Select
                  value={l.status}
                  disabled={!editable}
                  onChange={(e) => update.mutate({ status: e.target.value as LeadStatus })}
                >
                  {Object.entries(LEAD_STATUS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Ответственный">
                <Select
                  value={l.assignee_id ?? ""}
                  disabled={!editable}
                  onChange={(e) => update.mutate({ assignee_id: e.target.value || null })}
                >
                  <option value="">—</option>
                  {members.data?.map((m) => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.full_name || m.email}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <Field label="Заметки">
              <Textarea
                rows={3}
                value={notes}
                disabled={!editable}
                placeholder="Что ответили, договорённости…"
                onChange={(e) => setNotes(e.target.value)}
                onBlur={() => notes !== l.notes && update.mutate({ notes })}
              />
            </Field>
            <ErrorBox error={update.error} />
          </section>
        </div>
      )}
    </Drawer>
  );
}
