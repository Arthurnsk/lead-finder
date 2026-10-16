import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";
import { api, getActiveOrg, setActiveOrg, setUnauthorizedHandler } from "./api/client";
import type { Me, Org, Role } from "./api/types";
import { ROLE_RANK } from "./lib/format";

interface AuthState {
  me: Me | null;
  loading: boolean;
  org: Org | null;
  role: Role | null;
  switchOrg: (id: string) => void;
  can: (min: Role) => boolean;
  logout: () => Promise<void>;
  refetch: () => void;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const meQ = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Me>("/auth/me").catch(() => null),
    staleTime: 60_000,
  });
  const me = meQ.data ?? null;

  useEffect(() => {
    setUnauthorizedHandler(() => qc.setQueryData(["me"], null));
  }, [qc]);

  const membership = useMemo(() => {
    if (!me) return null;
    const active = getActiveOrg();
    return me.memberships.find((m) => m.organization.id === active) ?? me.memberships[0] ?? null;
  }, [me]);

  useEffect(() => {
    if (membership && getActiveOrg() !== membership.organization.id) setActiveOrg(membership.organization.id);
  }, [membership]);

  const switchOrg = useCallback(
    (id: string) => {
      setActiveOrg(id);
      qc.clear(); // every cached query is tenant-scoped
      qc.invalidateQueries();
    },
    [qc],
  );

  const logout = useCallback(async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => {});
    setActiveOrg(null);
    qc.clear();
    qc.setQueryData(["me"], null);
  }, [qc]);

  const role = me?.is_superadmin ? "owner" : (membership?.role ?? null);
  const value: AuthState = {
    me,
    loading: meQ.isLoading,
    org: membership?.organization ?? null,
    role,
    switchOrg,
    can: (min) => !!role && ROLE_RANK[role] >= ROLE_RANK[min],
    logout,
    refetch: () => meQ.refetch(),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
