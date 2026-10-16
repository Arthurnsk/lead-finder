import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Inbox } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, qs } from "../api/client";
import type { Dashboard, Project } from "../api/types";
import { CategoryBars, DailyBars } from "../components/charts";
import { RunStatusBadge } from "../components/status";
import { Card, CardHeader, EmptyState, ErrorBox, Loading, PageHeader, Select } from "../components/ui";
import { LEAD_STATUS, SOURCE_LABEL, relTime } from "../lib/format";

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card className="px-5 py-4">
      <div className="text-[13px] text-text-2">{label}</div>
      <div className="mt-1 text-3xl font-semibold tabular-nums tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-xs text-text-3">{hint}</div>}
    </Card>
  );
}

export default function DashboardPage() {
  const [days, setDays] = useState(30);
  const [projectId, setProjectId] = useState("");
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const q = useQuery({
    queryKey: ["dashboard", days, projectId],
    queryFn: () => api<Dashboard>(`/dashboard${qs({ days, project_id: projectId })}`),
    refetchInterval: 30_000,
  });
  const d = q.data;

  return (
    <>
      <PageHeader
        title="Обзор"
        subtitle="Сколько свежего спроса нашлось и насколько он качественный"
        actions={
          <>
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)} className="w-52">
              <option value="">Все проекты</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
            <Select value={days} onChange={(e) => setDays(Number(e.target.value))} className="w-36">
              <option value={7}>7 дней</option>
              <option value={30}>30 дней</option>
              <option value={90}>90 дней</option>
            </Select>
          </>
        }
      />
      <ErrorBox error={q.error} />
      {q.isLoading || !d ? (
        <Loading />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Лидов за период" value={d.total} />
            <Stat label="Новые, не разобраны" value={d.by_status.new ?? 0} hint="статус «Новый»" />
            <Stat
              label="Точность по оценкам"
              value={d.feedback.precision === null ? "—" : `${Math.round(d.feedback.precision * 100)}%`}
              hint={`👍 ${d.feedback.good} · 👎 ${d.feedback.bad} · без оценки ${d.feedback.unrated}`}
            />
            <Stat label="Стали клиентами" value={d.by_status.won ?? 0} hint="статус «Клиент»" />
          </div>

          <Card>
            <CardHeader title="Лиды по дням" subtitle={`Последние ${d.days} дней`} />
            <div className="px-5 py-4">
              {d.total ? (
                <DailyBars data={d.per_day} days={d.days} />
              ) : (
                <EmptyState icon={<Inbox className="size-8" />} title="Пока пусто">
                  Запустите поиск в проекте — найденные лиды появятся здесь.
                </EmptyState>
              )}
            </div>
          </Card>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card>
              <CardHeader title="По источникам" />
              <div className="px-5 py-4">
                <CategoryBars data={d.by_source} labels={SOURCE_LABEL} />
              </div>
            </Card>
            <Card>
              <CardHeader title="По статусам" />
              <div className="px-5 py-4">
                <CategoryBars data={d.by_status} labels={LEAD_STATUS} />
              </div>
            </Card>
            <Card>
              <CardHeader
                title="Последние запуски"
                actions={
                  <Link to="/runs" className="flex items-center gap-1 text-[13px] text-accent hover:underline">
                    Все <ArrowRight className="size-3.5" />
                  </Link>
                }
              />
              <ul className="divide-y divide-border">
                {d.last_runs.length === 0 && <li className="px-5 py-6 text-center text-sm text-text-3">Запусков не было</li>}
                {d.last_runs.map((r) => (
                  <li key={r.id}>
                    <Link to={`/runs/${r.id}`} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-2">
                      <div>
                        <RunStatusBadge status={r.status} />
                        <div className="mt-1 text-xs text-text-3">
                          {relTime(r.created_at)} · {r.trigger === "schedule" ? "по расписанию" : "вручную"}
                        </div>
                      </div>
                      <div className="text-right text-sm font-medium tabular-nums">{r.leads} лидов</div>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
