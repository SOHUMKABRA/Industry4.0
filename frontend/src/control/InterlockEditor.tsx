import { useMemo, useState } from "react";
import { api, qs } from "../api/client";
import { Asset, AssetType, Interlock } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";
import { Field, Modal } from "../components/ui";
import { useApi } from "../lib/useApi";
import { LiveValue } from "../live/LiveValue";

const OPS = ["==", "!=", ">", ">=", "<", "<="];

/** Software permissives checked before a command is sent (fail closed on stale/missing data). */
export function InterlockEditor({ asset, type, types }: { asset: Asset; type: AssetType; types: Record<string, AssetType> }) {
  const { can } = useAuth();
  const toast = useToast();
  const locks = useApi(() => api.get<Interlock[]>(`/assets/${asset.id}/interlocks`), [asset.id]);
  const assets = useApi(() => api.get<Asset[]>(`/assets${qs({ factory_id: asset.factory_id })}`), [asset.factory_id]);
  const [edit, setEdit] = useState<Partial<Interlock> | null>(null);
  const byId = useMemo(() => Object.fromEntries((assets.data ?? []).map((a) => [a.id, a])), [assets.data]);
  const editable = can("factory.write");
  const src = edit?.source_asset_id ? byId[edit.source_asset_id] : undefined;
  const srcDefs = src ? types[src.asset_type_id]?.telemetry ?? [] : [];

  const save = async () => {
    const body = { control_key: edit!.control_key ?? "*", source_asset_id: edit!.source_asset_id, measurement: edit!.measurement,
      operator: edit!.operator ?? "==", value: String(edit!.value ?? ""), message: edit!.message ?? "", enabled: edit!.enabled ?? true };
    try {
      if (edit!.id) await api.put(`/interlocks/${edit!.id}`, body);
      else await api.post(`/assets/${asset.id}/interlocks`, body);
      setEdit(null);
      await locks.reload();
      toast("ok", "Interlock saved");
    } catch (e) { toast("bad", (e as Error).message); }
  };
  const remove = async (i: Interlock) => {
    try { await api.del(`/interlocks/${i.id}`); await locks.reload(); } catch (e) { toast("bad", (e as Error).message); }
  };

  return (
    <div className="stack" style={{ gap: 8 }}>
      <table className="table compact">
        <tbody>
          {(locks.data ?? []).map((i) => {
            const s = byId[i.source_asset_id];
            const d = s ? types[s.asset_type_id]?.telemetry.find((x) => x.key === i.measurement) : undefined;
            return (
              <tr key={i.id} style={{ opacity: i.enabled ? 1 : 0.5 }}>
                <td className="small"><span className="tag">{i.control_key === "*" ? "all controls" : i.control_key}</span></td>
                <td className="small mono">{i.source_code}.{i.measurement} {i.operator} {i.value}</td>
                <td className="small">{s && d ? <LiveValue assetId={s.id} def={d} /> : "—"}</td>
                <td className="faint small">{i.message}</td>
                {editable && (
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button className="btn sm ghost" onClick={() => setEdit(i)}>Edit</button>
                    <button className="btn sm ghost danger" onClick={() => remove(i)}>Remove</button>
                  </td>
                )}
              </tr>
            );
          })}
          {locks.data?.length === 0 && <tr><td className="faint small">No software interlocks. PLC and hardwired safety still apply.</td></tr>}
        </tbody>
      </table>
      {editable && <div><button className="btn sm" onClick={() => setEdit({ control_key: "start", operator: "==", enabled: true })}>Add interlock</button></div>}
      {edit && (
        <Modal title={edit.id ? "Edit interlock" : `New interlock on ${asset.code}`} onClose={() => setEdit(null)} footer={<>
          <button className="btn" onClick={() => setEdit(null)}>Cancel</button>
          <button className="btn primary" disabled={!edit.source_asset_id || !edit.measurement || edit.value === undefined || edit.value === ""} onClick={save}>Save</button>
        </>}>
          <div className="stack">
            <div className="grid-2">
              <Field label="Applies to command" help="Don't put permissives on Stop: stopping must always be possible.">
                <select className="select" value={edit.control_key} onChange={(e) => setEdit({ ...edit, control_key: e.target.value })}>
                  {type.controls.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                  <option value="*">All controls</option>
                </select>
              </Field>
              <Field label="Source equipment">
                <select className="select" value={edit.source_asset_id ?? ""} onChange={(e) => setEdit({ ...edit, source_asset_id: e.target.value, measurement: undefined })}>
                  <option value="">Select…</option>
                  {(assets.data ?? []).filter((a) => (types[a.asset_type_id]?.telemetry.length ?? 0) > 0).map((a) => <option key={a.id} value={a.id}>{a.code} – {a.name}</option>)}
                </select>
              </Field>
              <Field label="Measurement">
                <select className="select" value={edit.measurement ?? ""} disabled={!src} onChange={(e) => setEdit({ ...edit, measurement: e.target.value })}>
                  <option value="">Select…</option>
                  {srcDefs.map((d) => <option key={d.key} value={d.key}>{d.label}{d.unit ? ` (${d.unit})` : ""}</option>)}
                </select>
              </Field>
              <div className="row" style={{ alignItems: "flex-end" }}>
                <Field label="Condition">
                  <select className="select" style={{ width: 70 }} value={edit.operator} onChange={(e) => setEdit({ ...edit, operator: e.target.value })}>{OPS.map((o) => <option key={o}>{o}</option>)}</select>
                </Field>
                <Field label="Value">
                  {(() => {
                    const d = srcDefs.find((x) => x.key === edit.measurement);
                    return d?.options.length
                      ? <select className="select" value={edit.value ?? ""} onChange={(e) => setEdit({ ...edit, value: e.target.value })}><option value="">Select…</option>{d.options.map((o) => <option key={o}>{o}</option>)}</select>
                      : <input className="input" value={edit.value ?? ""} onChange={(e) => setEdit({ ...edit, value: e.target.value })} />;
                  })()}
                </Field>
              </div>
            </div>
            <Field label="Message shown when blocked"><input className="input" value={edit.message ?? ""} onChange={(e) => setEdit({ ...edit, message: e.target.value })} /></Field>
            <label className="check"><input type="checkbox" checked={edit.enabled ?? true} onChange={(e) => setEdit({ ...edit, enabled: e.target.checked })} />Enabled</label>
            <p className="faint small" style={{ margin: 0 }}>If the source value is missing or stale, the command is blocked (fail closed).</p>
          </div>
        </Modal>
      )}
    </div>
  );
}
