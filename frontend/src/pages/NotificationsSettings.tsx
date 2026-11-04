import { useState } from "react";
import { api } from "../api/client";
import { Channel, Delivery } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";
import { Confirm, Field, Loading, Modal, Pill } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useApi } from "../lib/useApi";

interface Form {
  id?: string; name: string; type: "webhook" | "email"; enabled: boolean; alerts: boolean; min_severity: "warning" | "alarm"; notify_clear: boolean;
  url: string; secret: string; host: string; port: number; starttls: boolean; username: string; password: string; from_addr: string; to: string;
}
const blank: Form = { name: "", type: "webhook", enabled: true, alerts: true, min_severity: "alarm", notify_clear: false, url: "", secret: "",
  host: "", port: 587, starttls: true, username: "", password: "", from_addr: "", to: "" };

function toForm(c: Channel): Form {
  const k = c.config as Record<string, string | number | boolean>;
  return { ...blank, id: c.id, name: c.name, type: c.type, enabled: c.enabled, alerts: c.alerts, min_severity: c.min_severity, notify_clear: c.notify_clear,
    url: String(k.url ?? ""), host: String(k.host ?? ""), port: Number(k.port ?? 587), starttls: Boolean(k.starttls ?? true),
    username: String(k.username ?? ""), from_addr: String(k.from ?? ""), to: String(k.to ?? "") };
}

