import { useQueryClient } from "@tanstack/react-query";
import { Target } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Me } from "../api/types";
import { useAuth } from "../auth";
import { Button, ErrorBox, Field, Input } from "../components/ui";

export default function LoginPage() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const nav = useNavigate();
  const loc = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (me) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const data = await api<Me>("/auth/login", { method: "POST", json: { email, password } });
      qc.setQueryData(["me"], data);
      nav((loc.state as { from?: string } | null)?.from || "/", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-3 flex size-11 items-center justify-center rounded-xl bg-accent text-white">
            <Target className="size-5" />
          </div>
          <h1 className="text-xl font-semibold">Lead Finder</h1>
          <p className="mt-1 text-sm text-text-2">Свежий спрос из соцсетей, форумов и веба</p>
        </div>
        <form onSubmit={submit} className="card space-y-4 p-6">
          <Field label="Email">
            <Input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Пароль">
            <Input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <ErrorBox error={error} />
          <Button type="submit" variant="primary" className="w-full" loading={busy}>
            Войти
          </Button>
        </form>
      </div>
    </div>
  );
}
