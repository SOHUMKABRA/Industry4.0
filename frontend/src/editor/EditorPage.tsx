import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, qs, tokenStore } from "../api/client";
import { Asset, AssetType, FactoryStructure, ModelFile, ObjectKind, SceneObject, SceneVersion, SceneWithObjects, Vec3 } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal, Pill, Tabs } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { fmtDateTime, fromMetres, timeAgo, titleCase, toMetres } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useLiveMeta } from "../live/liveMeta";
import { LiveValue } from "../live/LiveValue";
import { SceneCtx } from "./objects";
import { PerfHud, SceneView, SceneViewHandle } from "./SceneView";
import { useShallow } from "zustand/react/shallow";
import { selectionOf, useEditor, uuid } from "./store";

// ---------- catalogue of building elements (scene-only objects) ----------
interface Element { kind: ObjectKind; label: string; shape: string; size: Vec3; color: string; y?: number; opacity?: number }
const BUILDING: Element[] = [
  { kind: "wall", label: "Wall", shape: "box", size: [6, 4, 0.25], color: "#9aa4b2" },
  { kind: "door", label: "Door", shape: "box", size: [1.2, 2.2, 0.3], color: "#f59e0b" },
  { kind: "window", label: "Window", shape: "box", size: [2, 1.2, 0.3], color: "#7dd3fc", y: 1, opacity: 0.5 },
  { kind: "pillar", label: "Pillar / column", shape: "cylinder", size: [0.5, 6, 0.5], color: "#b8c0cc" },
  { kind: "zone", label: "Production zone", shape: "zone", size: [10, 0.04, 8], color: "#38bdf8", opacity: 0.4 },
  { kind: "walkway", label: "Walkway", shape: "walkway", size: [10, 0.02, 2], color: "#facc15", opacity: 0.5 },
  { kind: "safety_zone", label: "Safety zone", shape: "zone", size: [4, 0.04, 4], color: "#ef4444", opacity: 0.35 },
  { kind: "workstation", label: "Workstation", shape: "box", size: [2, 0.9, 1], color: "#a3a3a3" },
  { kind: "storage", label: "Storage rack", shape: "box", size: [6, 3, 1.1], color: "#3b82f6" },
  { kind: "box", label: "Generic box", shape: "box", size: [1, 1, 1], color: "#6b7a90" },
];
const SHAPES = ["box", "cylinder", "sphere", "conveyor", "robot_arm", "tank", "panel", "sensor", "line", "zone", "walkway"];
const DEG = 180 / Math.PI;

type DragData = { t: "building"; i: number } | { t: "asset"; id: string } | { t: "type"; id: string };
const dragStart = (d: DragData) => (e: React.DragEvent) => {
  e.dataTransfer.setData("application/x-twin", JSON.stringify(d));
  e.dataTransfer.effectAllowed = "copy";
};

export function baseObject(p: Partial<SceneObject>): SceneObject {
  return {
    id: uuid(), kind: "box", asset_id: null, name: "", shape: "box", position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1],
    size: [1, 1, 1], color: "#6b7a90", opacity: 1, model_id: null, floor_id: null, group_id: null, locked: false, hidden: false,
    sort: 0, props: {}, ...p,
  };
}

function assetObject(a: Asset, t: AssetType | undefined, at: [number, number], floorId: string | null): SceneObject {
  return baseObject({
    kind: "asset", asset_id: a.id, name: a.name, shape: t?.visual.shape ?? "box", color: t?.visual.color ?? "#6b7a90",
    size: [...(t?.visual.size ?? [1, 1, 1])] as Vec3, position: [at[0], 0, at[1]], floor_id: floorId,
  });
}

// ---------- numeric field that commits on blur / Enter ----------
function NumField({ value, onCommit, step = 0.1, disabled, label }: {
  value: number; onCommit: (v: number) => void; step?: number; disabled?: boolean; label: string;
}) {
  const shown = String(+value.toFixed(3));
  const [text, setText] = useState(shown);
  useEffect(() => { setText(shown); }, [shown]);
  const commit = () => {
    const n = Number(text);
    if (text.trim() !== "" && Number.isFinite(n) && String(+n.toFixed(3)) !== shown) onCommit(n);
    else setText(shown);
  };
  return (
    <label className="num-field" title={label}>
      <span>{label}</span>
      <input className="input" type="number" step={step} value={text} disabled={disabled} aria-label={label}
        onChange={(e) => setText(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setText(shown); }} />
    </label>
  );
}