export function NotificationsSettings() {
  const { can } = useAuth();
  const toast = useToast();
  const chans = useApi(() => api.get<Channel[]>("/notification-channels"), []);
  const [edit, setEdit] = useState<Form | null>(null);
  const [log, setLog] = useState<{ c: Channel; rows: Delivery[] } | null>(null);
  const [del, setDel] = useState<Channel | null>(null);
  const editable = can("factory.write");

  const save = async () => {
    const f = edit!;
    const body = { name: f.name, type: f.type, enabled: f.enabled, alerts: f.alerts, min_severity: f.min_severity, notify_clear: f.notify_clear,
      ...(f.type === "webhook" ? { url: f.url, secret: f.secret || undefined }
        : { host: f.host, port: f.port, starttls: f.starttls, username: f.username || undefined, password: f.password || undefined, from_addr: f.from_addr, to: f.to }) };
    try {
      if (f.id) await api.put(`/notification-channels/${f.id}`, body); else await api.post("/notification-channels", body);
      setEdit(null); await chans.reload(); toast("ok", "Channel saved");
    } catch (e) { toast("bad", (e as Error).message); }
  };
  const test = async (c: Channel) => {
    toast("info", `Sending test to ${c.name}…`);
    try {
      const r = await api.post<{ status: string; detail: string; attempts: number }>(`/notification-channels/${c.id}/test`);
      toast(r.status === "sent" ? "ok" : "bad", `${c.name}: ${r.status} (${r.detail})`);
    } catch (e) { toast("bad", (e as Error).message); }
  };

  if (!chans.data) return <Loading />;
  return (
    <div className="stack">
      <div className="row"><span className="muted small">Where alerts and automation notifications are sent. Webhooks are signed (HMAC-SHA256, header <code>X-Twin-Signature</code>).</span>
        {editable && <button className="btn primary right" onClick={() => setEdit({ ...blank })}>Add channel</button>}</div>
      <table className="table">
        <thead><tr><th>Channel</th><th>Type</th><th>Alerts</th><th>Target</th><th /></tr></thead>
        <tbody>
          {chans.data.map((c) => (
            <tr key={c.id} style={{ opacity: c.enabled ? 1 : 0.55 }}>
              <td><strong>{c.name}</strong>{!c.enabled && <span className="faint small"> (disabled)</span>}</td>
              <td><span className="tag">{c.type}</span></td>
              <td className="small">{c.alerts ? `${c.min_severity === "alarm" ? "Alarms" : "Warnings & alarms"}${c.notify_clear ? " + clears" : ""}` : <span className="faint">automations only</span>}</td>
              <td className="small mono truncate" style={{ maxWidth: 280 }}>{String(c.config.url ?? c.config.to ?? "")}</td>
              <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                {editable && <button className="btn sm" onClick={() => test(c)}>Send test</button>}
                <button className="btn sm ghost" onClick={async () => setLog({ c, rows: await api.get<Delivery[]>(`/notification-channels/${c.id}/deliveries`) })}>Delivery log</button>
                {editable && <button className="btn sm ghost" onClick={() => setEdit(toForm(c))}>Edit</button>}
                {editable && <button className="btn sm ghost danger" onClick={() => setDel(c)}>Delete</button>}
              </td>
            </tr>
          ))}
          {!chans.data.length && <tr><td colSpan={5} className="faint">No channels. Alerts are shown in the app only.</td></tr>}
        </tbody>
      </table>
      {edit && (
        <Modal title={edit.id ? "Edit channel" : "New notification channel"} onClose={() => setEdit(null)} footer={<>
          <button className="btn" onClick={() => setEdit(null)}>Cancel</button><button className="btn primary" disabled={!edit.name} onClick={save}>Save</button></>}>
          <div className="stack">
            <div className="grid-2">
              <Field label="Name" required><input className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} autoFocus /></Field>
              <Field label="Type"><select className="select" value={edit.type} onChange={(e) => setEdit({ ...edit, type: e.target.value as Form["type"] })}><option value="webhook">Webhook (HTTP POST)</option><option value="email">E-mail (SMTP)</option></select></Field>
            </div>
            {edit.type === "webhook" ? (
              <div className="grid-2">
                <Field label="URL" required><input className="input" value={edit.url} placeholder="https://…" onChange={(e) => setEdit({ ...edit, url: e.target.value })} /></Field>
                <Field label="Signing secret" help={edit.id ? "Leave blank to keep the stored secret" : "Shared with the receiver to verify the signature"}>
                  <input className="input" type="password" value={edit.secret} onChange={(e) => setEdit({ ...edit, secret: e.target.value })} /></Field>
              </div>
            ) : (
              <div className="grid-2">
                <Field label="SMTP host" required><input className="input" value={edit.host} onChange={(e) => setEdit({ ...edit, host: e.target.value })} /></Field>
                <Field label="Port"><input className="input" type="number" value={edit.port} onChange={(e) => setEdit({ ...edit, port: Number(e.target.value) })} /></Field>
                <Field label="Username"><input className="input" value={edit.username} onChange={(e) => setEdit({ ...edit, username: e.target.value })} /></Field>
                <Field label="Password" help={edit.id ? "Leave blank to keep" : undefined}><input className="input" type="password" value={edit.password} onChange={(e) => setEdit({ ...edit, password: e.target.value })} /></Field>
                <Field label="From" required><input className="input" value={edit.from_addr} onChange={(e) => setEdit({ ...edit, from_addr: e.target.value })} /></Field>
                <Field label="To (comma separated)" required><input className="input" value={edit.to} onChange={(e) => setEdit({ ...edit, to: e.target.value })} /></Field>
                <label className="check"><input type="checkbox" checked={edit.starttls} onChange={(e) => setEdit({ ...edit, starttls: e.target.checked })} />STARTTLS</label>
              </div>
            )}
            <div className="row wrap">
              <label className="check"><input type="checkbox" checked={edit.enabled} onChange={(e) => setEdit({ ...edit, enabled: e.target.checked })} />Enabled</label>
              <label className="check"><input type="checkbox" checked={edit.alerts} onChange={(e) => setEdit({ ...edit, alerts: e.target.checked })} />Send alerts</label>
              <select className="select" style={{ width: 190 }} value={edit.min_severity} disabled={!edit.alerts} onChange={(e) => setEdit({ ...edit, min_severity: e.target.value as Form["min_severity"] })}>
                <option value="alarm">Alarms only</option><option value="warning">Warnings and alarms</option>
              </select>
              <label className="check"><input type="checkbox" checked={edit.notify_clear} disabled={!edit.alerts} onChange={(e) => setEdit({ ...edit, notify_clear: e.target.checked })} />Also when cleared</label>
            </div>
          </div>
        </Modal>
      )}
      {log && (
        <Modal wide title={`${log.c.name} · delivery log`} onClose={() => setLog(null)}>
          <table className="table compact">
            <tbody>
              {log.rows.map((d) => (
                <tr key={d.id}><td className="faint small">{timeAgo(d.at)}</td><td><Pill tone={d.status === "sent" ? "ok" : "bad"}>{d.status}</Pill></td>
                  <td className="small"><span className="tag">{d.event}</span> {d.subject}</td><td className="faint small">{d.detail}{d.attempts > 1 ? ` · ${d.attempts} attempts` : ""}</td></tr>
              ))}
              {!log.rows.length && <tr><td className="faint">Nothing sent yet.</td></tr>}
            </tbody>
          </table>
        </Modal>
      )}
      {del && <Confirm title={`Delete ${del.name}?`} message="Automations that notify this channel will fail validation until updated." onClose={() => setDel(null)}
        onConfirm={async () => { setDel(null); await api.del(`/notification-channels/${del.id}`); await chans.reload(); }} />}
    </div>
  );
}
