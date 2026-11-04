import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, qs, tokenStore } from "../api/client";
import { Asset, AssetType } from "../api/types";
import { BarChart, MultiLineChart, seriesColor } from "../components/charts";
import { useToast } from "../components/Toast";
import { Empty, ErrorNote, Field, Loading, Tabs } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { titleCase } from "../lib/format";
import { useApi } from "../lib/useApi";

interface UtilRow { asset_id: string; code: string; name: string; category: string; seconds: Record<string, number>; known_s: number; no_data_s: number;
  running_s: number; downtime_s: number; utilization: number | null; starts: number }
interface Energy { bucket: string; buckets: number[]; meters: { asset_id: string; code: string; name: string; kwh: number[]; total_kwh: number }[] }
interface Production { bucket: string; buckets: number[]; counters: { asset_id: string; code: string; name: string; measurement: string; counts: number[]; total: number }[] }
interface Compare { measurement: string; from: number; to: number; series: { asset_id: string; code: string; points: [number, number][] }[] }

const PERIODS = [{ h: 8, l: "Last 8 h" }, { h: 24, l: "Last 24 h" }, { h: 168, l: "Last 7 days" }, { h: 720, l: "Last 30 days" }];
const STATE_COLORS: Record<string, string> = { running: "#22c55e", stopped: "#94a3b8", idle: "#64748b", fault: "#ef4444", emergency_stop: "#dc2626", maintenance: "#38bdf8" };
const hrs = (s: number) => (s / 3600).toFixed(s >= 36000 ? 0 : 1);
const bucketLabel = (bucket: string) => (t: number) => bucket === "day"
  ? new Date(t).toLocaleDateString([], { weekday: "short", day: "numeric" })
  : new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function Utilization({ fid, hours }: { fid: string; hours: number }) {
  const d = useApi(() => api.get<{ assets: UtilRow[] }>(`/analytics/utilization${qs({ factory_id: fid, hours })}`), [fid, hours]);
  if (d.error) return <ErrorNote error={d.error} />;
  if (!d.data) return <Loading />;
  const rows = d.data.assets;
  if (!rows.length) return <Empty title="No equipment with a state signal" />;
  const window = hours * 3600;
  return (
    <table className="table">
      <thead><tr><th>Equipment</th><th style={{ width: "38%" }}>Time in state</th><th className="num">Utilization</th><th className="num">Running h</th><th className="num">Downtime h</th><th className="num">No data h</th><th className="num">Starts</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.asset_id}>
            <td><Link to={`/assets/${r.asset_id}`}><span className="code-chip">{r.code}</span></Link> <span className="muted small">{r.name}</span></td>
            <td>
              <div className="state-bar" title={Object.entries(r.seconds).map(([k, v]) => `${k}: ${hrs(v)} h`).join(" · ")}>
                {Object.entries(r.seconds).map(([k, v]) => <span key={k} style={{ width: `${(v / window) * 100}%`, background: STATE_COLORS[k] ?? "#a78bfa" }} />)}
                <span style={{ width: `${(r.no_data_s / window) * 100}%`, background: "var(--bg-hover)" }} />
              </div>
            </td>
            <td className="num"><strong>{r.utilization === null ? "—" : `${(r.utilization * 100).toFixed(1)} %`}</strong></td>
            <td className="num">{hrs(r.running_s)}</td>
            <td className="num">{hrs(r.downtime_s)}</td>
            <td className="num faint">{hrs(r.no_data_s)}</td>
            <td className="num">{r.starts}</td>
          </tr>
        ))}
      </tbody>
      <tfoot><tr><td colSpan={7} className="faint small">
        <span className="legend-inline">{Object.entries(STATE_COLORS).map(([k, c]) => <span key={k}><i style={{ background: c }} />{titleCase(k)}</span>)}<span><i style={{ background: "var(--bg-hover)" }} />No data</span></span>
        Utilization = running ÷ time with known state. Gaps over 60 s count as "no data", never as running.
      </td></tr></tfoot>
    </table>
  );
}