function Vec3Row({ label, value, onCommit, disabled, step, unit, convert }: {
  label: string; value: Vec3; onCommit: (v: Vec3) => void; disabled?: boolean; step?: number; unit?: string;
  convert?: { to: (v: number) => number; from: (v: number) => number };
}) {
  const to = convert?.to ?? ((v: number) => v), from = convert?.from ?? ((v: number) => v);
  return (
    <div className="vec-row">
      <div className="vec-label">{label}{unit && <span className="faint"> ({unit})</span>}</div>
      <div className="vec-inputs">
        {(["X", "Y", "Z"] as const).map((ax, i) => (
          <NumField key={ax} label={ax} value={to(value[i])} step={step} disabled={disabled}
            onCommit={(n) => { const v = [...value] as Vec3; v[i] = from(n); onCommit(v); }} />
        ))}
      </div>
    </div>
  );
}

// ---------- modals ----------
function NewAssetModal({ type, factoryId, areaId, onClose, onCreated }: {
  type: AssetType; factoryId: string; areaId: string | null; onClose: () => void; onCreated: (a: Asset) => void;
}) {
  const prefix = type.key.split("_").map((s) => s[0]).join("").toUpperCase().slice(0, 3);
  const [code, setCode] = useState(`${prefix}-${String(Math.floor(100 + Math.random() * 900))}`);
  const [name, setName] = useState(type.name);
  const [err, setErr] = useState<string | null>(null);
  const create = async () => {
    try {
      onCreated(await api.post<Asset>("/assets", { factory_id: factoryId, asset_type_id: type.id, code, name, area_id: areaId, properties: {} }));
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <Modal title={`New ${type.name}`} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn primary" onClick={create} disabled={!code.trim() || !name.trim()}>Create &amp; place</button>
    </>}>
      <div className="stack">
        <p className="muted small" style={{ margin: 0 }}>This creates a real asset record (with default properties) and places it here. Edit its properties later on the Assets page.</p>
        <div className="grid-2">
          <Field label="Asset ID" required><input className="input mono" value={code} onChange={(e) => setCode(e.target.value)} autoFocus /></Field>
          <Field label="Name" required><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        </div>
        {err && <div className="notice bad">{err}</div>}
      </div>
    </Modal>
  );
}

