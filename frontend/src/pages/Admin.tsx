import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api/client";
import type { Org } from "../api/types";
import { useAuth } from "../auth";
import { Badge, Button, Card, CardHeader, ErrorBox, Field, Input, Loading, Modal, PageHeader, Switch, useToast } from "../components/ui";

export default function AdminPage() {
  const { me, refetch } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", slug: "", owner_email: "", owner_name: "", owner_password: "" });
  const orgs = useQuery({ queryKey: ["admin-orgs"], queryFn: () => api<Org[]>("/admin/orgs"), enabled: !!me?.is_superadmin });
  const create = useMutation({
    mutationFn: () => api<Org>("/admin/orgs", { method: "POST", json: { ...f, owner_password: f.owner_password || null } }),
    onSuccess: (o) => {
      setOpen(false);
      setF({ name: "", slug: "", owner_email: "", owner_name: "", owner_password: "" });
      qc.invalidateQueries({ queryKey: ["admin-orgs"] });
      refetch();
      toast(`Клиент «${o.name}» создан`);
    },
  });
  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => api(`/admin/orgs/${id}?is_active=${active}`, { method: "PATCH" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-orgs"] }),
  });

  if (!me?.is_superadmin) return <Navigate to="/" replace />;
  return (
    <>
      <PageHeader
        title="Клиенты SaaS"
        subtitle="Каждый клиент — отдельная организация: свои проекты, лиды, пользователи и секреты"
        actions={<Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>Новый клиент</Button>}
      />
      <Card>
        <CardHeader title="Организации" />
        {orgs.isLoading ? (
          <Loading />
        ) : (
          <ul className="divide-y divide-border">
            {orgs.data?.map((o) => (
              <li key={o.id} className="flex items-center gap-3 px-5 py-3">
                <div className="flex-1">
                  <div className="font-medium">{o.name}</div>
                  <div className="text-[13px] text-text-3">{o.slug}</div>
                </div>
                <Badge tone={o.is_active ? "good" : "warn"}>{o.is_active ? "Активна" : "Отключена"}</Badge>
                <Switch checked={o.is_active} onChange={(v) => toggle.mutate({ id: o.id, active: v })} label="Активна" />
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Новый клиент"
        footer={
          <>
            <Button onClick={() => setOpen(false)}>Отмена</Button>
            <Button variant="primary" loading={create.isPending} onClick={() => create.mutate()}>
              Создать
            </Button>
          </>
        }
      >
        <Field label="Название компании">
          <Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </Field>
        <Field label="Код (латиница, дефис)">
          <Input value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") })} />
        </Field>
        <Field label="Email владельца">
          <Input type="email" value={f.owner_email} onChange={(e) => setF({ ...f, owner_email: e.target.value })} />
        </Field>
        <Field label="Имя владельца">
          <Input value={f.owner_name} onChange={(e) => setF({ ...f, owner_name: e.target.value })} />
        </Field>
        <Field label="Временный пароль" hint="Если пользователь уже существует — оставьте пустым">
          <Input value={f.owner_password} onChange={(e) => setF({ ...f, owner_password: e.target.value })} />
        </Field>
        <ErrorBox error={create.error} />
      </Modal>
    </>
  );
}
