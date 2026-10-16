import { useMemo, useState } from "react";

/** Daily bar chart: one series (no legend), thin bars with 4px rounded tops, crosshair-free per-bar tooltip. */
export function DailyBars({ data, days }: { data: { date: string; count: number }[]; days: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const series = useMemo(() => {
    const byDate = new Map(data.map((d) => [d.date, d.count]));
    const out: { date: string; count: number }[] = [];
    const today = new Date();
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      const key = d.toISOString().slice(0, 10);
      out.push({ date: key, count: byDate.get(key) ?? 0 });
    }
    return out;
  }, [data, days]);

  const W = 720;
  const H = 180;
  const pad = { l: 28, r: 8, t: 12, b: 22 };
  const max = Math.max(1, ...series.map((d) => d.count));
  const niceMax = max <= 4 ? max : Math.ceil(max / 5) * 5;
  const slot = (W - pad.l - pad.r) / series.length;
  const bw = Math.max(2, Math.min(18, slot - 2)); // 2px surface gap between bars
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / niceMax);
  const ticks = [0, niceMax / 2, niceMax].map((t) => Math.round(t));
  const fmt = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Лиды по дням">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeWidth={1} />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--text-3)">
              {t}
            </text>
          </g>
        ))}
        {series.map((d, i) => {
          const x = pad.l + i * slot + (slot - bw) / 2;
          const top = y(d.count);
          const h = y(0) - top;
          const r = Math.min(4, bw / 2, h);
          return (
            <g key={d.date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              {/* hit target larger than the mark */}
              <rect x={pad.l + i * slot} y={pad.t} width={slot} height={H - pad.t - pad.b} fill="transparent" />
              {d.count > 0 && (
                <path
                  d={`M${x},${y(0)} V${top + r} Q${x},${top} ${x + r},${top} H${x + bw - r} Q${x + bw},${top} ${x + bw},${top + r} V${y(0)} Z`}
                  fill="var(--chart-1)"
                  opacity={hover === null || hover === i ? 1 : 0.45}
                />
              )}
            </g>
          );
        })}
        {[0, Math.floor(series.length / 2), series.length - 1].map((i) => (
          <text key={i} x={pad.l + i * slot + slot / 2} y={H - 6} textAnchor="middle" fontSize={11} fill="var(--text-3)">
            {fmt.format(new Date(series[i].date))}
          </text>
        ))}
      </svg>
      {hover !== null && (
        <div
          className="card pointer-events-none absolute -translate-x-1/2 px-2.5 py-1.5 text-xs"
          style={{ left: `${((pad.l + hover * slot + slot / 2) / W) * 100}%`, top: 0 }}
        >
          <div className="text-text-3">{fmt.format(new Date(series[hover].date))}</div>
          <div className="font-semibold">{series[hover].count} лидов</div>
        </div>
      )}
    </div>
  );
}

/** Horizontal magnitude bars for categories (single hue; labels in text ink). */
export function CategoryBars({ data, labels = {} }: { data: Record<string, number>; labels?: Record<string, string> }) {
  const rows = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...rows.map((r) => r[1]));
  if (!rows.length) return <p className="py-6 text-center text-sm text-text-3">Нет данных</p>;
  return (
    <div className="space-y-2.5">
      {rows.map(([k, v]) => (
        <div key={k} className="group" title={`${labels[k] ?? k}: ${v}`}>
          <div className="mb-1 flex justify-between text-[13px]">
            <span className="truncate text-text-2">{labels[k] ?? k}</span>
            <span className="font-medium tabular-nums">{v}</span>
          </div>
          <div className="h-2 rounded-full bg-surface-2">
            <div className="h-2 rounded-full bg-[var(--chart-1)]" style={{ width: `${(v / max) * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}
