import { useEffect, useMemo, useRef, useState } from "react";
import { HistoryPoint, TelemetryDef } from "../api/types";

const fmt = (v: number) => (Number.isInteger(v) ? String(v) : Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
const fmtTime = (t: number) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

interface Series { t: number; v: number; min?: number; max?: number }

/** Time-series chart: avg line, min/max band, warn/alarm limit lines, hover readout. */
export function TrendChart({ points, live = [], def, from, to, height = 180 }: {
  points: HistoryPoint[]; live?: [number, number][]; def?: TelemetryDef; from: number; to: number; height?: number;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [hover, setHover] = useState<Series | null>(null);
  // Draw at the real pixel width so axis text isn't scaled up or down.
  useEffect(() => {
    if (!box.current || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(200, Math.round(e.contentRect.width))));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);
  const series: Series[] = useMemo(() => {
    const hist = points.filter((p) => p.avg !== null).map((p) => ({ t: p.t, v: p.avg!, min: p.min ?? undefined, max: p.max ?? undefined }));
    const lastT = hist.length ? hist[hist.length - 1].t : 0;
    return [...hist, ...live.filter(([t]) => t > lastT).map(([t, v]) => ({ t, v }))];
  }, [points, live]);

  const W = width, H = height, padL = 44, padR = 8, padT = 8, padB = 22;
  const end = Math.max(to, series.length ? series[series.length - 1].t : to);
  const limits = [def?.warn_low, def?.warn_high, def?.alarm_low, def?.alarm_high].filter((x): x is number => x != null);
  const vals = series.flatMap((s) => [s.v, s.min ?? s.v, s.max ?? s.v]);
  let lo = vals.length ? Math.min(...vals) : 0, hi = vals.length ? Math.max(...vals) : 1;
  // Include limits only when near the data, so the line isn't flattened.
  for (const l of limits) if (l >= lo - (hi - lo) * 0.5 && l <= hi + (hi - lo) * 0.5) { lo = Math.min(lo, l); hi = Math.max(hi, l); }
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const x = (t: number) => padL + ((t - from) / Math.max(end - from, 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);
  const line = series.map((s, i) => `${i ? "L" : "M"}${x(s.t).toFixed(1)},${y(s.v).toFixed(1)}`).join("");
  const band = series.filter((s) => s.min !== undefined);
  const bandPath = band.length > 1
    ? `M${band.map((s) => `${x(s.t).toFixed(1)},${y(s.max!).toFixed(1)}`).join("L")}L${[...band].reverse().map((s) => `${x(s.t).toFixed(1)},${y(s.min!).toFixed(1)}`).join("L")}Z`
    : "";
  const ticks = [lo + pad, (lo + hi) / 2, hi - pad];

  const onMove = (e: React.MouseEvent) => {
    if (!ref.current || !series.length) return;
    const r = ref.current.getBoundingClientRect();
    const t = from + (((e.clientX - r.left) / r.width) * W - padL) / (W - padL - padR) * (end - from);
    let best = series[0];
    for (const s of series) if (Math.abs(s.t - t) < Math.abs(best.t - t)) best = s;
    setHover(best);
  };

  return (
    <div className="chart" ref={box}>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img"
        aria-label={`${def?.label ?? "Trend"} chart`}>
        {ticks.map((v, i) => (
          <g key={i}>
            <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} className="chart-grid" />
            <text x={padL - 6} y={y(v) + 3} className="chart-axis" textAnchor="end">{fmt(v)}</text>
          </g>
        ))}
        {[def?.warn_low, def?.warn_high].map((l, i) => l != null && l > lo && l < hi && (
          <line key={`w${i}`} x1={padL} x2={W - padR} y1={y(l)} y2={y(l)} className="chart-limit warn" />
        ))}
        {[def?.alarm_low, def?.alarm_high].map((l, i) => l != null && l > lo && l < hi && (
          <line key={`a${i}`} x1={padL} x2={W - padR} y1={y(l)} y2={y(l)} className="chart-limit alarm" />
        ))}
        {bandPath && <path d={bandPath} className="chart-band" />}
        {line && <path d={line} className="chart-line" />}
        <text x={padL} y={H - 6} className="chart-axis">{fmtTime(from)}</text>
        <text x={W - padR} y={H - 6} className="chart-axis" textAnchor="end">{fmtTime(end)}</text>
        {hover && <circle cx={x(hover.t)} cy={y(hover.v)} r={3.5} className="chart-dot" />}
      </svg>
      {hover && (
        <div className="chart-tip">{fmt(hover.v)}{def?.unit ? ` ${def.unit}` : ""} · {new Date(hover.t).toLocaleTimeString()}</div>
      )}
      {!series.length && <div className="chart-empty">No data in this period</div>}
    </div>
  );
}

export function Sparkline({ values, color = "var(--accent)" }: { values: number[]; color?: string }) {
  if (values.length < 2) return <svg className="spark" viewBox="0 0 100 24" />;
  const lo = Math.min(...values), hi = Math.max(...values);
  const span = hi - lo || 1;
  const d = values.map((v, i) => `${i ? "L" : "M"}${(i / (values.length - 1)) * 100},${22 - ((v - lo) / span) * 20}`).join("");
  return <svg className="spark" viewBox="0 0 100 24" preserveAspectRatio="none"><path d={d} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" /></svg>;
}

/** 240° arc gauge with warn/alarm zones from the measurement definition. */
export function Gauge({ value, def, stale }: { value: number | null; def?: TelemetryDef; stale?: boolean }) {
  const min = def?.min ?? 0;
  const max = def?.max ?? Math.max(def?.alarm_high ?? 0, def?.warn_high ?? 0, (value ?? 0) * 1.25, 1);
  const a0 = -210, a1 = 30;
  const ang = (v: number) => a0 + ((Math.min(Math.max(v, min), max) - min) / (max - min || 1)) * (a1 - a0);
  const pt = (a: number, r: number) => [60 + r * Math.cos((a * Math.PI) / 180), 60 + r * Math.sin((a * Math.PI) / 180)];
  const arc = (from: number, to: number, r: number) => {
    const [x0, y0] = pt(ang(from), r), [x1, y1] = pt(ang(to), r);
    const large = ang(to) - ang(from) > 180 ? 1 : 0;
    return `M${x0},${y0}A${r},${r} 0 ${large} 1 ${x1},${y1}`;
  };
  const zones: [number, number, string][] = [];
  if (def?.warn_high != null) zones.push([def.warn_high, def.alarm_high ?? max, "var(--warn)"]);
  if (def?.alarm_high != null) zones.push([def.alarm_high, max, "var(--bad)"]);
  if (def?.warn_low != null) zones.push([def.alarm_low ?? min, def.warn_low, "var(--warn)"]);
  if (def?.alarm_low != null) zones.push([min, def.alarm_low, "var(--bad)"]);
  const [nx, ny] = pt(ang(value ?? min), 40);
  return (
    <svg viewBox="0 0 120 100" className="gauge" role="img" aria-label="Gauge">
      <path d={arc(min, max, 46)} className="gauge-track" />
      {zones.map(([a, b, c], i) => <path key={i} d={arc(a, b, 46)} stroke={c} strokeWidth={6} fill="none" />)}
      {value !== null && !stale && <path d={arc(min, value, 46)} className="gauge-fill" />}
      {value !== null && <line x1={60} y1={60} x2={nx} y2={ny} className="gauge-needle" opacity={stale ? 0.3 : 1} />}
      <circle cx={60} cy={60} r={3.5} className="gauge-hub" />
      <text x={14} y={98} className="chart-axis" textAnchor="start">{fmt(min)}</text>
      <text x={106} y={98} className="chart-axis" textAnchor="end">{fmt(max)}</text>
    </svg>
  );
}

const PALETTE = ["#38bdf8", "#a78bfa", "#22c55e", "#f59e0b", "#f472b6", "#2dd4bf", "#fb7185", "#facc15", "#60a5fa", "#c084fc", "#4ade80", "#fb923c"];
export const seriesColor = (i: number) => PALETTE[i % PALETTE.length];

function useWidth(initial = 600) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    if (!box.current || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(240, Math.round(e.contentRect.width))));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);
  return { box, width };
}