function EnergyView({ fid, hours }: { fid: string; hours: number }) {
  const bucket = hours > 48 ? "day" : "hour";
  const d = useApi(() => api.get<Energy>(`/analytics/energy${qs({ factory_id: fid, hours, bucket })}`), [fid, hours]);
  if (d.error) return <ErrorNote error={d.error} />;
  if (!d.data) return <Loading />;
  const total = d.data.meters.reduce((a, m) => a + m.total_kwh, 0);
  return (
    <div className="stack">
      <div className="cards">
        <div className="panel stat"><div className="label">Total energy</div><div className="value">{total.toFixed(0)} kWh</div></div>
        {d.data.meters.map((m, i) => <div key={m.asset_id} className="panel stat"><div className="label"><i className="dotc" style={{ background: seriesColor(i) }} />{m.code} · {m.name}</div><div className="value">{m.total_kwh.toFixed(0)} kWh</div></div>)}
      </div>
      <BarChart buckets={d.data.buckets} unit="kWh" labelFmt={bucketLabel(bucket)} series={d.data.meters.map((m) => ({ label: m.code, values: m.kwh }))} />
      <p className="faint small" style={{ margin: 0 }}>kWh per {bucket} = average active power × time. Sub-meters may be included in the incomer total.</p>
    </div>
  );
}

function ProductionView({ fid, hours }: { fid: string; hours: number }) {
  const bucket = hours > 48 ? "day" : "hour";
  const d = useApi(() => api.get<Production>(`/analytics/production${qs({ factory_id: fid, hours, bucket })}`), [fid, hours]);
  if (d.error) return <ErrorNote error={d.error} />;
  if (!d.data) return <Loading />;
  const lines = d.data.counters.filter((c) => c.measurement === "output_count");
  const shown = lines.length ? lines : d.data.counters;
  return (
    <div className="stack">
      <div className="cards">
        {d.data.counters.map((c) => <div key={c.asset_id + c.measurement} className="panel stat"><div className="label">{c.code} · {titleCase(c.measurement)}</div><div className="value">{c.total.toLocaleString()}</div></div>)}
      </div>
      <BarChart buckets={d.data.buckets} unit="pcs" labelFmt={bucketLabel(bucket)} series={shown.map((c) => ({ label: c.code, values: c.counts }))} />
      <p className="faint small" style={{ margin: 0 }}>Counter increases per {bucket}; counter resets (e.g. at midnight) are handled. Chart shows {lines.length ? "line output" : "all counters"}.</p>
    </div>
  );
}

