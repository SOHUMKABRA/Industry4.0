import { useEffect, useMemo, useState } from "react";
import { api, qs } from "../api/client";
import { Asset, AssetType, Device, Scenario, ScenarioRun, ScenarioStep } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { useToast } from "../components/Toast";
import { Confirm, Empty, Field, Loading, Modal, Pill } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { useApi } from "../lib/useApi";

function pointsOf(d: Device | undefined) { return (d?.point_mappings ?? []).map((m) => m.point); }

function StepsEditor({ steps, onChange, devices }: { steps: ScenarioStep[]; onChange: (s: ScenarioStep[]) => void; devices: Device[] }) {
  const byId = Object.fromEntries(devices.map((d) => [d.id, d]));
  const up = (i: number, p: Partial<ScenarioStep>) => onChange(steps.map((s, j) => (j === i ? { ...s, ...p } : s)));
  return (
    <div className="stack" style={{ gap: 6 }}>
      {steps.map((s, i) => (
        <div key={i} className="rule-row">
          <label className="small row">t+<input className="input" type="number" min={0} style={{ width: 70 }} value={s.at_s} onChange={(e) => up(i, { at_s: Number(e.target.value) })} />s</label>
          <select className="select" value={s.device_id} onChange={(e) => up(i, { device_id: e.target.value, point: pointsOf(byId[e.target.value])[0] })} aria-label="Device">
            {devices.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <select className="select" style={{ width: 130 }} value={s.action} onChange={(e) => up(i, { action: e.target.value as ScenarioStep["action"] })} aria-label="Action">
            <option value="set">Force value</option><option value="offline">Go offline</option><option value="restore">Restore</option>
          </select>
          {s.action === "set" && <>
            <select className="select" value={s.point ?? ""} onChange={(e) => up(i, { point: e.target.value })} aria-label="Point">
              {pointsOf(byId[s.device_id]).map((p) => <option key={p}>{p}</option>)}
            </select>
            <input className="input" style={{ width: 110 }} placeholder="value" value={String(s.value ?? "")} aria-label="Value"
              onChange={(e) => up(i, { value: e.target.value !== "" && !isNaN(Number(e.target.value)) ? Number(e.target.value) : e.target.value })} />
          </>}
          {s.action !== "restore" && <label className="small row">for <input className="input" type="number" min={1} style={{ width: 70 }} value={s.duration_s} onChange={(e) => up(i, { duration_s: Number(e.target.value) })} />s</label>}
          <button className="btn sm ghost danger" onClick={() => onChange(steps.filter((_, j) => j !== i))} aria-label="Remove"><Icon name="x" size={13} /></button>
        </div>
      ))}
      <div><button className="btn sm" onClick={() => devices[0] && onChange([...steps, { at_s: steps.length ? steps[steps.length - 1].at_s + 10 : 0, device_id: devices[0].id, action: "set", point: pointsOf(devices[0])[0], value: "", duration_s: 30 }])}>
        <Icon name="plus" size={13} />Step</button></div>
    </div>
  );
}

export function SimulationPage() {
  const { factory } = useFactory();
  const { can } = useAuth();
  const toast = useToast();
  const fid = factory?.id;
  const devices = useApi(() => (fid ? api.get<Device[]>(`/devices${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const assets = useApi(() => (fid ? api.get<Asset[]>(`/assets${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const types = useApi(() => api.get<AssetType[]>("/asset-types"), []);
  const scenarios = useApi(() => (fid ? api.get<Scenario[]>(`/simulation/scenarios${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const [run, setRun] = useState<ScenarioRun | null>(null);
  const [edit, setEdit] = useState<Partial<Scenario> | null>(null);
  const [del, setDel] = useState<Scenario | null>(null);
  const [inj, setInj] = useState<{ device_id: string; point: string; value: string; duration_s: number }>({ device_id: "", point: "", value: "", duration_s: 60 });
  const editable = can("factory.write");
  const sim = useMemo(() => (devices.data ?? []).filter((d) => d.protocol === "simulated" && d.enabled), [devices.data]);
  const assetById = useMemo(() => Object.fromEntries((assets.data ?? []).map((a) => [a.id, a])), [assets.data]);
  const typeById = useMemo(() => Object.fromEntries((types.data ?? []).map((t) => [t.id, t])), [types.data]);
  const fieldCount = (devices.data ?? []).filter((d) => d.protocol !== "simulated" && d.enabled).length;

  useEffect(() => {
    if (!fid) return;
    let stop = false;
    const tick = () => api.get<ScenarioRun | null>(`/simulation/status${qs({ factory_id: fid })}`).then((r) => !stop && setRun(r)).catch(() => {});
    void tick();
    const t = setInterval(tick, 1500);
    return () => { stop = true; clearInterval(t); };
  }, [fid]);

  const inject = async (action: "set" | "offline" | "restore") => {
    try {
      const body = { device_id: inj.device_id, action, point: inj.point, duration_s: inj.duration_s,
        value: inj.value !== "" && !isNaN(Number(inj.value)) ? Number(inj.value) : inj.value };
      const r = await api.post<{ message: string }>("/simulation/inject", body);
      toast("ok", r.message);
    } catch (e) { toast("bad", (e as Error).message); }
  };
  const save = async () => {
    try {
      const body = { factory_id: fid, name: edit!.name, description: edit!.description ?? "", steps: edit!.steps ?? [] };
      if (edit!.id) await api.put(`/simulation/scenarios/${edit!.id}`, body); else await api.post("/simulation/scenarios", body);
      setEdit(null); await scenarios.reload();
    } catch (e) { toast("bad", (e as Error).message); }
  };
  const start = async (s: Scenario) => {
    try { setRun(await api.post<ScenarioRun>(`/simulation/scenarios/${s.id}/run`)); toast("info", `Scenario '${s.name}' running`); }
    catch (e) { toast("bad", (e as Error).message); }
  };

  if (!factory || !fid) return <div className="panel"><Empty title="No factory selected" /></div>;
  if (!devices.data || !scenarios.data) return <Loading />;
  const injDev = sim.find((d) => d.id === inj.device_id);
  const injAsset = injDev?.asset_id ? assetById[injDev.asset_id] : undefined;
  const injDef = injAsset ? typeById[injAsset.asset_type_id]?.telemetry.find((t) => injDev?.point_mappings.find((m) => m.point === inj.point)?.measurement === t.key) : undefined;

  return (
    <>
      <div className="page-head">
        <div><h1>Simulation</h1><div className="sub">Rehearse alarms, interlocks and automations by injecting faults into <strong>simulated</strong> devices. Field devices ({fieldCount}) are never touched.</div></div>
        <div className="actions">{editable && <button className="btn primary" onClick={() => setEdit({ name: "", description: "", steps: [] })}><Icon name="plus" />New scenario</button>}</div>
      </div>
      {run && !run.done && (
        <div className="notice warn" style={{ marginBottom: 12 }}>
          <span><strong>Scenario running: {run.name}</strong> · t+{Math.round(run.elapsed_s)}s of {Math.round(run.duration_s)}s · started by {run.started_by}</span>
          {editable && <button className="btn sm right" onClick={async () => { await api.post(`/simulation/stop?factory_id=${fid}`); toast("ok", "Scenario stopped; devices restored"); }}>Stop &amp; restore</button>}
        </div>
      )}
      <div className="two-col">
        <section className="panel">
          <div className="panel-head"><h2>Scenarios</h2></div>
          <table className="table">
            <tbody>
              {scenarios.data.map((s) => (
                <tr key={s.id}>
                  <td><strong>{s.name}</strong><div className="faint small">{s.description} · {s.steps.length} step(s)</div></td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {editable && <button className="btn sm primary" disabled={!!run && !run.done} onClick={() => start(s)}>Run</button>}
                    {editable && <button className="btn sm ghost" onClick={() => setEdit(s)}>Edit</button>}
                    {editable && <button className="btn sm ghost danger" onClick={() => setDel(s)} aria-label="Delete"><Icon name="trash" size={13} /></button>}
                  </td>
                </tr>
              ))}
              {!scenarios.data.length && <tr><td className="faint">No scenarios yet.</td></tr>}
            </tbody>
          </table>
          {run && <><div className="section-title" style={{ margin: "14px" }}>Last run: {run.name} {run.done ? <Pill tone="neutral">finished</Pill> : <Pill tone="warn">running</Pill>}</div>
            <pre className="exec-detail" style={{ margin: "0 14px 14px" }}>{run.log.join("\n")}</pre></>}
        </section>
        <section className="panel">
          <div className="panel-head"><h2>Quick fault injection</h2></div>
          <div className="panel-body stack">
            <Field label="Simulated device">
              <select className="select" value={inj.device_id} onChange={(e) => { const d = sim.find((x) => x.id === e.target.value); setInj({ ...inj, device_id: e.target.value, point: pointsOf(d)[0] ?? "" }); }}>
                <option value="">Select…</option>{sim.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </Field>
            <div className="grid-2">
              <Field label="Point"><select className="select" value={inj.point} onChange={(e) => setInj({ ...inj, point: e.target.value })}>{pointsOf(injDev).map((p) => <option key={p}>{p}</option>)}</select></Field>
              <Field label="Forced value" help={injDef ? `${injDef.label}${injDef.unit ? ` (${injDef.unit})` : ""}${injDef.alarm_high != null ? ` · alarm ≥ ${injDef.alarm_high}` : ""}${injDef.options.length ? ` · ${injDef.options.join(", ")}` : ""}` : undefined}>
                <input className="input" value={inj.value} onChange={(e) => setInj({ ...inj, value: e.target.value })} />
              </Field>
              <Field label="Duration (s)"><input className="input" type="number" min={1} max={3600} value={inj.duration_s} onChange={(e) => setInj({ ...inj, duration_s: Number(e.target.value) })} /></Field>
            </div>
            <div className="row wrap">
              <button className="btn primary" disabled={!editable || !inj.device_id || inj.value === ""} onClick={() => inject("set")}>Force value</button>
              <button className="btn" disabled={!editable || !inj.device_id} onClick={() => inject("offline")}>Take offline</button>
              <button className="btn ghost" disabled={!editable || !inj.device_id} onClick={() => inject("restore")}>Restore</button>
            </div>
            <p className="faint small" style={{ margin: 0 }}>Values stay tagged <span className="sim-tag">SIM</span> everywhere. For field devices on the lab PLC, use the lab presenter panel instead.</p>
          </div>
        </section>
      </div>
      {edit && (
        <Modal wide title={edit.id ? "Edit scenario" : "New scenario"} onClose={() => setEdit(null)} footer={<>
          <button className="btn" onClick={() => setEdit(null)}>Cancel</button>
          <button className="btn primary" disabled={!edit.name || !(edit.steps ?? []).length} onClick={save}>Save</button></>}>
          <div className="stack">
            <div className="grid-2">
              <Field label="Name" required><input className="input" value={edit.name ?? ""} onChange={(e) => setEdit({ ...edit, name: e.target.value })} autoFocus /></Field>
              <Field label="Description"><input className="input" value={edit.description ?? ""} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
            </div>
            <StepsEditor steps={edit.steps ?? []} onChange={(steps) => setEdit({ ...edit, steps })} devices={sim} />
          </div>
        </Modal>
      )}
      {del && <Confirm title={`Delete '${del.name}'?`} message="The scenario definition is removed." onClose={() => setDel(null)}
        onConfirm={async () => { setDel(null); await api.del(`/simulation/scenarios/${del.id}`); await scenarios.reload(); }} />}
    </>
  );
}
