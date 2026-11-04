import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { api, qs } from "../api/client";
import { ErrorNote, Loading } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { titleCase } from "../lib/format";
import { useApi } from "../lib/useApi";

interface Report {
  factory: { name: string; location: string; timezone: string }; date: string; from: string; to: string; generated_at: string; generated_by: string; partial_day: boolean;
  utilization: { code: string; name: string; utilization: number | null; running_s: number; downtime_s: number; no_data_s: number; starts: number }[];
  energy: { total_kwh: number; meters: { code: string; name: string; total_kwh: number }[] };
  production: { code: string; name: string; measurement: string; total: number }[];
  alerts: { total: number; unacknowledged: number; by_severity: Record<string, number>; by_kind: Record<string, number>;
    longest: { severity: string; message: string; raised_at: string; duration_s: number; asset: string | null }[] };
  commands: { total: number; verified: number; simulated: number; by_status: Record<string, number> };
  automations: { runs: number; by_status: Record<string, number> };
}

const h = (s: number) => (s / 3600).toFixed(1);
const d = (s: number) => (s < 60 ? `${s}s` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);

/** Print-ready daily report (open in a new tab; Print → Save as PDF). */
export function ReportPrintPage() {
  const { factory } = useFactory();
  const [params] = useSearchParams();
  const day = params.get("date") ?? "";
  const r = useApi(() => (factory ? api.get<Report>(`/reports/daily${qs({ factory_id: factory.id, date: day })}`) : Promise.resolve(undefined)), [factory?.id, day]);
  useEffect(() => { document.title = `Daily report ${day}`; }, [day]);
  if (r.error) return <div style={{ padding: 24 }}><ErrorNote error={r.error} /></div>;
  if (!r.data) return <Loading />;
  const x = r.data;
  return (
    <div className="report">
      <div className="report-actions no-print"><button className="btn primary" onClick={() => window.print()}>Print / Save as PDF</button></div>
      <header>
        <h1>Daily operations report</h1>
        <div>{x.factory.name}{x.factory.location ? ` · ${x.factory.location}` : ""}</div>
        <div className="muted">{new Date(x.date).toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" })} ({x.factory.timezone})
          {x.partial_day && " · day in progress"}</div>
      </header>
      <section className="report-kpis">
        <div><span>Energy</span><strong>{x.energy.total_kwh.toFixed(0)} kWh</strong></div>
        <div><span>Alerts</span><strong>{x.alerts.total}</strong><em>{x.alerts.by_severity.alarm ?? 0} alarms</em></div>
        <div><span>Commands</span><strong>{x.commands.total}</strong><em>{x.commands.verified} verified</em></div>
        <div><span>Automation runs</span><strong>{x.automations.runs}</strong></div>
      </section>
      <h2>Equipment utilization</h2>
      <table>
        <thead><tr><th>Equipment</th><th>Utilization</th><th>Running h</th><th>Downtime h</th><th>No data h</th><th>Starts</th></tr></thead>
        <tbody>{x.utilization.map((u) => (
          <tr key={u.code}><td><b>{u.code}</b> {u.name}</td><td>{u.utilization === null ? "—" : `${(u.utilization * 100).toFixed(1)} %`}</td>
            <td>{h(u.running_s)}</td><td>{h(u.downtime_s)}</td><td>{h(u.no_data_s)}</td><td>{u.starts}</td></tr>
        ))}</tbody>
      </table>
      <div className="report-cols">
        <div>
          <h2>Energy</h2>
          <table><tbody>{x.energy.meters.map((m) => <tr key={m.code}><td><b>{m.code}</b> {m.name}</td><td className="num">{m.total_kwh.toFixed(1)} kWh</td></tr>)}</tbody></table>
        </div>
        <div>
          <h2>Production</h2>
          <table><tbody>{x.production.map((p) => <tr key={p.code + p.measurement}><td><b>{p.code}</b> {titleCase(p.measurement)}</td><td className="num">{p.total.toLocaleString()}</td></tr>)}</tbody></table>
        </div>
      </div>
      <h2>Longest alerts</h2>
      {x.alerts.longest.length ? (
        <table>
          <thead><tr><th>Severity</th><th>Asset</th><th>Message</th><th>Raised</th><th>Duration</th></tr></thead>
          <tbody>{x.alerts.longest.map((a, i) => (
            <tr key={i}><td>{titleCase(a.severity)}</td><td>{a.asset ?? "—"}</td><td>{a.message}</td><td>{new Date(a.raised_at).toLocaleTimeString()}</td><td>{d(a.duration_s)}</td></tr>
          ))}</tbody>
        </table>
      ) : <p className="muted">No alerts.</p>}
      <div className="report-cols">
        <div><h2>Commands by outcome</h2><ul>{Object.entries(x.commands.by_status).map(([k, v]) => <li key={k}>{titleCase(k.toLowerCase())}: {v}</li>)}</ul>
          {x.commands.simulated > 0 && <p className="muted">{x.commands.simulated} on simulated devices.</p>}</div>
        <div><h2>Alerts by type</h2><ul>{Object.entries(x.alerts.by_kind).map(([k, v]) => <li key={k}>{titleCase(k)}: {v}</li>)}</ul>
          <p className="muted">{x.alerts.unacknowledged} not acknowledged.</p></div>
      </div>
      <footer>Generated {new Date(x.generated_at).toLocaleString()} by {x.generated_by}. Times are factory local time. Gaps in data are reported as "no data", never estimated.</footer>
    </div>
  );
}
