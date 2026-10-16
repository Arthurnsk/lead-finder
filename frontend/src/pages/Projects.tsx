import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, FolderKanban, Plus, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Project } from "../api/types";
import { useAuth } from "../auth";
import { Badge, Button, Card, EmptyState, ErrorBox, Field, Input, Loading, Modal, PageHeader, useToast } from "../components/ui";
import { SOURCE_LABEL, fmtDateTime } from "../lib/format";

export default function ProjectsPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const q = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });

  const create = useMutation({
    mutationFn: () => api<Project>("/projects", { method: "POST", json: { name, slug } }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      nav(`/projects/${p.id}`);
    },
  });

  const importYaml = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api<Project>("/projects/import", { method: "POST", body: fd });
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      toast(`Проект «${p.name}» импортирован`);
      nav(`/projects/${p.id}`);
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Ошибка импорта", "bad"),
  });

  return (
    <>
      <PageHeader
        title="Проекты"
        subtitle="Проект — это ниша: кого ищем, где ищем и как часто"
        actions={
          can("admin") && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".yaml,.yml"
                hidden
                onChange={(e) => e.target.files?.[0] && importYaml.mutate(e.target.files[0])}
              />
              <Button icon={<Upload className="size-4" />} loading={importYaml.isPending} onClick={() => fileRef.current?.click()}>
                Импорт YAML
              </Button>
              <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>
                Новый проект
              </Button>
            </>
          )
        }
      />
      <ErrorBox error={q.error} />
      {q.isLoading ? (
        <Loading />
      ) : !q.data?.length ? (
        <Card>
          <EmptyState icon={<FolderKanban className="size-8" />} title="Проектов пока нет">
            Создайте проект или импортируйте шаблон ниши в YAML.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {q.data.map((p) => (
            <Link key={p.id} to={`/projects/${p.id}`} className="card block p-5 transition-shadow hover:shadow-md">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-semibold">{p.name}</div>
                  <div className="text-[13px] text-text-3">{p.site || p.slug}</div>
                </div>
                {!p.is_active && <Badge tone="warn">Пауза</Badge>}
              </div>
              <div className="mt-3 flex flex-wrap gap-1">
                {p.sources.map((s) => (
                  <Badge key={s.id} tone={s.enabled ? "accent" : "neutral"}>
                    {SOURCE_LABEL[s.type] ?? s.type}
                  </Badge>
                ))}
              </div>
              <div className="mt-4 flex items-center gap-1.5 text-xs text-text-3">
                <CalendarClock className="size-3.5" />
                {p.schedule_enabled && p.next_run_at ? `Следующий запуск ${fmtDateTime(p.next_run_at)}` : "Только ручной запуск"}
              </div>
            </Link>
          ))}
        </div>
      )}

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title="Новый проект"
        footer={
          <>
            <Button onClick={() => setCreating(false)}>Отмена</Button>
            <Button variant="primary" loading={create.isPending} onClick={() => create.mutate()} disabled={!name || !slug}>
              Создать
            </Button>
          </>
        }
      >
        <Field label="Название">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Например: Юристы по земле, Москва" />
        </Field>
        <Field label="Код (латиница)" hint="Используется в экспорте и API; менять нельзя">
          <Input
            value={slug}
            onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
            placeholder="land-lawyers"
          />
        </Field>
        <ErrorBox error={create.error} />
      </Modal>
    </>
  );
}
