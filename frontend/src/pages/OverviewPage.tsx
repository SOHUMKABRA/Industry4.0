import { Link } from "react-router-dom";
import { api } from "../api/client";
import { AuditEntry, FactorySummary } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Empty, ErrorNote, Loading } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { timeAgo } from "../lib/format";
import { useApi } from "../lib/useApi";
import { CreateFactoryButton } from "./FactoryPage";

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

          {!s.live_data_available && (
            <div className="notice info">
              <span>
                <strong>Operational state isn't shown yet.</strong> Running/stopped/fault counts, live values and alerts need
                telemetry ingestion (Phase 4). This build shows configuration only and won't show estimated or made-up machine states.
              </span>
            </div>
          )}

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