function VersionsModal({ sceneId, onClose, onRestored, canWrite, dirty }: {
  sceneId: string; onClose: () => void; onRestored: (s: SceneWithObjects) => void; canWrite: boolean; dirty: boolean;
}) {
  const versions = useApi(() => api.get<SceneVersion[]>(`/scenes/${sceneId}/versions`), [sceneId]);
  const [confirm, setConfirm] = useState<SceneVersion | null>(null);
  const toast = useToast();
  const restore = async (v: SceneVersion) => {
    try {
      onRestored(await api.post<SceneWithObjects>(`/scenes/${sceneId}/versions/${v.version}/restore`));
      toast("ok", `Restored v${v.version}`);
    } catch (e) { toast("bad", (e as Error).message); }
  };
  return (
    <Modal wide title="Layout history" onClose={onClose}>
      {!versions.data ? <Loading /> : (
        <table className="table">
          <thead><tr><th>Version</th><th>Saved</th><th>By</th><th>Message</th><th className="num">Objects</th><th /></tr></thead>
          <tbody>
            {versions.data.map((v, i) => (
              <tr key={v.id}>
                <td><span className="code-chip">v{v.version}</span>{i === 0 && <span className="faint small"> current</span>}</td>
                <td className="muted" title={fmtDateTime(v.created_at)}>{timeAgo(v.created_at)}</td>
                <td className="muted">{v.created_by}</td>
                <td>{v.message || <span className="faint">—</span>}</td>
                <td className="num">{v.object_count}</td>
                <td style={{ textAlign: "right" }}>{canWrite && i > 0 && <button className="btn sm" onClick={() => setConfirm(v)}>Restore</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {confirm && (
        <Confirm title={`Restore v${confirm.version}?`} confirmLabel="Restore"
          message={<>The layout from v{confirm.version} is saved as a new version; nothing is deleted from history.{dirty && <><br /><strong>Your unsaved changes will be discarded.</strong></>}</>}
          onClose={() => setConfirm(null)} onConfirm={() => { setConfirm(null); void restore(confirm); }} />
      )}
    </Modal>
  );
}

// ---------- left panel ----------
function LibraryPanel({ types, unplaced, canWrite }: { types: AssetType[]; unplaced: Asset[]; canWrite: boolean }) {
  const [tab, setTab] = useState<"assets" | "new" | "building" | "outline">("assets");
  const [q, setQ] = useState("");
  const ql = q.toLowerCase();
  const cats = [...new Set(types.map((t) => t.category))].sort();
  return (
    <aside className="ed-left">
      <Tabs value={tab} onChange={setTab} tabs={[
        { key: "assets", label: `Assets${unplaced.length ? ` (${unplaced.length})` : ""}` },
        { key: "new", label: "New" }, { key: "building", label: "Building" }, { key: "outline", label: "Outline" },
      ]} />
      <div className="ed-search"><input className="input" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter library" /></div>
      <div className="ed-scroll">
        {tab === "assets" && (
          <>
            <p className="faint small ed-hint">{canWrite ? "Drag an unplaced asset onto the floor." : "Unplaced assets"}</p>
            {unplaced.filter((a) => `${a.code} ${a.name}`.toLowerCase().includes(ql)).map((a) => (
              <div key={a.id} className="lib-item" draggable={canWrite} onDragStart={dragStart({ t: "asset", id: a.id })}>
                <span className="code-chip">{a.code}</span><span className="lib-name">{a.name}</span>
              </div>
            ))}
            {!unplaced.length && <p className="faint small ed-hint">Every asset is placed. Create new ones from the “New” tab.</p>}
          </>
        )}
        {tab === "new" && (
          <>
            <p className="faint small ed-hint">Drag a type onto the floor to create and place a new asset.</p>
            {cats.map((c) => {
              const list = types.filter((t) => t.category === c && t.name.toLowerCase().includes(ql));
              if (!list.length) return null;
              return (
                <div key={c}>
                  <div className="section-title ed-cat">{titleCase(c)}</div>
                  {list.map((t) => (
                    <div key={t.id} className="lib-item" draggable={canWrite} onDragStart={dragStart({ t: "type", id: t.id })}>
                      <span className="swatch" style={{ background: t.visual.color }} /><span className="lib-name">{t.name}</span>
                    </div>
                  ))}
                </div>
              );
            })}
          </>
        )}
        {tab === "building" && BUILDING.map((b, i) => b.label.toLowerCase().includes(ql) && (
          <div key={b.kind + i} className="lib-item" draggable={canWrite} onDragStart={dragStart({ t: "building", i })}>
            <span className="swatch" style={{ background: b.color }} /><span className="lib-name">{b.label}</span>
          </div>
        ))}
        {tab === "outline" && <Outline q={ql} canWrite={canWrite} />}
      </div>
    </aside>
  );
}

function Outline({ q, canWrite }: { q: string; canWrite: boolean }) {
  const order = useEditor((s) => s.order);
  const objects = useEditor((s) => s.objects);
  const selected = useEditor((s) => s.selected);
  const sel = new Set(selected);
  const list = order.map((id) => objects[id]).filter((o) => o && `${o.name} ${o.kind}`.toLowerCase().includes(q));
  const LIMIT = 400;
  const st = useEditor.getState();
  return (
    <>
      {list.slice(0, LIMIT).map((o) => (
        <div key={o.id} className={`outline-row${sel.has(o.id) ? " selected" : ""}`}
          onClick={(e) => st.select([o.id], e.shiftKey || e.ctrlKey || e.metaKey)}>
          <span className="outline-kind" title={titleCase(o.kind)}>{o.kind === "asset" ? "◆" : o.group_id ? "▣" : "□"}</span>
          <span className="lib-name" style={{ opacity: o.hidden ? 0.45 : 1 }}>{o.name || titleCase(o.kind)}</span>
          {canWrite && (
            <>
              <button className={`tog${o.hidden ? " on" : ""}`} title={o.hidden ? "Show" : "Hide"} aria-label={o.hidden ? "Show" : "Hide"}
                onClick={(e) => { e.stopPropagation(); st.update([o.id], (x) => ({ hidden: !x.hidden }), o.hidden ? "Show" : "Hide"); }}>{o.hidden ? "hidden" : "eye"}</button>
              <button className={`tog${o.locked ? " on" : ""}`} title={o.locked ? "Unlock" : "Lock"} aria-label={o.locked ? "Unlock" : "Lock"}
                onClick={(e) => { e.stopPropagation(); st.update([o.id], (x) => ({ locked: !x.locked }), o.locked ? "Unlock" : "Lock"); }}>{o.locked ? "locked" : "lock"}</button>
            </>
          )}
        </div>
      ))}
      {list.length > LIMIT && <p className="faint small ed-hint">Showing {LIMIT} of {list.length}. Use the filter to narrow.</p>}
    </>
  );
}

// ---------- right panel ----------
function PropertiesPanel({ types, assets, models, unit, canWrite, onModelsChanged }: {
  types: Record<string, AssetType>; assets: Record<string, Asset>; models: ModelFile[]; unit: string; canWrite: boolean; onModelsChanged: () => void;
}) {
  const selection = useEditor(useShallow(selectionOf));
  const live = useEditor((s) => s.live);
  const st = useEditor.getState();
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const len = { to: (v: number) => fromMetres(v, unit), from: (v: number) => toMetres(v, unit) };

  if (!selection.length) {
    return (
      <aside className="ed-right">
        <div className="ed-section">
          <h3>Nothing selected</h3>
          <p className="muted small">Click an object, or drag one in from the library.</p>
          <dl className="kv small shortcut-list">
            <dt>W / E / R</dt><dd>Move / rotate / scale</dd>
            <dt>Shift+click</dt><dd>Multi-select</dd>
            <dt>Ctrl+Z / Ctrl+Y</dt><dd>Undo / redo</dd>
            <dt>Ctrl+D</dt><dd>Duplicate</dd>
            <dt>Ctrl+G</dt><dd>Group (+Shift: ungroup)</dd>
            <dt>Arrows</dt><dd>Nudge (Shift ×10)</dd>
            <dt>L / H</dt><dd>Lock / hide</dd>
            <dt>Delete</dt><dd>Remove from layout</dd>
            <dt>2 / 3 / F</dt><dd>2D / 3D / frame all</dd>
            <dt>Ctrl+S</dt><dd>Save</dd>
          </dl>
        </div>
      </aside>
    );
  }

  const ids = selection.map((o) => o.id);
  const disabled = !canWrite;
  if (selection.length > 1) {
    const allLocked = selection.every((o) => o.locked);
    return (
      <aside className="ed-right">
        <div className="ed-section"><h3>{selection.length} objects selected</h3></div>
        <div className="ed-section">
          <div className="section-title">Align</div>
          <div className="btn-grid">
            {(["min", "center", "max"] as const).map((h) => <button key={`x${h}`} className="btn sm" disabled={disabled} onClick={() => st.align(ids, 0, h)}>X {h}</button>)}
            {(["min", "center", "max"] as const).map((h) => <button key={`z${h}`} className="btn sm" disabled={disabled} onClick={() => st.align(ids, 2, h)}>Z {h}</button>)}
            <button className="btn sm" disabled={disabled || ids.length < 3} onClick={() => st.distribute(ids, 0)}>Distribute X</button>
            <button className="btn sm" disabled={disabled || ids.length < 3} onClick={() => st.distribute(ids, 2)}>Distribute Z</button>
          </div>
        </div>
        <div className="ed-section">
          <div className="section-title">Arrange</div>
          <div className="btn-grid">
            <button className="btn sm" disabled={disabled} onClick={() => st.group(ids)}>Group</button>
            <button className="btn sm" disabled={disabled} onClick={() => st.ungroup(ids)}>Ungroup</button>
            <button className="btn sm" disabled={disabled} onClick={() => st.update(ids, () => ({ locked: !allLocked }), allLocked ? "Unlock" : "Lock")}>{allLocked ? "Unlock" : "Lock"}</button>
            <button className="btn sm" disabled={disabled} onClick={() => st.update(ids, () => ({ hidden: true }), "Hide")}>Hide</button>
            <button className="btn sm" disabled={disabled} onClick={() => st.duplicate(ids)}>Duplicate</button>
            <button className="btn sm danger" disabled={disabled} onClick={() => st.remove(ids)}>Remove</button>
          </div>
          <p className="faint small">Asset objects aren't duplicated: each represents one physical asset. Locked objects can't be removed.</p>
        </div>
      </aside>
    );
  }

  const o = selection[0];
  const asset = o.asset_id ? assets[o.asset_id] : undefined;
  const type = asset ? types[asset.asset_type_id] : undefined;
  const locked = o.locked;
  const upd = (patch: Partial<SceneObject>, label: string) => st.update([o.id], () => patch, label);

  const upload = async (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    try {
      const res = await fetch("/api/models", { method: "POST", body: fd, headers: { Authorization: `Bearer ${tokenStore.get()}` } });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new ApiError(res.status, data?.detail);
      onModelsChanged();
      upd({ model_id: data.id }, "Assign model");
      toast("ok", `${f.name} uploaded`);
    } catch (e) { toast("bad", (e as Error).message); }
  };

  return (
    <aside className="ed-right">
      <div className="ed-section">
        <div className="row">
          {asset ? <span className="code-chip">{asset.code}</span> : <span className="tag">{titleCase(o.kind)}</span>}
          {locked && <Pill tone="warn" dot={false}>Locked</Pill>}
          {o.group_id && <Pill tone="info" dot={false}>Grouped</Pill>}
        </div>
        {asset ? (
          <>
            <h3 style={{ marginTop: 6 }}>{asset.name}</h3>
            <div className="faint small">{asset.asset_type.name} · <Link to={`/assets/${asset.id}`}>Open asset</Link></div>
          </>
        ) : (
          <Field label="Name">
            <input key={o.id} className="input" defaultValue={o.name} disabled={disabled || locked}
              onBlur={(e) => e.target.value !== o.name && upd({ name: e.target.value }, "Rename")}
              onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
          </Field>
        )}
      </div>

      <div className="ed-section">
        <div className="section-title">Transform</div>
        <Vec3Row label="Position" unit={unit} value={o.position} disabled={disabled || locked} convert={len} step={0.1} onCommit={(v) => upd({ position: v }, "Move")} />
        <Vec3Row label="Rotation" unit="°" value={o.rotation} disabled={disabled || locked} step={15}
          convert={{ to: (r) => +(r * DEG).toFixed(2), from: (d) => d / DEG }} onCommit={(v) => upd({ rotation: v }, "Rotate")} />
        <Vec3Row label="Size" unit={unit} value={o.size} disabled={disabled || locked} convert={len} step={0.1}
          onCommit={(v) => { if (v.every((x) => x > 0)) upd({ size: v }, "Resize"); }} />
        <Vec3Row label="Scale" value={o.scale} disabled={disabled || locked} step={0.1} onCommit={(v) => { if (v.every((x) => x > 0)) upd({ scale: v }, "Scale"); }} />
      </div>

      <div className="ed-section">
        <div className="section-title">Appearance</div>
        <div className="grid-2">
          <Field label="Colour">
            <input key={o.id + o.color} type="color" defaultValue={o.color} disabled={disabled || locked} aria-label="Colour" className="color-input"
              onBlur={(e) => e.target.value !== o.color && upd({ color: e.target.value }, "Colour")}
              onChange={(e) => e.target.value !== o.color && upd({ color: e.target.value }, "Colour")} />
          </Field>
          <Field label={`Opacity ${Math.round(o.opacity * 100)}%`}>
            <input type="range" min={0.1} max={1} step={0.05} value={o.opacity} disabled={disabled || locked} aria-label="Opacity"
              onChange={(e) => upd({ opacity: Number(e.target.value) }, "Opacity")} />
          </Field>
          <Field label="Shape">
            <select className="select" value={o.shape} disabled={disabled || locked} onChange={(e) => upd({ shape: e.target.value }, "Shape")}>
              {SHAPES.map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </select>
          </Field>
          <Field label="3D model">
            <select className="select" value={o.model_id ?? ""} disabled={disabled || locked} onChange={(e) => upd({ model_id: e.target.value || null }, "Model")}>
              <option value="">Built-in shape</option>
              {models.map((m) => <option key={m.id} value={m.id}>{m.filename}</option>)}
            </select>
          </Field>
        </div>
        {canWrite && !locked && (
          <>
            <input ref={fileRef} type="file" accept=".glb,.obj,.stl" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} />
            <button className="btn sm" style={{ marginTop: 8 }} onClick={() => fileRef.current?.click()}>Upload model (GLB, OBJ, STL)</button>
            <p className="faint small" style={{ margin: "6px 0 0" }}>The model is stretched to fit the object's size. FBX: export to GLB first.</p>
          </>
        )}
      </div>

      <div className="ed-section">
        <div className="row wrap">
          <label className="check"><input type="checkbox" checked={o.locked} disabled={disabled} onChange={() => upd({ locked: !o.locked }, o.locked ? "Unlock" : "Lock")} />Locked</label>
          <label className="check"><input type="checkbox" checked={o.hidden} disabled={disabled} onChange={() => upd({ hidden: !o.hidden }, "Visibility")} />Hidden</label>
        </div>
        {canWrite && (
          <div className="row" style={{ marginTop: 10 }}>
            {o.kind !== "asset" && <button className="btn sm" disabled={locked} onClick={() => st.duplicate([o.id])}>Duplicate</button>}
            <button className="btn sm danger" disabled={locked} onClick={() => st.remove([o.id])}>Remove from layout</button>
          </div>
        )}
        {asset && <p className="faint small">Removing it from the layout keeps the asset record; it moves back to “unplaced”.</p>}
      </div>

      {asset && type && live && type.telemetry.length > 0 && (
        <div className="ed-section">
          <div className="section-title">Live values</div>
          <dl className="kv small">
            {type.telemetry.map((d) => (
              <Fragment key={d.key}><dt>{d.label}</dt><dd><LiveValue assetId={asset.id} def={d} /></dd></Fragment>
            ))}
          </dl>
        </div>
      )}
    </aside>
  );
}

// ---------- page ----------
export function EditorPage() {
  const { factory } = useFactory();
  const { can } = useAuth();
  const toast = useToast();
  const canWrite = can("factory.write");
  const fid = factory?.id;
  const ed = useEditor();
  const sceneRef = useRef<SceneViewHandle>(null);
  const [loadErr, setLoadErr] = useState<Error | null>(null);
  const [saving, setSaving] = useState(false);
  const [showVersions, setShowVersions] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [newAsset, setNewAsset] = useState<{ type: AssetType; at: [number, number]; areaId: string | null } | null>(null);
  const [perf, setPerf] = useState(false);
  const latency = useLiveMeta((s) => s.latencyMs);

  const types = useApi(() => api.get<AssetType[]>("/asset-types"), []);
  const assets = useApi(() => (fid ? api.get<Asset[]>(`/assets${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const structure = useApi(() => (fid ? api.get<FactoryStructure>(`/factories/${fid}`) : Promise.resolve(undefined)), [fid]);
  const models = useApi(() => api.get<ModelFile[]>("/models"), []);

  const loadScene = useCallback(async (force = false) => {
    if (!fid) return;
    const s = useEditor.getState();
    if (!force && s.factoryId === fid && s.sceneId) return; // keep in-memory edits across page navigation
    try {
      const r = await api.get<SceneWithObjects>(`/factories/${fid}/scene`);
      useEditor.getState().load(fid, r.scene.id, r.scene.version, r.objects);
      setLoadErr(null);
    } catch (e) { setLoadErr(e as Error); }
  }, [fid]);
  useEffect(() => { void loadScene(); }, [loadScene]);

  // Warn before closing the tab with unsaved changes.
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (useEditor.getState().dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, []);

  const typeById = useMemo(() => Object.fromEntries((types.data ?? []).map((t) => [t.id, t])), [types.data]);
  const assetById = useMemo(() => Object.fromEntries((assets.data ?? []).map((a) => [a.id, a])), [assets.data]);
  const modelById = useMemo(() => Object.fromEntries((models.data ?? []).map((m) => [m.id, m])), [models.data]);
  const placed = useMemo(() => new Set(Object.values(ed.objects).map((o) => o.asset_id).filter(Boolean)), [ed.objects]);
  const unplaced = (assets.data ?? []).filter((a) => !placed.has(a.id));
  const unit = factory?.length_unit ?? "m";
  const floorId = structure.data?.floors[0]?.id ?? null;

  const ctx: SceneCtx = useMemo(() => ({
    typeOfAsset: (id) => typeById[assetById[id]?.asset_type_id],
    assetLabel: (id) => assetById[id]?.code ?? "",
    models: modelById, live: ed.live, animate: true, labels: ed.labels, view: ed.view,
  }), [typeById, assetById, modelById, ed.live, ed.labels, ed.view]);

  const save = useCallback(async (message = "") => {
    const s = useEditor.getState();
    if (!s.sceneId || saving) return;
    setSaving(true);
    try {
      const objects = s.order.map((id, i) => ({ ...s.objects[id], sort: i }));
      const r = await api.put<SceneWithObjects>(`/scenes/${s.sceneId}`, { base_version: s.version, message, objects });
      useEditor.getState().markSaved(r.scene.version, r.objects);
      toast("ok", `Layout saved (v${r.scene.version})`);
    } catch (e) {
      toast("bad", (e as Error).message);
    } finally { setSaving(false); }
  }, [saving, toast]);

  const areaAt = (x: number, z: number) =>
    structure.data?.floors[0]?.areas.find((a) => x >= a.bounds.x && x <= a.bounds.x + a.bounds.width && z >= a.bounds.z && z <= a.bounds.z + a.bounds.depth)?.id ?? null;

  const onDrop = (raw: string, at: [number, number]) => {
    if (!canWrite) return;
    const s = useEditor.getState();
    const p: [number, number] = s.snap ? [Math.round(at[0] / s.grid) * s.grid, Math.round(at[1] / s.grid) * s.grid] : at;
    const d = JSON.parse(raw) as DragData;
    if (d.t === "building") {
      const b = BUILDING[d.i];
      s.add([baseObject({ kind: b.kind, name: b.label, shape: b.shape, size: [...b.size] as Vec3, color: b.color, opacity: b.opacity ?? 1, position: [p[0], b.y ?? 0, p[1]], floor_id: floorId })], `Add ${b.label}`);
    } else if (d.t === "asset") {
      const a = assetById[d.id];
      if (a && !placed.has(a.id)) s.add([assetObject(a, typeById[a.asset_type_id], p, floorId)], `Place ${a.code}`);
    } else {
      const t = typeById[d.id];
      if (t) setNewAsset({ type: t, at: p, areaId: areaAt(p[0], p[1]) });
    }
  };

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || document.querySelector(".overlay")) return;
      const s = useEditor.getState();
      const mod = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (mod && k === "s") { e.preventDefault(); if (canWrite && s.dirty) setSaveMsg(""); return; }
      if (mod && k === "a") { e.preventDefault(); s.set({ selected: s.order.filter((id) => !s.objects[id].hidden) }); return; }
      if (k === "escape") { s.select([]); return; }
      if (k === "f") { sceneRef.current?.frame(); return; }
      if (k === "2") { s.set({ view: "2d" }); return; }
      if (k === "3") { s.set({ view: "3d" }); return; }
      if (!canWrite) return;
      if (mod && k === "z" && !e.shiftKey) { e.preventDefault(); s.undo(); return; }
      if (mod && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); s.redo(); return; }
      if (mod && k === "d") { e.preventDefault(); s.duplicate(s.selected); return; }
      if (mod && k === "g") { e.preventDefault(); if (e.shiftKey) s.ungroup(s.selected); else s.group(s.selected); return; }
      if (k === "delete" || k === "backspace") { e.preventDefault(); s.remove(s.selected); return; }
      if (mod) return;
      if (k === "w") s.set({ mode: "translate" });
      if (k === "e") s.set({ mode: "rotate" });
      if (k === "r") s.set({ mode: "scale" });
      if (k === "l" && s.selected.length) { const lock = !s.objects[s.selected[0]].locked; s.update(s.selected, () => ({ locked: lock }), lock ? "Lock" : "Unlock"); }
      if (k === "h" && s.selected.length) s.update(s.selected, () => ({ hidden: true }), "Hide");
      const arrows: Record<string, [number, number]> = { arrowleft: [-1, 0], arrowright: [1, 0], arrowup: [0, -1], arrowdown: [0, 1] };
      if (arrows[k] && s.selected.length) {
        e.preventDefault();
        const step = s.grid * (e.shiftKey ? 10 : 1);
        const [dx, dz] = arrows[k];
        s.update(s.selected.filter((id) => !s.objects[id].locked), (o) => ({ position: [o.position[0] + dx * step, o.position[1], o.position[2] + dz * step] }), "Nudge");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canWrite]);

  const stressTest = () => {
    const s = useEditor.getState();
    const g = uuid();
    const N = 5000, cols = 100;
    const objs = Array.from({ length: N }, (_, i) => baseObject({
      kind: "box", name: `Stress ${i + 1}`, group_id: g, size: [0.6, 0.6 + (i % 7) * 0.2, 0.6],
      color: ["#64748b", "#3b82f6", "#22c55e", "#f59e0b"][i % 4], position: [(i % cols) * 1.0, 0, 45 + Math.floor(i / cols) * 1.0], floor_id: floorId,
    }));
    s.add(objs, "Stress test (5,000 objects)");
    s.select([]);
    setPerf(true);
    toast("info", "Added 5,000 instanced boxes south of the building. Ctrl+Z removes them.");
  };

  if (!factory) return <div className="panel"><Empty title="No factory selected" /></div>;
  if (loadErr) return <ErrorNote error={loadErr} onRetry={() => loadScene(true)} />;
  if (!ed.sceneId || ed.factoryId !== fid || !types.data || !assets.data) return <Loading label="Loading layout…" />;

  const objectCount = ed.order.length;
  const seg = (active: boolean) => `btn sm${active ? " active" : ""}`;

  return (
    <div className="editor">
      <div className="ed-toolbar">
        <div className="seg" role="group" aria-label="Gizmo mode">
          <button className={seg(ed.mode === "translate")} onClick={() => ed.set({ mode: "translate" })} title="Move (W)">Move</button>
          <button className={seg(ed.mode === "rotate")} onClick={() => ed.set({ mode: "rotate" })} title="Rotate (E)">Rotate</button>
          <button className={seg(ed.mode === "scale")} onClick={() => ed.set({ mode: "scale" })} title="Scale (R)">Scale</button>
        </div>
        <div className="seg" role="group" aria-label="View">
          <button className={seg(ed.view === "3d")} onClick={() => ed.set({ view: "3d" })} title="3D view (3)">3D</button>
          <button className={seg(ed.view === "2d")} onClick={() => ed.set({ view: "2d" })} title="2D plan (2)">2D</button>
        </div>
        <label className="check small"><input type="checkbox" checked={ed.snap} onChange={(e) => ed.set({ snap: e.target.checked })} />Snap</label>
        <select className="select sm-select" value={ed.grid} onChange={(e) => ed.set({ grid: Number(e.target.value) })} aria-label="Grid size">
          {[0.1, 0.25, 0.5, 1, 2, 5].map((g) => <option key={g} value={g}>{fromMetres(g, unit)} {unit}</option>)}
        </select>
        <span className="tb-sep" />
        <button className="btn sm" onClick={ed.undo} disabled={!canWrite || !ed.past.length} title={ed.past.length ? `Undo ${ed.past[ed.past.length - 1].label} (Ctrl+Z)` : "Undo"}>↶ Undo</button>
        <button className="btn sm" onClick={ed.redo} disabled={!canWrite || !ed.future.length} title={ed.future.length ? `Redo ${ed.future[0].label} (Ctrl+Y)` : "Redo"}>↷ Redo</button>
        <span className="tb-sep" />
        <label className="check small"><input type="checkbox" checked={ed.labels} onChange={(e) => ed.set({ labels: e.target.checked })} />Labels</label>
        <label className="check small" title="Status beacons and animation for equipment reporting fresh 'running' state"><input type="checkbox" checked={ed.live} onChange={(e) => ed.set({ live: e.target.checked })} />Live state</label>
        <label className="check small"><input type="checkbox" checked={perf} onChange={(e) => setPerf(e.target.checked)} />Perf</label>
        <button className="btn sm ghost" onClick={() => sceneRef.current?.frame()} title="Frame factory (F)">Frame</button>
        <div className="right row">
          {canWrite && <button className="btn sm ghost" onClick={stressTest} title="Adds 5,000 instanced objects to measure rendering performance">Stress test</button>}
          <button className="btn sm" onClick={() => setShowVersions(true)}>History</button>
          {canWrite && <button className="btn sm" disabled={!ed.dirty} onClick={() => void loadScene(true)} title="Discard unsaved changes">Discard</button>}
          {canWrite && (
            <button className="btn sm primary" disabled={!ed.dirty || saving} onClick={() => setSaveMsg("")}>
              {saving ? "Saving…" : ed.dirty ? "Save layout" : "Saved"}
            </button>
          )}
        </div>
      </div>

      <div className="ed-body">
        <LibraryPanel types={types.data} unplaced={unplaced} canWrite={canWrite} />
        <div className="ed-canvas">
          <SceneView ref={sceneRef} objects={ed.objects} order={ed.order} selected={ed.selected} structure={structure.data} ctx={ctx}
            editable={canWrite} mode={ed.mode} snap={ed.snap} grid={ed.grid} perf={perf}
            onSelect={(ids, add) => ed.select(ids, add)} onDropItem={canWrite ? onDrop : undefined} />
          {perf && <PerfHud objects={objectCount} latency={latency} />}
          {!canWrite && <div className="ed-banner">View only. Your role can't edit layouts.</div>}
        </div>
        <PropertiesPanel types={typeById} assets={assetById} models={models.data ?? []} unit={unit} canWrite={canWrite}
          onModelsChanged={() => void models.reload()} />
      </div>

      <div className="ed-status">
        <span>{objectCount.toLocaleString()} objects</span>
        <span>{ed.selected.length} selected</span>
        <span>v{ed.version}{ed.dirty && <strong className="dirty"> · unsaved changes</strong>}</span>
        <span>{unplaced.length} unplaced assets</span>
        <span className="right">{ed.view.toUpperCase()} · grid {fromMetres(ed.grid, unit)} {unit}{ed.snap ? " · snap" : ""}</span>
      </div>

      {saveMsg !== null && (
        <Modal title="Save layout" onClose={() => setSaveMsg(null)} footer={<>
          <button className="btn" onClick={() => setSaveMsg(null)}>Cancel</button>
          <button className="btn primary" onClick={() => { const m = saveMsg; setSaveMsg(null); void save(m); }}>Save v{ed.version + 1}</button>
        </>}>
          <Field label="What changed? (optional)" help="Stored in the layout history so you can find and restore this version later.">
            <input className="input" value={saveMsg} onChange={(e) => setSaveMsg(e.target.value)} autoFocus
              onKeyDown={(e) => { if (e.key === "Enter") { const m = saveMsg; setSaveMsg(null); void save(m); } }} />
          </Field>
        </Modal>
      )}
      {showVersions && ed.sceneId && (
        <VersionsModal sceneId={ed.sceneId} canWrite={canWrite} dirty={ed.dirty} onClose={() => setShowVersions(false)}
          onRestored={(r) => { useEditor.getState().load(fid!, r.scene.id, r.scene.version, r.objects); setShowVersions(false); }} />
      )}
      {newAsset && (
        <NewAssetModal type={newAsset.type} factoryId={factory.id} areaId={newAsset.areaId} onClose={() => setNewAsset(null)}
          onCreated={async (a) => {
            const { type, at } = newAsset;
            setNewAsset(null);
            await assets.reload();
            useEditor.getState().add([assetObject(a, type, at, floorId)], `Place ${a.code}`);
            toast("ok", `${a.code} created and placed. Save the layout to keep its position.`);
          }} />
      )}
    </div>
  );
}
