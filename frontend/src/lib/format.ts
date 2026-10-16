import type { LeadStatus, Role, Run } from "../api/types";

const dtf = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const df = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", year: "numeric" });

export const fmtDateTime = (s?: string | null) => (s ? dtf.format(new Date(s)) : "—");
export const fmtDate = (s?: string | null) => (s ? df.format(new Date(s)) : "—");
export const pct = (x: number) => `${Math.round(x * 100)}%`;

export function relTime(s?: string | null): string {
  if (!s) return "—";
  const diff = (Date.now() - new Date(s).getTime()) / 1000;
  if (diff < 60) return "только что";
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} дн назад`;
  return fmtDate(s);
}

export function duration(a?: string | null, b?: string | null): string {
  if (!a) return "—";
  const sec = Math.max(0, ((b ? new Date(b) : new Date()).getTime() - new Date(a).getTime()) / 1000);
  if (sec < 60) return `${Math.round(sec)} с`;
  return `${Math.floor(sec / 60)} мин ${Math.round(sec % 60)} с`;
}

export const LEAD_STATUS: Record<LeadStatus, string> = {
  new: "Новый",
  in_progress: "В работе",
  contacted: "Связались",
  won: "Клиент",
  lost: "Отказ",
  spam: "Мусор",
};

export const RUN_STATUS: Record<Run["status"], string> = {
  queued: "В очереди",
  running: "Идёт",
  succeeded: "Готово",
  failed: "Ошибка",
  cancelled: "Остановлен",
};

export const ROLE: Record<Role, string> = {
  owner: "Владелец",
  admin: "Администратор",
  manager: "Менеджер",
  viewer: "Наблюдатель",
};

export const SOURCE_LABEL: Record<string, string> = {
  vk: "ВКонтакте",
  telegram: "Telegram-каналы",
  telegram_chat: "Telegram-чаты",
  tenders: "Тендеры и торги",
  web_watch: "Наблюдатель за страницами",
  searxng: "Веб (SearXNG)",
  rss: "RSS",
  ddg: "DuckDuckGo",
  legacy: "Пилот",
};

export const DROP_REASON: Record<string, string> = {
  blocked_host: "стоп-лист сайтов",
  listing_page: "страница раздела",
  past_experience: "прошлый опыт",
  no_demand_signal: "нет признаков запроса",
  off_topic: "не наша тема",
  stale: "старые",
};

export const ROLE_RANK: Record<Role, number> = { viewer: 0, manager: 1, admin: 2, owner: 3 };
