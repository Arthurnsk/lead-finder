import { useQuery } from "@tanstack/react-query";
import { PlayCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Project, Run } from "../api/types";
import { RunStatusBadge } from "../components/status";
import { Card, EmptyState, ErrorBox, Loading, PageHeader } from "../components/ui";
import { duration, fmtDateTime } from "../lib/format";

export default function RunsPage() {
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("/runs?limit=100"),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "running" || r.status === "queued") ? 3000 : 15000),
  });
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const name = (id: string) => projects.data?.find((p) => p.id === id)?.name ?? "—";

  return (
    <>
      <PageHeader title="Запуски" subtitle="История поиска: вручную и по расписанию" />
      <ErrorBox error={runs.error} />
      <Card>
        {runs.isLoading ? (
          <Loading />
        ) : !runs.data?.length ? (
          <EmptyState icon={<PlayCircle className="size-8" />} title="Запусков ещё не было">
            Откройте проект и нажмите «Запустить поиск».
          </EmptyState>
        ) : (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-text-3">
                  <th className="px-5 py-2.5">Статус</th>
                  <th className="px-2 py-2.5">Проект</th>
                  <th className="px-2 py-2.5">Начат</th>
                  <th className="px-2 py-2.5">Длительность</th>
                  <th className="px-2 py-2.5 text-right">Проверено</th>
                  <th className="px-5 py-2.5 text-right">Лидов</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {runs.data.map((r) => (
                  <tr key={r.id} className="hover:bg-surface-2">
                    <td className="px-5 py-3">
                      <Link to={`/runs/${r.id}`} className="block">
                        <RunStatusBadge status={r.status} />
                      </Link>
                    </td>
                    <td className="px-2 py-3">
                      <Link to={`/runs/${r.id}`} className="font-medium hover:underline">
                        {name(r.project_id)}
                      </Link>
                      <div className="text-xs text-text-3">{r.trigger === "schedule" ? "по расписанию" : "вручную"}</div>
                    </td>
                    <td className="px-2 py-3 text-text-2">{fmtDateTime(r.started_at ?? r.created_at)}</td>
                    <td className="px-2 py-3 text-text-2">{duration(r.started_at, r.finished_at)}</td>
                    <td className="px-2 py-3 text-right tabular-nums">{r.stats.evaluated ?? 0}</td>
                    <td className="px-5 py-3 text-right font-semibold tabular-nums">{r.stats.leads ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