function CompareView({ fid, hours, assets, types }: { fid: string; hours: number; assets: Asset[]; types: Record<string, AssetType> }) {
  const measurements = useMemo(() => {
    const m = new Map<string, string>();
    assets.forEach((a) => types[a.asset_type_id]?.telemetry.filter((d) => d.data_type === "number" || d.data_type === "integer").forEach((d) => m.set(d.key, `${d.label}${d.unit ? ` (${d.unit})` : ""}`)));
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [assets, types]);
  const [measurement, setMeasurement] = useState("temp");
  const candidates = assets.filter((a) => types[a.asset_type_id]?.telemetry.some((d) => d.key === measurement));
  const [picked, setPicked] = useState<string[]>([]);
  const ids = picked.filter((id) => candidates.some((a) => a.id === id));
  const chosen = ids.length ? ids : candidates.slice(0, 4).map((a) => a.id);
  const d = useApi(() => (chosen.length ? api.get<Compare>(`/analytics/compare${qs({ factory_id: fid, measurement, asset_ids: chosen.join(","), hours })}`) : Promise.resolve(undefined)),
    [fid, measurement, chosen.join(","), hours]);
  const unit = measurements.find(([k]) => k === measurement)?.[1].match(/\(([^)]+)\)$/)?.[1] ?? "";
  return (
    <div className="stack">
      <div className="row wrap">
        <Field label="Measurement">
          <select className="select" value={measurement} onChange={(e) => { setMeasurement(e.target.value); setPicked([]); }}>
            {measurements.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <div className="row wrap" style={{ alignSelf: "flex-end" }}>
          {candidates.map((a) => (
            <label key={a.id} className="check small chip-check">
              <input type="checkbox" checked={chosen.includes(a.id)} onChange={(e) => setPicked(e.target.checked ? [...chosen, a.id] : chosen.filter((x) => x !== a.id))} />{a.code}
            </label>
          ))}
        </div>
      </div>
      {d.error ? <ErrorNote error={d.error} /> : !d.data ? <Loading /> :
        <MultiLineChart series={d.data.series.map((s) => ({ label: s.code, points: s.points }))} from={d.data.from} to={d.data.to} unit={unit} />}
      <p className="faint small" style={{ margin: 0 }}>Up to 24 h: 1–5 minute averages from raw data. Longer: hourly averages from roll-ups.</p>
    </div>
  );
}

function Reports({ fid, name }: { fid: string; name: string }) {
  const toast = useToast();
  const today = new Date();
  const [day, setDay] = useState(`${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`);
  const csv = async () => {
    try {
      const res = await fetch(`/api/reports/daily.csv${qs({ factory_id: fid, date: day })}`, { headers: { Authorization: `Bearer ${tokenStore.get()}` } });
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `HTTP ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `report-${name.replace(/\s+/g, "_")}-${day}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { toast("bad", (e as Error).message); }
  };
  return (
    <div className="stack" style={{ maxWidth: 560 }}>
      <p className="muted" style={{ margin: 0 }}>Daily operations report: equipment utilization, energy, production, alerts, commands and automation runs for one day (factory local time).</p>
      <Field label="Day"><input className="input" type="date" value={day} max={undefined} onChange={(e) => setDay(e.target.value)} style={{ maxWidth: 200 }} /></Field>
      <div className="row">
        <Link className="btn primary" to={`/reports/print?date=${day}`} target="_blank">Open printable report</Link>
        <button className="btn" onClick={csv}>Download CSV</button>
      </div>
      <p className="faint small" style={{ margin: 0 }}>Use the browser's Print → Save as PDF on the printable report.</p>
    </div>
  );
}

export function AnalyticsPage() {
  const { factory } = useFactory();
  const fid = factory?.id;
  const [tab, setTab] = useState<"util" | "energy" | "production" | "compare" | "reports">("util");
  const [hours, setHours] = useState(24);
  const assets = useApi(() => (fid ? api.get<Asset[]>(`/assets${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const types = useApi(() => api.get<AssetType[]>("/asset-types"), []);
  const typeById = useMemo(() => Object.fromEntries((types.data ?? []).map((t) => [t.id, t])), [types.data]);
  if (!factory || !fid) return <div className="panel"><Empty title="No factory selected" /></div>;
  return (
    <>
      <div className="page-head">
        <div><h1>Analytics</h1><div className="sub">Performance of {factory.name}, computed from recorded telemetry (hourly roll-ups kept for 400 days).</div></div>
        {tab !== "reports" && (
          <div className="actions">
            <select className="select" value={hours} onChange={(e) => setHours(Number(e.target.value))} aria-label="Period">
              {PERIODS.map((p) => <option key={p.h} value={p.h}>{p.l}</option>)}
            </select>
          </div>
        )}
      </div>
      <section className="panel">
        <Tabs value={tab} onChange={setTab} tabs={[
          { key: "util", label: "Utilization & downtime" }, { key: "energy", label: "Energy" }, { key: "production", label: "Production" },
          { key: "compare", label: "Compare machines" }, { key: "reports", label: "Reports" },
        ]} />
        <div className="panel-body">
          {tab === "util" && <Utilization fid={fid} hours={hours} />}
          {tab === "energy" && <EnergyView fid={fid} hours={hours} />}
          {tab === "production" && <ProductionView fid={fid} hours={hours} />}
          {tab === "compare" && (assets.data && types.data ? <CompareView fid={fid} hours={hours} assets={assets.data} types={typeById} /> : <Loading />)}
          {tab === "reports" && <Reports fid={fid} name={factory.name} />}
        </div>
      </section>
    </>
  );
}
