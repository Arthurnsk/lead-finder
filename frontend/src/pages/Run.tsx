import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Inbox, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, apiUrl } from "../api/client";
import type { Project, Run, RunEvent } from "../api/types";
import { useAuth } from "../auth";
import { RunStatusBadge } from "../components/status";
import { Button, Card, CardHeader, ErrorBox, Loading, PageHeader } from "../components/ui";
import { DROP_REASON, SOURCE_LABEL, duration, fmtDateTime } from "../lib/format";

const LEVEL_STYLE: Record<RunEvent["level"], string> = {
  info: "text-text-2",
  lead: "text-good font-medium",
  warn: "text-warn",
  error: "text-bad font-medium",
};

export default function RunPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { can } = useAuth();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [live, setLive] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  const run = useQuery({ queryKey: ["run", id], queryFn: () => api<Run>(`/runs/${id}`) });
  const project = useQuery({
    queryKey: ["project", run.data?.project_id],
    queryFn: () => api<Project>(`/projects/${run.data!.project_id}`),
    enabled: !!run.data,
  });

  useEffect(() => {
    if (!id) return;
    setEvents([]);
    const es = new EventSource(apiUrl(`/runs/${id}/stream`));
    setLive(true);
    es.addEventListener("log", (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as RunEvent;
      setEvents((prev) => (prev.some((x) => x.id === ev.id) ? prev : [...prev, ev]));
    });
    es.addEventListener("done", () => {
      es.close();
      setLive(false);
      qc.invalidateQueries({ queryKey: ["run", id] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["leads"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    });
    es.onerror = () => {
      // Browser reconnects automatically (Last-Event-ID); status poll below keeps the header fresh.
      qc.invalidateQueries({ queryKey: ["run", id] });
    };
    return () => es.close();
  }, [id, qc]);

  useEffect(() => {
    if (stick.current && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [events]);

  const cancel = useMutation({
    mutationFn: () => api<Run>(`/runs/${id}/cancel`, { method: "POST" }),
    onSuccess: (r) => qc.setQueryData(["run", id], r),
  });

  if (run.isLoading) return <Loading />;
  if (!run.data) return <ErrorBox error={run.error ?? "Запуск не найден"} />;
  const r = run.data;
  const active = r.status === "running" || r.status === "queued";
  const s = r.stats;
  const dropped = Object.entries(s.dropped ?? {});

  return (
    <>
      <div className="mb-2 text-sm text-text-3">
        <Link to="/runs" className="hover:text-text">
          Запуски
        </Link>{" "}
        / {fmtDateTime(r.created_at)}
      </div>
      <PageHeader
        title={project.data?.name ?? "Запуск"}
        subtitle={
          <span className="flex items-center gap-2">
            <RunStatusBadge status={r.status} />
            {r.trigger === "schedule" ? "по расписанию" : "вручную"} · {duration(r.started_at, r.finished_at)}
          </span>
        }
        actions={
          <>
            {active && can("manager") && (
              <Button variant="danger" icon={<Square className="size-4" />} loading={cancel.isPending} onClick={() => cancel.mutate()}>
                Остановить
              </Button>
            )}
            {(s.leads ?? 0) > 0 && (
              <Link to="/leads">
                <Button variant="primary" icon={<Inbox className="size-4" />}>
                  Лиды ({s.leads})
                </Button>
              </Link>
            )}
          </>
        }
      />
      {r.error && (
        <div className="mb-4">
          <ErrorBox error={r.error} />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        <Card className="flex min-h-[420px] flex-col">
          <CardHeader
            title="Журнал"
            actions={
              live && (
                <span className="flex items-center gap-1.5 text-xs text-good">
                  <span className="size-2 animate-pulse rounded-full bg-good" /> в реальном времени
                </span>
              )
            }
          />
          <div
            ref={logRef}
            onScroll={(e) => {
              const el = e.currentTarget;
              stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
            }}
            className="scroll-thin h-[560px] overflow-y-auto px-5 py-3 font-mono text-[12.5px] leading-relaxed"
          >
            {events.length === 0 && <p className="text-text-3">{active ? "Ожидание worker…" : "Событий нет"}</p>}
            {events.map((e) => (
              <div key={e.id} className={clsx("whitespace-pre-wrap break-words", LEVEL_STYLE[e.level])}>
                <span className="mr-2 text-text-3">{new Date(e.ts).toLocaleTimeString("ru-RU")}</span>
                {e.message}
              </div>
            ))}
          </div>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Итоги" />
            <dl className="space-y-2 px-5 py-4 text-sm">
              {[
                ["Кандидатов из источников", s.candidates],
                ["Уже видели раньше", s.skipped_seen],
                ["Оценено моделью", s.evaluated],
                ["Отклонено моделью", s.rejected],
                ["Лидов", s.leads],
                ["Ошибок источников", s.source_errors],
                ["Ошибок модели", s.llm_errors],
              ].map(([k, v]) => (
                <div key={k as string} className="flex justify-between">
                  <dt className="text-text-2">{k}</dt>
                  <dd className="font-medium tabular-nums">{v ?? 0}</dd>
                </div>
              ))}
            </dl>
          </Card>
          {dropped.length > 0 && (
            <Card>
              <CardHeader title="Отсеяно фильтрами" subtitle="До модели — экономит время" />
              <dl className="space-y-2 px-5 py-4 text-sm">
                {dropped.map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <dt className="text-text-2">{DROP_REASON[k] ?? k}</dt>
                    <dd className="font-medium tabular-nums">{v}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          )}
          {Object.keys(s.leads_by_source ?? {}).length > 0 && (
            <Card>
              <CardHeader title="Лиды по источникам" />
              <dl className="space-y-2 px-5 py-4 text-sm">
                {Object.entries(s.leads_by_source ?? {}).map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <dt className="text-text-2">{SOURCE_LABEL[k] ?? k}</dt>
                    <dd className="font-medium tabular-nums">{v}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
