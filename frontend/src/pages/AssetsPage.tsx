import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError, api, qs } from "../api/client";
import { Asset, AssetType, AuditEntry, Device, FactoryStructure, Lifecycle } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { defaultsFor, DynamicForm, validateAll } from "../components/DynamicForm";
import { Icon } from "../components/Icon";
import { useToast } from "../components/Toast";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal, Pill, Tabs } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { fmtDateTime, formatValue, timeAgo, titleCase } from "../lib/format";
import { useApi } from "../lib/useApi";

const LIFECYCLE: Lifecycle[] = ["active", "maintenance", "decommissioned"];
const lifecycleTone = (l: string) => (l === "active" ? "ok" : l === "maintenance" ? "warn" : "neutral");

type AreaOpt = { id: string; label: string };

function useAreaOptions(structure?: FactoryStructure): AreaOpt[] {
  return useMemo(
    () => (structure?.floors ?? []).flatMap((f) => f.areas.map((a) => ({ id: a.id, label: structure!.floors.length > 1 ? `${f.name} / ${a.name}` : a.name }))),
    [structure],
  );
}

// ---------- Create / duplicate ----------
function CreateAssetModal({ factoryId, types, areas, assets, from, onClose, onCreated }: {
  factoryId: string; types: AssetType[]; areas: AreaOpt[]; assets: Asset[]; from?: Asset;
  onClose: () => void; onCreated: (a: Asset) => void;
}) {
  const [typeId, setTypeId] = useState<string | null>(from?.asset_type_id ?? null);
  const [search, setSearch] = useState("");
  const t = types.find((x) => x.id === typeId);
  const [g, setG] = useState({
    code: from ? `${from.code}-COPY` : "", name: from ? `${from.name} (copy)` : "",
    area_id: from?.area_id ?? "", parent_id: from?.parent_id ?? "",
    manufacturer: from?.manufacturer ?? "", model: from?.model ?? "", description: from?.description ?? "",
  });
  const [props, setProps] = useState<Record<string, unknown>>(from?.properties ?? {});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const pickType = (x: AssetType) => { setTypeId(x.id); setProps(defaultsFor(x.property_schema)); };
  const filtered = types.filter((x) => `${x.name} ${x.category}`.toLowerCase().includes(search.toLowerCase()));
  const cats = [...new Set(filtered.map((x) => x.category))];

  const save = async () => {
    if (!t) return;
    const e = validateAll(t.property_schema, props);
    setErrors(e);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      const body = { ...g, factory_id: factoryId, asset_type_id: t.id, area_id: g.area_id || null, parent_id: g.parent_id || null,
        properties: Object.fromEntries(Object.entries(props).filter(([, v]) => v !== null && v !== "")) };
      onCreated(await api.post<Asset>("/assets", body));
    } catch (ex) {
      if (ex instanceof ApiError) setErrors(ex.fieldErrors);
      setErr((ex as Error).message);
    } finally { setBusy(false); }
  };

  return (
    <Modal wide title={from ? `Duplicate ${from.code}` : t ? `New ${t.name}` : "Add asset"} onClose={onClose}
      footer={t && <>
        {!from && <button className="btn ghost" onClick={() => setTypeId(null)} style={{ marginRight: "auto" }}>Change type</button>}
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" onClick={save} disabled={busy || !g.code.trim() || !g.name.trim()}>Create asset</button>
      </>}>
      {!t ? (
        <div className="stack">
          <input className="input" placeholder="Search asset types…" value={search} onChange={(e) => setSearch(e.target.value)} autoFocus />
          {cats.map((c) => (
            <div key={c}>
              <div className="section-title">{titleCase(c)}</div>
              <div className="choice-grid">
                {filtered.filter((x) => x.category === c).map((x) => (
                  <button key={x.id} className="choice" onClick={() => pickType(x)}>
                    <div className="t"><span className="swatch" style={{ background: x.visual.color, marginRight: 6 }} />{x.name}</div>
                    <div className="d">{x.property_schema.length} properties · {x.telemetry.length} measurements</div>
                  </button>
                ))}
              </div>
            </div>
          ))}
          {!filtered.length && <p className="faint">No matching types. Create one under Asset types.</p>}
        </div>
      ) : (
        <div className="stack">
          <div className="grid-2">
            <Field label="Asset ID" required help="Unique tag, e.g. MTR-104" error={errors.code}>
              <input className="input mono" value={g.code} onChange={(e) => setG({ ...g, code: e.target.value })} autoFocus />
            </Field>
            <Field label="Name" required error={errors.name}><input className="input" value={g.name} onChange={(e) => setG({ ...g, name: e.target.value })} /></Field>
            <Field label="Area">
              <select className="select" value={g.area_id} onChange={(e) => setG({ ...g, area_id: e.target.value })}>
                <option value="">Unassigned</option>
                {areas.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
              </select>
            </Field>
            <Field label="Parent asset" help="e.g. the line or machine this belongs to">
              <select className="select" value={g.parent_id} onChange={(e) => setG({ ...g, parent_id: e.target.value })}>
                <option value="">None</option>
                {assets.map((a) => <option key={a.id} value={a.id}>{a.code} – {a.name}</option>)}
              </select>
            </Field>
            <Field label="Manufacturer"><input className="input" value={g.manufacturer} onChange={(e) => setG({ ...g, manufacturer: e.target.value })} /></Field>
            <Field label="Model"><input className="input" value={g.model} onChange={(e) => setG({ ...g, model: e.target.value })} /></Field>
          </div>
          <div className="section-title">{t.name} properties</div>
          <DynamicForm schema={t.property_schema} values={props} onChange={setProps} errors={errors} />
          {err && <div className="notice bad">{err}</div>}
        </div>
      )}
    </Modal>
  );
}

