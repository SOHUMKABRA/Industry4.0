import { useMemo, useState } from "react";
import { api, qs } from "../api/client";
import { Asset, Command } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Checklist, CommandTimeline, statusLabel, statusTone } from "../control/ControlPanel";
import { useToast } from "../components/Toast";
import { Empty, ErrorNote, Field, Loading, Modal, Pill } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { timeAgo } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useCommands } from "../live/liveMeta";

const FILTERS = [
  { key: "", label: "All" },
  { key: "PENDING_APPROVAL", label: "Awaiting approval" },
  { key: "REQUESTED,VALIDATING,APPROVED,SENT,ACKNOWLEDGED", label: "In progress" },
  { key: "COMPLETED", label: "Completed" },
  { key: "REJECTED,FAILED,TIMED_OUT,CANCELLED", label: "Not completed" },
];

export function CommandsPage() {
  const { factory } = useFactory();
  const { me, can } = useAuth();
  const toast = useToast();
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<Command | null>(null);
  const [why, setWhy] = useState("");
  const fid = factory?.id;
  const list = useApi(() => (fid ? api.get<Command[]>(`/commands${qs({ factory_id: fid, status: filter, limit: 300 })}`) : Promise.resolve([])), [fid, filter]);
  const pending = useApi(() => (fid ? api.get<Command[]>(`/commands${qs({ factory_id: fid, status: "PENDING_APPROVAL" })}`) : Promise.resolve([])), [fid]);
  const assets = useApi(() => (fid ? api.get<Asset[]>(`/assets${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const pushed = useCommands((s) => s.byId);
  const assetById = useMemo(() => Object.fromEntries((assets.data ?? []).map((a) => [a.id, a])), [assets.data]);

  const merge = (rows: Command[] | undefined) => (rows ?? []).map((c) => (pushed[c.id] && pushed[c.id].events.length >= c.events.length ? pushed[c.id] : c));
  const rows = merge(list.data);
  const queue = merge(pending.data).filter((c) => c.status === "PENDING_APPROVAL");
  const selected = rows.find((c) => c.id === open) ?? queue.find((c) => c.id === open);

  const decide = async (c: Command, action: "approve" | "reject" | "cancel", body?: object) => {
    try {
      const r = await api.post<Command>(`/commands/${c.id}/${action}`, body);
      useCommands.getState().upsert(r);
      toast("ok", `${c.control_label}: ${action === "approve" ? "approved and sent" : action === "reject" ? "rejected" : "cancelled"}`);
      void pending.reload(); void list.reload();
    } catch (e) { toast("bad", (e as Error).message); }
  };

  if (!factory) return <div className="panel"><Empty title="No factory selected" /></div>;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Commands</h1>
          <div className="sub">Every control action with its validation, approval, device acknowledgement and verified outcome.</div>
        </div>
      </div>

      {queue.length > 0 && (
        <section className="panel" style={{ marginBottom: 14 }}>
          <div className="panel-head"><h2>Awaiting approval</h2><Pill tone="warn">{queue.length}</Pill></div>
          <table className="table">
            <tbody>
              {queue.map((c) => {
                const own = c.requested_by === me?.user.email;
                return (
                  <tr key={c.id}>
                    <td><span className="code-chip">{assetById[c.asset_id]?.code ?? "?"}</span></td>
                    <td><strong>{c.control_label}</strong>{Object.keys(c.params).length > 0 && <span className="muted"> → {Object.entries(c.params).map(([k, v]) => `${k}=${v}`).join(", ")}</span>}</td>
                    <td className="muted small">{c.requested_by} · {timeAgo(c.requested_at)}{c.reason && <> · “{c.reason}”</>}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      {can("control.approve") && !own && <button className="btn sm primary" onClick={() => decide(c, "approve")}>Approve &amp; send</button>}
                      {can("control.approve") && !own && <button className="btn sm danger" onClick={() => { setWhy(""); setRejecting(c); }}>Reject</button>}
                      {(own || can("control.approve")) && <button className="btn sm ghost" onClick={() => decide(c, "cancel")}>Cancel</button>}
                      {own && <span className="faint small"> needs another person</span>}
                      {!can("control.approve") && !own && <span className="faint small">engineer/admin approves</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      <section className="panel">
        <div className="toolbar">
          <select className="select" style={{ width: 200 }} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Status filter">
            {FILTERS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select>
          <button className="btn sm" onClick={() => list.reload()}>Refresh</button>
          <span className="faint small right">{rows.length} commands</span>
        </div>
        {list.error && <ErrorNote error={list.error} />}
        {!list.data ? <Loading /> : rows.length === 0 ? <Empty title="No commands yet">Use the controls on the Live monitoring page or an asset's Control tab.</Empty> : (
          <table className="table">
            <thead><tr><th>Time</th><th>Asset</th><th>Command</th><th>Status</th><th>Requested by</th><th>Result</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => setOpen(c.id)}>
                  <td className="muted small" style={{ whiteSpace: "nowrap" }}>{new Date(c.requested_at).toLocaleString()}</td>
                  <td><span className="code-chip">{assetById[c.asset_id]?.code ?? "?"}</span></td>
                  <td>{c.control_label}{Object.keys(c.params).length > 0 && <span className="muted small"> ({Object.values(c.params).join(", ")})</span>}{c.simulated && <span className="sim-tag" style={{ marginLeft: 6 }}>SIM</span>}</td>
                  <td><Pill tone={statusTone(c)}>{statusLabel(c)}</Pill></td>
                  <td className="muted small">{c.requested_by}{c.approved_by && <> · ✓ {c.approved_by}</>}</td>
                  <td className="small muted truncate" style={{ maxWidth: 360 }} title={c.result_message}>{c.result_message || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {selected && (
        <Modal wide title={<span className="row">{selected.control_label} · <span className="code-chip">{assetById[selected.asset_id]?.code}</span><Pill tone={statusTone(selected)}>{statusLabel(selected)}</Pill></span>} onClose={() => setOpen(null)}>
          <div className="two-col">
            <div>
              <div className="section-title">Lifecycle</div>
              <CommandTimeline cmd={selected} />
            </div>
            <div>
              <div className="section-title">Validation</div>
              <Checklist checks={selected.checks} />
              <dl className="kv small" style={{ marginTop: 12 }}>
                <dt>Requested by</dt><dd>{selected.requested_by}</dd>
                {selected.approved_by && <><dt>Approved by</dt><dd>{selected.approved_by}</dd></>}
                <dt>Reason</dt><dd>{selected.reason || "—"}</dd>
                <dt>Parameters</dt><dd className="mono">{JSON.stringify(selected.params)}</dd>
                <dt>Data source</dt><dd>{selected.simulated ? "Simulated device" : "Field device"}</dd>
              </dl>
            </div>
          </div>
        </Modal>
      )}
      {rejecting && (
        <Modal title={`Reject ${rejecting.control_label}?`} onClose={() => setRejecting(null)} footer={<>
          <button className="btn" onClick={() => setRejecting(null)}>Back</button>
          <button className="btn danger solid" onClick={() => { const c = rejecting; setRejecting(null); void decide(c, "reject", { reason: why }); }}>Reject</button>
        </>}>
          <Field label="Reason (sent back to the requester and audited)"><input className="input" value={why} onChange={(e) => setWhy(e.target.value)} autoFocus /></Field>
        </Modal>
      )}
    </>
  );
}