/** Stacked bars over time buckets (e.g. kWh per hour per meter). */
export function BarChart({ buckets, series, unit, height = 220, labelFmt }: {
  buckets: number[]; series: { label: string; values: number[] }[]; unit: string; height?: number; labelFmt: (t: number) => string;
}) {
  const { box, width } = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const W = width, H = height, padL = 46, padR = 8, padT = 10, padB = 24;
  const totals = buckets.map((_, i) => series.reduce((a, s) => a + (s.values[i] ?? 0), 0));
  const max = Math.max(1e-9, ...totals) * 1.1;
  const bw = (W - padL - padR) / Math.max(buckets.length, 1);
  const y = (v: number) => padT + (1 - v / max) * (H - padT - padB);
  const every = Math.ceil(buckets.length / Math.max(1, Math.floor((W - padL) / 70)));
  return (
    <div className="chart" ref={box}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Bar chart" onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((f, i) => (
          <g key={i}><line x1={padL} x2={W - padR} y1={y(max * f / 1.1)} y2={y(max * f / 1.1)} className="chart-grid" />
            <text x={padL - 6} y={y(max * f / 1.1) + 3} className="chart-axis" textAnchor="end">{fmt(max * f / 1.1)}</text></g>
        ))}
        {buckets.map((b, i) => {
          let acc = 0;
          return (
            <g key={b} onMouseEnter={() => setHover(i)}>
              <rect x={padL + i * bw} y={padT} width={bw} height={H - padT - padB} fill="transparent" />
              {series.map((s, si) => {
                const v = s.values[i] ?? 0;
                const y0 = y(acc), y1 = y(acc + v);
                acc += v;
                return <rect key={si} x={padL + i * bw + bw * 0.12} width={bw * 0.76} y={y1} height={Math.max(0, y0 - y1)} fill={seriesColor(si)} opacity={hover === null || hover === i ? 0.9 : 0.45} rx={1.5} />;
              })}
              {i % every === 0 && <text x={padL + i * bw + bw / 2} y={H - 7} className="chart-axis" textAnchor="middle">{labelFmt(b)}</text>}
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div className="chart-tip">{labelFmt(buckets[hover])}: {series.map((s, si) => <span key={si} style={{ color: seriesColor(si) }}> {s.label} {fmt(s.values[hover] ?? 0)}</span>)} · total {fmt(totals[hover])} {unit}</div>
      )}
      {!buckets.length && <div className="chart-empty">No data in this period</div>}
    </div>
  );
}