// ---------- Detail panel ----------
function AssetDetail({ asset, type, areas, assets, onChanged, onDeleted, onDuplicate }: {
  asset: Asset; type?: AssetType; areas: AreaOpt[]; assets: Asset[];
  onChanged: (a: Asset) => void; onDeleted: () => void; onDuplicate: () => void;
}) {
  const { can } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const editable = can("asset.write");
  const [tab, setTab] = useState<"details" | "telemetry" | "devices" | "history">("details");
  const [draft, setDraft] = useState(asset);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [confirmDel, setConfirmDel] = useState(false);
  const [saving, setSaving] = useState(false);
  useEffect(() => { setDraft(asset); setErrors({}); }, [asset]);

  const devices = useApi(() => api.get<Device[]>(`/devices${qs({ asset_id: asset.id })}`), [asset.id]);
  const history = useApi(() => (can("audit.read") && tab === "history" ? api.get<AuditEntry[]>(`/audit${qs({ entity_id: asset.id })}`) : Promise.resolve([])), [asset.id, asset.version, tab]);
  const children = assets.filter((a) => a.parent_id === asset.id);

  const fields = ["code", "name", "description", "manufacturer", "model", "serial_number", "area_id", "parent_id", "lifecycle_status", "tags", "properties"] as const;
  const dirty = fields.some((k) => JSON.stringify(draft[k]) !== JSON.stringify(asset[k]));
  const set = <K extends keyof Asset>(k: K, v: Asset[K]) => setDraft({ ...draft, [k]: v });

  const save = async () => {
    if (type) {
      const e = validateAll(type.property_schema, draft.properties);
      setErrors(e);
      if (Object.keys(e).length) return;
    }
    const body: Record<string, unknown> = { version: asset.version };
    for (const k of fields) if (JSON.stringify(draft[k]) !== JSON.stringify(asset[k])) body[k] = draft[k];
    if ("properties" in body) body.properties = Object.fromEntries(Object.entries(draft.properties).filter(([, v]) => v !== null && v !== ""));
    setSaving(true);
    try {
      onChanged(await api.patch<Asset>(`/assets/${asset.id}`, body));
      toast("ok", `${draft.code} saved`);
    } catch (ex) {
      if (ex instanceof ApiError) setErrors(ex.fieldErrors);
      toast("bad", (ex as Error).message);
    } finally { setSaving(false); }
  };

  const del = async () => {
    try { await api.del(`/assets/${asset.id}`); toast("ok", `${asset.code} deleted`); onDeleted(); }
    catch (ex) { toast("bad", (ex as Error).message); }
  };

  return (
    <section className="panel" style={{ position: "sticky", top: 0 }}>
      <div className="panel-head" style={{ alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <div className="row"><span className="code-chip">{asset.code}</span><Pill tone={lifecycleTone(asset.lifecycle_status)}>{titleCase(asset.lifecycle_status)}</Pill></div>
          <h2 style={{ marginTop: 6 }}>{asset.name}</h2>
          <div className="faint small">{asset.asset_type.name} · v{asset.version} · updated {timeAgo(asset.updated_at)}</div>
        </div>
        {editable && (
          <div className="row right">
            <button className="btn sm ghost" onClick={onDuplicate} title="Duplicate"><Icon name="copy" size={14} /></button>
            <button className="btn sm ghost danger" onClick={() => setConfirmDel(true)} title="Delete"><Icon name="trash" size={14} /></button>
          </div>
        )}
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[
        { key: "details", label: "Details" },
        { key: "telemetry", label: `Telemetry (${type?.telemetry.length ?? 0})` },
        { key: "devices", label: `Devices (${devices.data?.length ?? "…"})` },
        ...(can("audit.read") ? [{ key: "history" as const, label: "History" }] : []),
      ]} />
      <div className="panel-body">
        {tab === "details" && (
          <div className="stack">
            <div className="section-title">General</div>
            <div className="grid-2">
              <Field label="Asset ID" required error={errors.code}><input className="input mono" value={draft.code} disabled={!editable} onChange={(e) => set("code", e.target.value)} /></Field>
              <Field label="Name" required error={errors.name}><input className="input" value={draft.name} disabled={!editable} onChange={(e) => set("name", e.target.value)} /></Field>
              <Field label="Area">
                <select className="select" value={draft.area_id ?? ""} disabled={!editable} onChange={(e) => set("area_id", e.target.value || null)}>
                  <option value="">Unassigned</option>
                  {areas.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
                </select>
              </Field>
              <Field label="Parent asset">
                <select className="select" value={draft.parent_id ?? ""} disabled={!editable} onChange={(e) => set("parent_id", e.target.value || null)}>
                  <option value="">None</option>
                  {assets.filter((a) => a.id !== asset.id).map((a) => <option key={a.id} value={a.id}>{a.code} – {a.name}</option>)}
                </select>
              </Field>
              <Field label="Lifecycle">
                <select className="select" value={draft.lifecycle_status} disabled={!editable} onChange={(e) => set("lifecycle_status", e.target.value as Lifecycle)}>
                  {LIFECYCLE.map((l) => <option key={l} value={l}>{titleCase(l)}</option>)}
                </select>
              </Field>
              <Field label="Tags" help="Comma separated">
                <input className="input" value={draft.tags.join(", ")} disabled={!editable}
                  onChange={(e) => set("tags", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
              </Field>
              <Field label="Manufacturer"><input className="input" value={draft.manufacturer} disabled={!editable} onChange={(e) => set("manufacturer", e.target.value)} /></Field>
              <Field label="Model"><input className="input" value={draft.model} disabled={!editable} onChange={(e) => set("model", e.target.value)} /></Field>
              <Field label="Serial number"><input className="input" value={draft.serial_number} disabled={!editable} onChange={(e) => set("serial_number", e.target.value)} /></Field>
            </div>
            <Field label="Description"><textarea className="input" value={draft.description} disabled={!editable} onChange={(e) => set("description", e.target.value)} /></Field>
            <div className="section-title">{asset.asset_type.name} properties</div>
            {type ? <DynamicForm schema={type.property_schema} values={draft.properties} errors={errors} disabled={!editable}
              onChange={(p) => set("properties", p)} /> : <Loading />}
            {children.length > 0 && (
              <>
                <div className="section-title">Contains</div>
                <div className="row wrap">
                  {children.map((c) => <button key={c.id} className="btn sm" onClick={() => navigate(`/assets/${c.id}`)}>{c.code}</button>)}
                </div>
              </>
            )}
            {editable && (
              <div className="row" style={{ justifyContent: "flex-end", borderTop: "1px solid var(--border)", paddingTop: 12 }}>
                {dirty && <span className="faint small" style={{ marginRight: "auto" }}>Unsaved changes</span>}
                <button className="btn" disabled={!dirty} onClick={() => { setDraft(asset); setErrors({}); }}>Revert</button>
                <button className="btn primary" disabled={!dirty || saving} onClick={save}>Save changes</button>
              </div>
            )}
          </div>
        )}

        {tab === "telemetry" && type && (
          <div className="stack">
            <div className="notice"><span>Measurements defined by the <strong>{type.name}</strong> type. Values stay empty until live ingestion (Phase 4). Nothing on this tab is estimated.</span></div>
            <table className="table">
              <thead><tr><th>Measurement</th><th>Unit</th><th>Warn</th><th>Alarm</th><th>Mapped from</th><th className="num">Value</th></tr></thead>
              <tbody>
                {type.telemetry.map((m) => {
                  const src = (devices.data ?? []).flatMap((d) => d.point_mappings.filter((p) => p.measurement === m.key).map(() => d.name));
                  return (
                    <tr key={m.key}>
                      <td>{m.label} <span className="faint mono">{m.key}</span></td>
                      <td className="muted">{m.unit || "—"}</td>
                      <td className="muted">{[m.warn_low, m.warn_high].map((v) => formatValue(v)).join(" / ")}</td>
                      <td className="muted">{[m.alarm_low, m.alarm_high].map((v) => formatValue(v)).join(" / ")}</td>
                      <td>{src.length ? src.join(", ") : <span className="faint">not mapped</span>}</td>
                      <td className="num"><Pill tone="neutral" dot={false}>no data</Pill></td>
                    </tr>
                  );
                })}
                {!type.telemetry.length && <tr><td colSpan={6} className="faint">This type defines no measurements.</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        {tab === "devices" && (
          <div className="stack">
            {(devices.data ?? []).map((d) => (
              <div key={d.id} className="row" style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                <Icon name="plug" />
                <div>
                  <div style={{ fontWeight: 550 }}>{d.name}</div>
                  <div className="faint small">{d.protocol} · {d.point_mappings.length} mapped point(s)</div>
                </div>
                <div className="right row">
                  {d.protocol === "simulated" && <Pill tone="sim">Simulated</Pill>}
                  <TestPill status={d.last_test_status} />
                </div>
              </div>
            ))}
            {devices.data?.length === 0 && <p className="faint" style={{ margin: 0 }}>No devices are bound to this asset.</p>}
            <div><button className="btn sm" onClick={() => navigate(`/devices?asset=${asset.id}`)}><Icon name="plug" size={14} />Manage devices</button></div>
          </div>
        )}

        {tab === "history" && (
          <div className="stack">
            {(history.data ?? []).map((h) => (
              <div key={h.id} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
                <div>{h.summary}</div>
                <div className="faint small">{h.user_email} · {fmtDateTime(h.at)}</div>
              </div>
            ))}
            {history.loading && <Loading />}
          </div>
        )}
      </div>
      {confirmDel && <Confirm title={`Delete ${asset.code}?`} onClose={() => setConfirmDel(false)} onConfirm={del}
        message="Child assets will be detached and bound devices will be unbound. A snapshot is kept in the audit log." />}
    </section>
  );
}

export function TestPill({ status }: { status: string }) {
  if (status === "ok") return <Pill tone="ok">Test passed</Pill>;
  if (status === "error") return <Pill tone="bad">Test failed</Pill>;
  return <Pill tone="neutral">Not tested</Pill>;
}

// ---------- Page ----------
export function AssetsPage() {
  const { factory } = useFactory();
  const { can } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const { assetId } = useParams();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const category = params.get("category") ?? "";
  const area = params.get("area") ?? "";
  const [creating, setCreating] = useState<null | { from?: Asset }>(null);

  const fid = factory?.id;
  const assets = useApi(() => (fid ? api.get<Asset[]>(`/assets${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const types = useApi(() => api.get<AssetType[]>("/asset-types"), []);
  const structure = useApi(() => (fid ? api.get<FactoryStructure>(`/factories/${fid}`) : Promise.resolve(undefined)), [fid]);
  const areas = useAreaOptions(structure.data);
  const areaName = useMemo(() => Object.fromEntries(areas.map((a) => [a.id, a.label])), [areas]);

  const all = assets.data ?? [];
  const list = all.filter((a) =>
    (!category || a.asset_type.category === category) &&
    (!area || (area === "unassigned" ? !a.area_id : a.area_id === area)) &&
    (!q || `${a.code} ${a.name} ${a.asset_type.name} ${a.tags.join(" ")}`.toLowerCase().includes(q.toLowerCase())));
  const selected = all.find((a) => a.id === assetId);
  const categories = [...new Set((types.data ?? []).map((t) => t.category))].sort();

  const setFilter = (k: string, v: string) => { const p = new URLSearchParams(params); v ? p.set(k, v) : p.delete(k); setParams(p, { replace: true }); };

  if (!factory) return <div className="panel"><Empty title="No factory selected" /></div>;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Assets</h1>
          <div className="sub">Physical equipment in {factory.name}. Each asset is one identity; 2D/3D and dashboard views will reference it.</div>
        </div>
        <div className="actions">
          {can("asset.write") && <button className="btn primary" onClick={() => setCreating({})} disabled={!types.data}><Icon name="plus" />Add asset</button>}
        </div>
      </div>
      {assets.error && <ErrorNote error={assets.error} onRetry={assets.reload} />}
      <div className="split">
        <section className="panel">
          <div className="toolbar">
            <input className="input" style={{ flex: "1 1 160px" }} placeholder="Search ID, name, type, tag…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search assets" />
            <select className="select" style={{ width: 140 }} value={category} onChange={(e) => setFilter("category", e.target.value)} aria-label="Category">
              <option value="">All categories</option>
              {categories.map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
            </select>
            <select className="select" style={{ width: 160 }} value={area} onChange={(e) => setFilter("area", e.target.value)} aria-label="Area">
              <option value="">All areas</option>
              {areas.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
              <option value="unassigned">Unassigned</option>
            </select>
          </div>
          {assets.loading && !assets.data ? <Loading /> : (
            <div className="scroll" style={{ maxHeight: "calc(100vh - 230px)" }}>
              <table className="table" style={{ tableLayout: "fixed" }}>
                <thead><tr><th style={{ width: 96 }}>ID</th><th>Name</th><th style={{ width: "30%" }}>Type</th><th style={{ width: "24%" }}>Area</th></tr></thead>
                <tbody>
                  {list.map((a) => (
                    <tr key={a.id} className={`clickable${a.id === assetId ? " selected" : ""}`} onClick={() => navigate(`/assets/${a.id}${window.location.search}`)}>
                      <td><span className="code-chip">{a.code}</span></td>
                      <td className="truncate" style={{ maxWidth: "none" }} title={a.name}>{a.name}</td>
                      <td className="muted truncate" style={{ maxWidth: "none" }} title={a.asset_type.name}>{a.asset_type.name}</td>
                      <td className="faint small truncate" style={{ maxWidth: "none" }} title={a.area_id ? areaName[a.area_id] : ""}>{a.area_id ? areaName[a.area_id] : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!list.length && <Empty title={all.length ? "No matches" : "No assets yet"}>{all.length ? "Try a different search or filter." : "Add your first machine or sensor."}</Empty>}
            </div>
          )}
          <div className="faint small" style={{ padding: "8px 12px", borderTop: "1px solid var(--border)" }}>{list.length} of {all.length} assets</div>
        </section>

        {selected ? (
          <AssetDetail key={selected.id} asset={selected} type={types.data?.find((t) => t.id === selected.asset_type_id)} areas={areas} assets={all}
            onChanged={(a) => assets.setData(all.map((x) => (x.id === a.id ? a : x)))}
            onDeleted={() => { navigate("/assets"); void assets.reload(); }}
            onDuplicate={() => setCreating({ from: selected })} />
        ) : (
          <section className="panel"><Empty title="Select an asset">Choose an asset on the left to view and edit its configuration.</Empty></section>
        )}
      </div>

      {creating && types.data && (
        <CreateAssetModal factoryId={factory.id} types={types.data} areas={areas} assets={all} from={creating.from}
          onClose={() => setCreating(null)}
          onCreated={async (a) => { setCreating(null); toast("ok", `${a.code} created`); await assets.reload(); navigate(`/assets/${a.id}`); }} />
      )}
    </>
  );
}
