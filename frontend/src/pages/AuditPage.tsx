import { Fragment, useState } from "react";
import { api, qs } from "../api/client";
import { AuditEntry } from "../api/types";
import { ErrorNote, Loading } from "../components/ui";
import { fmtDateTime, titleCase } from "../lib/format";
import { useApi } from "../lib/useApi";

const ENTITY_TYPES = ["", "factory", "floor", "area", "asset", "asset_type", "device", "organization"];

export function AuditPage() {
  const [entity, setEntity] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const log = useApi(() => api.get<AuditEntry[]>(`/audit${qs({ entity_type: entity, limit: 500 })}`), [entity]);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Audit log</h1>
          <div className="sub">Append-only record of every configuration change, with who made it and when.</div>
        </div>
      </div>
      {log.error && <ErrorNote error={log.error} onRetry={log.reload} />}
      <section className="panel">
        <div className="toolbar">
          <select className="select" style={{ width: 180 }} value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Entity type">
            {ENTITY_TYPES.map((t) => <option key={t} value={t}>{t ? titleCase(t) : "All entities"}</option>)}
          </select>
          <span className="faint small right">{log.data?.length ?? 0} entries</span>
        </div>
        {!log.data ? <Loading /> : (
          <table className="table">
            <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Summary</th></tr></thead>
            <tbody>
              {log.data.map((e) => (
                <Fragment key={e.id}>
                  <tr className="clickable" onClick={() => setOpen(open === e.id ? null : e.id)}>
                    <td className="muted" style={{ whiteSpace: "nowrap" }}>{fmtDateTime(e.at)}</td>
                    <td className="muted">{e.user_email}</td>
                    <td><span className="tag mono">{e.action}</span></td>
                    <td>{e.summary}</td>
                  </tr>
                  {open === e.id && (
                    <tr><td colSpan={4}><pre className="mono" style={{ margin: 0, whiteSpace: "pre-wrap", color: "var(--text-2)" }}>{JSON.stringify(e.details, null, 2)}</pre></td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
