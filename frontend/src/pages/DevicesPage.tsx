import { Fragment, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, qs } from "../api/client";
import { Asset, AssetType, ConfigField, Device, DiscoveredPoint, PointMapping, Protocol, TestResult } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { useToast } from "../components/Toast";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal, Pill } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { timeAgo } from "../lib/format";
import { useApi } from "../lib/useApi";
import { TestPill } from "./AssetsPage";

// ---------- Building blocks ----------
function ConfigForm({ schema, values, onChange, secrets, onSecrets, hasStoredSecrets }: {
  schema: ConfigField[]; values: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void;
  secrets: Record<string, string>; onSecrets: (v: Record<string, string>) => void; hasStoredSecrets?: boolean;
}) {
  const input = (f: ConfigField) => {
    if (f.secret) {
      return <input className="input" type="password" autoComplete="new-password" value={secrets[f.key] ?? ""}
        placeholder={hasStoredSecrets ? "•••••• stored (leave blank to keep)" : ""} onChange={(e) => onSecrets({ ...secrets, [f.key]: e.target.value })} />;
    }
    const v = values[f.key] ?? f.default;
    if (f.type === "boolean") return <label className="check"><input type="checkbox" checked={v === true} onChange={(e) => onChange({ ...values, [f.key]: e.target.checked })} />{v ? "Yes" : "No"}</label>;
    if (f.type === "enum") return <select className="select" value={String(v ?? "")} onChange={(e) => onChange({ ...values, [f.key]: e.target.value })}>{f.options.map((o) => <option key={o}>{o}</option>)}</select>;
    if (f.type === "integer" || f.type === "number")
      return <input className="input" type="number" step={f.type === "integer" ? 1 : "any"} value={v === null || v === undefined ? "" : String(v)}
        onChange={(e) => onChange({ ...values, [f.key]: e.target.value === "" ? null : Number(e.target.value) })} />;
    return <input className="input" value={String(v ?? "")} onChange={(e) => onChange({ ...values, [f.key]: e.target.value })} />;
  };
  return (
    <div className="grid-2">
      {schema.map((f) => <Field key={f.key} label={f.label} required={f.required} help={f.help || (f.secret ? "Encrypted at rest; never shown again" : undefined)}>{input(f)}</Field>)}
    </div>
  );
}

