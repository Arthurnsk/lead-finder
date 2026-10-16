import clsx from "clsx";
import {
  Building2,
  FolderKanban,
  Inbox,
  LayoutDashboard,
  LogOut,
  Moon,
  PlayCircle,
  Settings,
  Sun,
  Target,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";
import { ROLE } from "../lib/format";

const THEME_KEY = "lf.theme";

function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark" | null>(() => {
    try {
      return (localStorage.getItem(THEME_KEY) as "light" | "dark" | null) ?? null;
    } catch {
      return null;
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme) root.setAttribute("data-theme", theme);
    else root.removeAttribute("data-theme");
    try {
      if (theme) localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  const isDark = theme ? theme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  return { isDark, toggle: () => setTheme(isDark ? "light" : "dark") };
}

const NAV = [
  { to: "/", label: "Обзор", icon: LayoutDashboard, end: true },
  { to: "/leads", label: "Лиды", icon: Inbox },
  { to: "/projects", label: "Проекты", icon: FolderKanban },
  { to: "/runs", label: "Запуски", icon: PlayCircle },
  { to: "/settings", label: "Настройки", icon: Settings },
];

export default function Layout() {
  const { me, org, role, switchOrg, logout } = useAuth();
  const { isDark, toggle } = useTheme();

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-surface md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <div className="flex size-8 items-center justify-center rounded-lg bg-accent text-white">
            <Target className="size-4.5" />
          </div>
          <div className="leading-tight">
            <div className="text-[15px] font-semibold">Lead Finder</div>
            <div className="text-xs text-text-3">свежий спрос</div>
          </div>
        </div>

        {me && me.memberships.length > 0 && (
          <div className="px-3 pb-3">
            <label className="sr-only" htmlFor="org">Организация</label>
            <select
              id="org"
              value={org?.id ?? ""}
              onChange={(e) => switchOrg(e.target.value)}
              className="h-9 w-full rounded-lg border border-border bg-surface-2 px-2.5 text-sm font-medium"
            >
              {me.memberships.map((m) => (
                <option key={m.organization.id} value={m.organization.id}>
                  {m.organization.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors",
                  isActive ? "bg-accent-soft text-accent" : "text-text-2 hover:bg-surface-2 hover:text-text",
                )
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
          {me?.is_superadmin && (
            <NavLink
              to="/admin"
              className={({ isActive }) =>
                clsx(
                  "mt-4 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium",
                  isActive ? "bg-accent-soft text-accent" : "text-text-2 hover:bg-surface-2 hover:text-text",
                )
              }
            >
              <Building2 className="size-4" />
              Клиенты SaaS
            </NavLink>
          )}
        </nav>

        <div className="border-t border-border p-3">
          <div className="mb-2 px-2">
            <div className="truncate text-sm font-medium">{me?.full_name || me?.email}</div>
            <div className="text-xs text-text-3">
              {me?.is_superadmin ? "Суперадмин" : role ? ROLE[role] : ""}
            </div>
          </div>
          <div className="flex gap-1">
            <button
              onClick={toggle}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg py-1.5 text-xs text-text-2 hover:bg-surface-2"
              aria-label="Сменить тему"
            >
              {isDark ? <Sun className="size-3.5" /> : <Moon className="size-3.5" />}
              {isDark ? "Светлая" : "Тёмная"}
            </button>
            <button
              onClick={logout}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg py-1.5 text-xs text-text-2 hover:bg-surface-2"
            >
              <LogOut className="size-3.5" />
              Выйти
            </button>
          </div>
        </div>
      </aside>

      {/* mobile top bar */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-1 overflow-x-auto border-b border-border bg-surface px-3 py-2 md:hidden">
          {NAV.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx("whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm", isActive ? "bg-accent-soft text-accent" : "text-text-2")
              }
            >
              {label}
            </NavLink>
          ))}
        </div>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8 md:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
