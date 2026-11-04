import { Link } from "react-router-dom";
import { api } from "../api/client";
import { AuditEntry, FactorySummary } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Empty, ErrorNote, Loading } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { timeAgo } from "../lib/format";
import { useApi } from "../lib/useApi";
import { CreateFactoryButton } from "./FactoryPage";
import { Asset, AssetType } from "../api/types";
import { qs } from "../api/client";
import { SourceBanner, usePlantStatus } from "../live/plant";
import { useMemo } from "react";

function LiveStrip({ factoryId }: { factoryId: string }) {
  const assets = useApi(() => api.get<Asset[]>(`/assets${qs({ factory_id: factoryId })}`), [factoryId]);
  const types = useApi(() => api.get<AssetType[]>("/asset-types"), []);
  const typeById = useMemo(() => Object.fromEntries((types.data ?? []).map((t) => [t.id, t])), [types.data]);
  const p = usePlantStatus(assets.data, typeById);
  const tiles = [
    ["Running", p.running, "ok"], ["Stopped / idle", p.stopped, ""], ["Fault / E-stop", p.fault, p.fault ? "bad" : ""],
    ["Alarms", p.alarm, p.alarm ? "bad" : ""], ["Warnings", p.warn, p.warn ? "warn" : ""], ["Stale / no data", p.noData, p.noData ? "warn" : ""],
  ] as const;
  return (
    <section className="panel">
      <div className="panel-head"><h2>Live status</h2><Link to="/monitor" className="right small">Open live twin</Link></div>
      <div className="panel-body stack">
        <SourceBanner />
        <div className="mon-kpis">{tiles.map(([l, v, t]) => <div key={l} className={`mon-kpi ${t}`}><span>{l}</span><strong>{v}</strong></div>)}</div>
      </div>
    </section>
  );
}

function Bars({ rows }: { rows: { key: string; label: string; count: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  if (!rows.length) return <p className="faint small">Nothing yet.</p>;
  return (
    <div className="bar-list">
      {rows.map((r) => (
        <div className="bar-row" key={r.key}>
          <span className="muted" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.label}>{r.label}</span>
          <div className="bar-track"><div className="bar-fill" style={{ width: `${(r.count / max) * 100}%` }} /></div>
          <span className="num" style={{ textAlign: "right" }}>{r.count}</span>
        </div>
      ))}
    </div>
  );
}

export function OverviewPage() {
  const { factory, loading: fLoading } = useFactory();
  const { can } = useAuth();
  const summary = useApi(
    () => (factory ? api.get<FactorySummary>(`/factories/${factory.id}/summary`) : Promise.resolve(undefined)),
    [factory?.id],
  );
  const activity = useApi(
    () => (can("audit.read") ? api.get<AuditEntry[]>("/audit?limit=8") : Promise.resolve([])),
    [factory?.id],
  );

  if (fLoading) return <Loading />;
  if (!factory)
    return (
      <div className="panel">
        <Empty title="No factory yet" action={<CreateFactoryButton />}>
          Create your first factory, then add floors, areas and equipment.
        </Empty>
      </div>
    );

  const s = summary.data;
  const tiles = s && [
    { label: "Assets", value: s.asset_count, hint: `${s.by_category.length} categories`, to: "/assets" },
    { label: "Devices", value: s.device_count, hint: `${s.devices_enabled} enabled`, to: "/devices" },
    { label: "Untested devices", value: s.devices_untested, hint: "connection never verified", to: "/devices" },
    { label: "Failed connection tests", value: s.devices_test_failed, hint: "last test failed", to: "/devices", bad: s.devices_test_failed > 0 },
    { label: "Floors / areas", value: `${s.floors} / ${s.areas}`, hint: "factory structure", to: "/factory" },
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{factory.name}</h1>
          <div className="sub">{factory.location || "No location set"}</div>
        </div>
      </div>
      {summary.error && <ErrorNote error={summary.error} onRetry={summary.reload} />}
      {!s ? <Loading /> : (
        <div className="stack" style={{ gap: 14 }}>
          <div className="cards">
            {tiles!.map((t) => (
              <Link key={t.label} to={t.to} className="panel stat" style={{ color: "inherit" }}>
                <div className="label">{t.label}</div>
                <div className="value" style={t.bad ? { color: "var(--bad)" } : undefined}>{t.value}</div>
                <div className="hint">{t.hint}</div>
              </Link>
            ))}
          </div>

          <LiveStrip factoryId={factory.id} />

          <div className="two-col">
            <section className="panel">
              <div className="panel-head"><h2>Assets by category</h2></div>
              <div className="panel-body"><Bars rows={s.by_category} /></div>
            </section>
            <section className="panel">
              <div className="panel-head"><h2>Assets by area</h2></div>
              <div className="panel-body"><Bars rows={s.by_area} /></div>
            </section>
          </div>

          {can("audit.read") && (
            <section className="panel">
              <div className="panel-head"><h2>Recent changes</h2><Link to="/audit" className="right small">View all</Link></div>
              <div className="panel-body flush">
                <table className="table">
                  <tbody>
                    {(activity.data ?? []).map((e) => (
                      <tr key={e.id}>
                        <td>{e.summary}</td>
                        <td className="muted">{e.user_email}</td>
                        <td className="faint" style={{ textAlign: "right", whiteSpace: "nowrap" }}>{timeAgo(e.at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}
    </>
  );
}