function MappingEditor({ mappings, onChange, type, discovered }: {
  mappings: PointMapping[]; onChange: (m: PointMapping[]) => void; type?: AssetType; discovered: DiscoveredPoint[];
}) {
  const measurements = type?.telemetry ?? [];
  const addDiscovered = (p: DiscoveredPoint) => {
    const guess = measurements.find((m) => m.key === p.suggested_measurement || m.key === p.point);
    onChange([...mappings, { point: p.point, measurement: guess?.key ?? measurements[0]?.key ?? "", scale: 1, offset: 0 }]);
  };
  const unmapped = discovered.filter((p) => !mappings.some((m) => m.point === p.point));
  return (
    <div className="stack">
      {!type && <div className="notice warn"><span>Bind this device to an asset first. Points map onto that asset's measurements.</span></div>}
      {unmapped.length > 0 && (
        <div>
          <div className="section-title">Discovered points</div>
          <div className="row wrap">
            {unmapped.map((p) => (
              <button key={p.point} className="btn sm" onClick={() => addDiscovered(p)} disabled={!type}>
                <Icon name="plus" size={13} />{p.label} <span className="faint mono">{p.point}{p.unit ? ` · ${p.unit}` : ""}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <table className="table def-table">
        <thead><tr><th>Device point / address</th><th>→ Asset measurement</th><th style={{ width: 80 }}>Scale</th><th style={{ width: 80 }}>Offset</th><th style={{ width: 40 }} /></tr></thead>
        <tbody>
          {mappings.map((m, i) => {
            const upd = (patch: Partial<PointMapping>) => onChange(mappings.map((x, j) => (j === i ? { ...x, ...patch } : x)));
            return (
              <tr key={i}>
                <td><input className="input mono" value={m.point} onChange={(e) => upd({ point: e.target.value })} aria-label="Point" /></td>
                <td>
                  <select className="select" value={m.measurement} onChange={(e) => upd({ measurement: e.target.value })} aria-label="Measurement">
                    {!measurements.some((x) => x.key === m.measurement) && <option value={m.measurement}>{m.measurement || "Select…"}</option>}
                    {measurements.map((x) => <option key={x.key} value={x.key}>{x.label}{x.unit ? ` (${x.unit})` : ""}</option>)}
                  </select>
                </td>
                <td><input className="input" type="number" step="any" value={m.scale} onChange={(e) => upd({ scale: Number(e.target.value) })} aria-label="Scale" /></td>
                <td><input className="input" type="number" step="any" value={m.offset} onChange={(e) => upd({ offset: Number(e.target.value) })} aria-label="Offset" /></td>
                <td><button className="btn sm ghost danger" onClick={() => onChange(mappings.filter((_, j) => j !== i))} aria-label="Remove"><Icon name="x" size={13} /></button></td>
              </tr>
            );
          })}
          {!mappings.length && <tr><td colSpan={5} className="faint">No points mapped yet.</td></tr>}
        </tbody>
      </table>
      <div><button className="btn sm" disabled={!type} onClick={() => onChange([...mappings, { point: "", measurement: measurements[0]?.key ?? "", scale: 1, offset: 0 }])}><Icon name="plus" size={13} />Add mapping manually</button></div>
      <p className="faint small" style={{ margin: 0 }}>value = raw × scale + offset</p>
    </div>
  );
}

function TestBox({ result }: { result: TestResult | null }) {
  if (!result) return null;
  return (
    <div className={`notice ${result.ok ? "info" : "bad"}`} role="status">
      <Icon name={result.ok ? "check" : "x"} />
      <span><strong>{result.ok ? "Connection OK" : "Connection failed"}</strong> · {result.message}{result.latency_ms !== null ? ` · ${result.latency_ms} ms` : ""}</span>
    </div>
  );
}

// ---------- Onboarding wizard ----------
const STEPS = ["Basics", "Protocol", "Connection", "Test", "Map points", "Activate"];

function OnboardingWizard({ factoryId, assets, types, protocols, presetAsset, onClose, onDone }: {
  factoryId: string; assets: Asset[]; types: AssetType[]; protocols: Protocol[]; presetAsset?: string;
  onClose: () => void; onDone: () => void;
}) {
  const toast = useToast();
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [assetId, setAssetId] = useState(presetAsset ?? "");
  const [protocol, setProtocol] = useState<Protocol | null>(null);
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [device, setDevice] = useState<Device | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [discovered, setDiscovered] = useState<DiscoveredPoint[]>([]);
  const [mappings, setMappings] = useState<PointMapping[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const asset = assets.find((a) => a.id === assetId);
  const type = types.find((t) => t.id === asset?.asset_type_id);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setErr(null);
    try { await fn(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  const pickProtocol = (p: Protocol) => {
    setProtocol(p);
    setConfig(Object.fromEntries(p.config_schema.filter((f) => !f.secret && f.default !== null).map((f) => [f.key, f.default])));
  };

  // Persist as a disabled device, then test. Re-entering the step updates the same device.
  const saveAndTest = () => run(async () => {
    const creds = Object.fromEntries(Object.entries(secrets).filter(([, v]) => v));
    const body = { name, asset_id: assetId || null, connection_config: config, ...(Object.keys(creds).length ? { credentials: creds } : {}) };
    const d = device
      ? await api.patch<Device>(`/devices/${device.id}`, body)
      : await api.post<Device>("/devices", { ...body, factory_id: factoryId, protocol: protocol!.key, enabled: false });
    setDevice(d);
    setStep(3);
    const r = await api.post<TestResult>(`/devices/${d.id}/test`);
    setTest(r);
    if (r.ok && protocol!.supports_discovery) {
      const pts = await api.post<DiscoveredPoint[]>(`/devices/${d.id}/discover`);
      setDiscovered(pts);
    }
  });

  const retest = () => run(async () => { setTest(await api.post<TestResult>(`/devices/${device!.id}/test`)); });

  const saveMappings = () => run(async () => {
    setDevice(await api.patch<Device>(`/devices/${device!.id}`, { point_mappings: mappings }));
    setStep(5);
  });

  const finish = (enable: boolean) => run(async () => {
    if (enable) await api.patch(`/devices/${device!.id}`, { enabled: true });
    toast("ok", `${name} ${enable ? "activated" : "saved (inactive)"}`);
    onDone();
  });

  const canNext = [name.trim().length > 0, !!protocol, true][step] ?? true;

  return (
    <Modal wide title="Connect a device" onClose={onClose} footer={
      <>
        {step > 0 && step < 5 && step !== 3 && <button className="btn ghost" style={{ marginRight: "auto" }} onClick={() => setStep(step - 1)}>Back</button>}
        {step === 3 && <button className="btn ghost" style={{ marginRight: "auto" }} onClick={() => setStep(2)}>Edit connection</button>}
        {step < 2 && <button className="btn primary" disabled={!canNext} onClick={() => setStep(step + 1)}>Next</button>}
        {step === 2 && <button className="btn primary" disabled={busy} onClick={saveAndTest}>{busy ? "Testing…" : "Save & test connection"}</button>}
        {step === 3 && <>
          <button className="btn" disabled={busy} onClick={retest}><Icon name="refresh" size={14} />Test again</button>
          <button className="btn primary" disabled={!test?.ok} onClick={() => setStep(4)} title={test?.ok ? "" : "Connection must pass first"}>Next</button>
        </>}
        {step === 4 && <>
          <button className="btn ghost" onClick={() => setStep(5)}>Skip for now</button>
          <button className="btn primary" disabled={busy || mappings.some((m) => !m.point || !m.measurement)} onClick={saveMappings}>Save mappings</button>
        </>}
        {step === 5 && <>
          <button className="btn" disabled={busy} onClick={() => finish(false)}>Keep inactive</button>
          <button className="btn primary" disabled={busy} onClick={() => finish(true)}>Activate device</button>
        </>}
      </>
    }>
      <div className="steps">
        {STEPS.map((s, i) => (
          <div key={s} className={`step${i < step ? " done" : i === step ? " current" : ""}`}>
            <span className="n">{i < step ? "✓" : i + 1}</span>{s}
          </div>
        ))}
      </div>

      {step === 0 && (
        <div className="stack">
          <Field label="Device name" required help="e.g. 'Line 1 coolant temperature transmitter'">
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </Field>
          <Field label="Digital twin asset" help="The asset this device reports for. Its asset type decides which measurements can be mapped.">
            <select className="select" value={assetId} onChange={(e) => setAssetId(e.target.value)}>
              <option value="">Not bound yet</option>
              {assets.map((a) => <option key={a.id} value={a.id}>{a.code} – {a.name} ({a.asset_type.name})</option>)}
            </select>
          </Field>
          {type && <p className="faint small" style={{ margin: 0 }}>{type.name} measurements: {type.telemetry.map((t) => t.label).join(", ") || "none"}</p>}
        </div>
      )}

      {step === 1 && (
        <div className="stack">
          <div className="choice-grid">
            {protocols.map((p) => (
              <button key={p.key} className={`choice${protocol?.key === p.key ? " selected" : ""}`} disabled={p.status !== "available"} onClick={() => pickProtocol(p)}>
                <div className="t">{p.name}</div>
                <div className="d">{p.status === "available" ? p.description : p.description || "Planned"}</div>
              </button>
            ))}
          </div>
          <p className="faint small" style={{ margin: 0 }}>Greyed-out protocols aren't implemented yet. Some need edge-gateway hardware (serial, fieldbus).</p>
        </div>
      )}

      {step === 2 && protocol && (
        <div className="stack">
          {protocol.key === "simulated" && <div className="notice"><Pill tone="sim">Simulated</Pill><span>Generates software values only and never contacts real equipment.</span></div>}
          <ConfigForm schema={protocol.config_schema} values={config} onChange={setConfig} secrets={secrets} onSecrets={setSecrets} />
        </div>
      )}

      {step === 3 && (
        <div className="stack">
          {busy && <Loading label="Contacting device…" />}
          <TestBox result={test} />
          {test?.ok && discovered.length > 0 && <p className="muted" style={{ margin: 0 }}>Found {discovered.length} data point(s). Next, map them to the asset's measurements.</p>}
        </div>
      )}

      {step === 4 && <MappingEditor mappings={mappings} onChange={setMappings} type={type} discovered={discovered} />}

      {step === 5 && device && (
        <div className="stack">
          <dl className="kv">
            <dt>Device</dt><dd>{device.name}</dd>
            <dt>Asset</dt><dd>{asset ? `${asset.code} – ${asset.name}` : "Not bound"}</dd>
            <dt>Protocol</dt><dd>{protocol?.name}</dd>
            <dt>Connection test</dt><dd><TestPill status={device.last_test_status} /></dd>
            <dt>Mapped points</dt><dd>{device.point_mappings.length}</dd>
          </dl>
          <div className="notice"><span>Activating marks the device for data collection. Ingestion and live values arrive in Phase 4. Until then the device is configured and tested, but no telemetry is collected.</span></div>
        </div>
      )}
      {err && <div className="notice bad" style={{ marginTop: 12 }}>{err}</div>}
    </Modal>
  );
}

// ---------- Device detail ----------
function DeviceDetail({ device, assets, types, protocols, onClose, onChanged }: {
  device: Device; assets: Asset[]; types: AssetType[]; protocols: Protocol[]; onClose: () => void; onChanged: () => void;
}) {
  const { can } = useAuth();
  const toast = useToast();
  const editable = can("device.write");
  const proto = protocols.find((p) => p.key === device.protocol);
  const [d, setD] = useState(device);
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [test, setTest] = useState<TestResult | null>(null);
  const [discovered, setDiscovered] = useState<DiscoveredPoint[]>([]);
  const [confirmDel, setConfirmDel] = useState(false);
  const [busy, setBusy] = useState(false);
  const asset = assets.find((a) => a.id === d.asset_id);
  const type = types.find((t) => t.id === asset?.asset_type_id);

  const save = async () => {
    setBusy(true);
    try {
      const creds = Object.fromEntries(Object.entries(secrets).filter(([, v]) => v));
      const body = { name: d.name, asset_id: d.asset_id, connection_config: d.connection_config, point_mappings: d.point_mappings, enabled: d.enabled,
        ...(Object.keys(creds).length ? { credentials: creds } : {}) };
      setD(await api.patch<Device>(`/devices/${d.id}`, body));
      setSecrets({});
      toast("ok", "Device saved");
      onChanged();
    } catch (e) { toast("bad", (e as Error).message); } finally { setBusy(false); }
  };
  const runTest = async () => {
    setBusy(true);
    try {
      const r = await api.post<TestResult>(`/devices/${d.id}/test`);
      setTest(r);
      if (r.ok && proto?.supports_discovery) setDiscovered(await api.post<DiscoveredPoint[]>(`/devices/${d.id}/discover`));
      onChanged();
    } catch (e) { toast("bad", (e as Error).message); } finally { setBusy(false); }
  };

  return (
    <Modal wide title={<span className="row">{device.name}{device.protocol === "simulated" && <Pill tone="sim">Simulated</Pill>}</span>} onClose={onClose}
      footer={<>
        {editable && <button className="btn danger" style={{ marginRight: "auto" }} onClick={() => setConfirmDel(true)}>Delete</button>}
        {can("device.test") && <button className="btn" onClick={runTest} disabled={busy}><Icon name="plug" size={14} />Test connection</button>}
        {editable && <button className="btn primary" onClick={save} disabled={busy}>Save</button>}
      </>}>
      <div className="stack">
        <TestBox result={test} />
        <div className="grid-2">
          <Field label="Name"><input className="input" value={d.name} disabled={!editable} onChange={(e) => setD({ ...d, name: e.target.value })} /></Field>
          <Field label="Asset">
            <select className="select" value={d.asset_id ?? ""} disabled={!editable} onChange={(e) => setD({ ...d, asset_id: e.target.value || null })}>
              <option value="">Not bound</option>
              {assets.map((a) => <option key={a.id} value={a.id}>{a.code} – {a.name}</option>)}
            </select>
          </Field>
        </div>
        <label className="check"><input type="checkbox" checked={d.enabled} disabled={!editable} onChange={(e) => setD({ ...d, enabled: e.target.checked })} />Active (collect data once ingestion is available)</label>
        <div className="section-title">Connection · {proto?.name ?? d.protocol}</div>
        {proto && editable ? (
          <ConfigForm schema={proto.config_schema} values={d.connection_config} onChange={(c) => setD({ ...d, connection_config: c })}
            secrets={secrets} onSecrets={setSecrets} hasStoredSecrets={d.has_credentials} />
        ) : (
          <dl className="kv">{Object.entries(d.connection_config).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd className="mono">{String(v)}</dd></Fragment>)}</dl>
        )}
        <div className="faint small">Last test: <TestPill status={device.last_test_status} /> {device.last_test_message && `· ${device.last_test_message}`} · {timeAgo(device.last_test_at)}</div>
        <div className="section-title">Point mappings</div>
        <MappingEditor mappings={d.point_mappings} onChange={(m) => setD({ ...d, point_mappings: m })} type={type} discovered={discovered} />
      </div>
      {confirmDel && (
        <Confirm title={`Delete ${device.name}?`} message="The device configuration and stored credentials will be removed." onClose={() => setConfirmDel(false)}
          onConfirm={async () => { try { await api.del(`/devices/${device.id}`); toast("ok", "Device deleted"); onChanged(); onClose(); } catch (e) { toast("bad", (e as Error).message); } }} />
      )}
    </Modal>
  );
}

// ---------- Page ----------
export function DevicesPage() {
  const { factory } = useFactory();
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const assetFilter = params.get("asset") ?? "";
  const [wizard, setWizard] = useState(false);
  const [open, setOpen] = useState<Device | null>(null);
  const fid = factory?.id;
  const devices = useApi(() => (fid ? api.get<Device[]>(`/devices${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const assets = useApi(() => (fid ? api.get<Asset[]>(`/assets${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const types = useApi(() => api.get<AssetType[]>("/asset-types"), []);
  const protocols = useApi(() => api.get<Protocol[]>("/protocols"), []);
  const assetById = useMemo(() => Object.fromEntries((assets.data ?? []).map((a) => [a.id, a])), [assets.data]);

  if (!factory) return <div className="panel"><Empty title="No factory selected" /></div>;
  const list = (devices.data ?? []).filter((d) => !assetFilter || d.asset_id === assetFilter);
  const ready = assets.data && types.data && protocols.data;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Devices</h1>
          <div className="sub">Data sources and control endpoints. Industrial I/O always goes through the backend or an edge gateway, never the browser.</div>
        </div>
        <div className="actions">
          {can("device.write") && <button className="btn primary" disabled={!ready} onClick={() => setWizard(true)}><Icon name="plug" />Connect device</button>}
        </div>
      </div>
      {devices.error && <ErrorNote error={devices.error} onRetry={devices.reload} />}
      {assetFilter && (
        <div className="notice" style={{ marginBottom: 12 }}>
          <span>Showing devices for <strong>{assetById[assetFilter]?.code ?? "asset"}</strong>.</span>
          <button className="btn sm right" onClick={() => setParams({})}>Show all</button>
        </div>
      )}
      <section className="panel">
        {!devices.data ? <Loading /> : list.length === 0 ? (
          <Empty title="No devices yet" action={can("device.write") && ready ? <button className="btn primary" onClick={() => setWizard(true)}>Connect a device</button> : undefined}>
            Connect a sensor, meter or controller, or start with a simulated device.
          </Empty>
        ) : (
          <table className="table">
            <thead><tr><th>Device</th><th>Asset</th><th>Protocol</th><th className="num">Points</th><th>Status</th><th>Connection test</th><th>Tested</th></tr></thead>
            <tbody>
              {list.map((d) => {
                const a = d.asset_id ? assetById[d.asset_id] : undefined;
                return (
                  <tr key={d.id} className="clickable" onClick={() => setOpen(d)}>
                    <td style={{ fontWeight: 550 }}>{d.name}</td>
                    <td>{a ? <Link to={`/assets/${a.id}`} onClick={(e) => e.stopPropagation()}><span className="code-chip">{a.code}</span></Link> : <span className="faint">—</span>}</td>
                    <td>{d.protocol === "simulated" ? <Pill tone="sim">Simulated</Pill> : d.protocol}</td>
                    <td className="num">{d.point_mappings.length}</td>
                    <td>{d.enabled ? <Pill tone="info">Active</Pill> : <Pill tone="neutral">Inactive</Pill>}</td>
                    <td><TestPill status={d.last_test_status} /></td>
                    <td className="faint small">{timeAgo(d.last_test_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {wizard && ready && (
        <OnboardingWizard factoryId={factory.id} assets={assets.data!} types={types.data!} protocols={protocols.data!} presetAsset={assetFilter || undefined}
          onClose={() => { setWizard(false); void devices.reload(); }} onDone={() => { setWizard(false); void devices.reload(); }} />
      )}
      {open && ready && (
        <DeviceDetail key={open.id} device={open} assets={assets.data!} types={types.data!} protocols={protocols.data!}
          onClose={() => setOpen(null)} onChanged={() => void devices.reload()} />
      )}
    </>
  );
}