/** Several assets' series on one time axis. */
export function MultiLineChart({ series, from, to, unit, height = 240 }: {
  series: { label: string; points: [number, number][] }[]; from: number; to: number; unit: string; height?: number;
}) {
  const { box, width } = useWidth();
  const W = width, H = height, padL = 46, padR = 8, padT = 10, padB = 22;
  const vals = series.flatMap((s) => s.points.map((p) => p[1]));
  let lo = vals.length ? Math.min(...vals) : 0, hi = vals.length ? Math.max(...vals) : 1;
  if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const x = (t: number) => padL + ((t - from) / Math.max(to - from, 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);
  const span = to - from;
  const tl = (t: number) => (span > 2 * 86400_000 ? new Date(t).toLocaleDateString([], { month: "short", day: "numeric" }) : fmtTime(t));
  return (
    <div className="chart" ref={box}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Comparison chart">
        {[lo + pad, (lo + hi) / 2, hi - pad].map((v, i) => (
          <g key={i}><line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} className="chart-grid" />
            <text x={padL - 6} y={y(v) + 3} className="chart-axis" textAnchor="end">{fmt(v)}</text></g>
        ))}
        {series.map((s, i) => (
          <path key={i} d={s.points.map((p, j) => `${j ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join("")}
            fill="none" stroke={seriesColor(i)} strokeWidth={1.8} strokeLinejoin="round" />
        ))}
        <text x={padL} y={H - 6} className="chart-axis">{tl(from)}</text>
        <text x={W - padR} y={H - 6} className="chart-axis" textAnchor="end">{tl(to)}</text>
      </svg>
      <div className="legend-inline">{series.map((s, i) => <span key={i}><i style={{ background: seriesColor(i) }} />{s.label}</span>)}{unit && <span className="faint">({unit})</span>}</div>
      {!vals.length && <div className="chart-empty">No data in this period</div>}
    </div>
  );
}
