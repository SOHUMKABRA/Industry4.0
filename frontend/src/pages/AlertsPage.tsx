import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, qs } from "../api/client";
import { Alert, Asset } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";
import { Empty, ErrorNote, Loading, Pill, Tabs } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { timeAgo } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useAlerts } from "../live/liveMeta";

const KIND: Record<string, string> = { limit: "Limit", state: "Equipment", comm: "Communication", command: "Command", automation: "Automation" };

function duration(a: Alert) {
  const end = a.cleared_at ? new Date(a.cleared_at).getTime() : Date.now();
  const s = Math.max(0, Math.round((end - new Date(a.raised_at).getTime()) / 1000));
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function AlertsPage() {
  const { factory } = useFactory();
  const { can } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState<"active" | "history">("active");
  const fid = factory?.id;
  const active = useAlerts((s) => s.active);
  const history = useApi(() => (fid && tab === "history" ? api.get<Alert[]>(`/alerts${qs({ factory_id: fid, state: "history", limit: 500 })}`) : Promise.resolve([])), [fid, tab]);
  const assets = useApi(() => (fid ? api.get<Asset[]>(`/assets${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const assetById = useMemo(() => Object.fromEntries((assets.data ?? []).map((a) => [a.id, a])), [assets.data]);
  const list = Object.values(active).filter((a) => a.factory_id === fid)
    .sort((a, b) => (a.acked === b.acked ? (a.severity === b.severity ? b.raised_at.localeCompare(a.raised_at) : a.severity === "alarm" ? -1 : 1) : a.acked ? 1 : -1));
  const unacked = list.filter((a) => !a.acked).length;

  const ack = async (a: Alert) => {
    try { useAlerts.getState().upsert(await api.post<Alert>(`/alerts/${a.id}/ack`)); } catch (e) { toast("bad", (e as Error).message); }
  };
  const ackAll = async () => {
    try {
      const r = await api.post<{ acknowledged: number }>(`/alerts/ack-all?factory_id=${fid}`);
      useAlerts.getState().seed(await api.get<Alert[]>(`/alerts?factory_id=${fid}&state=active`));
      toast("ok", `${r.acknowledged} alert(s) acknowledged`);
    } catch (e) { toast("bad", (e as Error).message); }
  };

  if (!factory) return <div className="panel"><Empty title="No factory selected" /></div>;
  const rows = tab === "active" ? list : history.data ?? [];
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Alerts</h1>
          <div className="sub">Raised by the server from telemetry limits, equipment fault states, lost communication and failed commands. Cleared automatically when conditions return to normal.</div>
        </div>
        <div className="actions">{tab === "active" && can("alert.ack") && unacked > 0 && <button className="btn" onClick={ackAll}>Acknowledge all ({unacked})</button>}</div>
      </div>
      <section className="panel">
        <Tabs value={tab} onChange={setTab} tabs={[{ key: "active", label: `Active (${list.length})` }, { key: "history", label: "History" }]} />
        {history.error && <ErrorNote error={history.error} />}
        {tab === "history" && !history.data ? <Loading /> : rows.length === 0 ? (
          <Empty title={tab === "active" ? "No active alerts" : "No cleared alerts yet"}>{tab === "active" ? "Everything monitored is within limits and communicating." : ""}</Empty>
        ) : (
          <table className="table">
            <thead><tr><th>Severity</th><th>Type</th><th>Asset</th><th>Message</th><th>{tab === "active" ? "Since" : "Raised"}</th><th>Duration</th><th>{tab === "active" ? "" : "Acknowledged"}</th></tr></thead>
            <tbody>
              {rows.map((a) => {
                const asset = a.asset_id ? assetById[a.asset_id] : undefined;
                return (
                  <tr key={a.id} className={!a.acked && a.active ? `alert-row ${a.severity}` : ""}>
                    <td><Pill tone={a.severity === "alarm" ? "bad" : "warn"}>{a.severity === "alarm" ? "Alarm" : "Warning"}</Pill></td>
                    <td className="muted small">{KIND[a.kind]}{a.source === "simulated" && <span className="sim-tag" style={{ marginLeft: 6 }}>SIM</span>}</td>
                    <td>{asset ? <Link to={`/assets/${asset.id}`}><span className="code-chip">{asset.code}</span></Link> : "—"}</td>
                    <td>{a.message}</td>
                    <td className="muted small" title={new Date(a.raised_at).toLocaleString()}>{timeAgo(a.raised_at)}</td>
                    <td className="muted small">{duration(a)}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      {a.acked ? <span className="faint small">✓ {a.acked_by?.split("@")[0]}</span>
                        : a.active && can("alert.ack") ? <button className="btn sm" onClick={() => ack(a)}>Acknowledge</button> : <span className="faint small">not acknowledged</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
