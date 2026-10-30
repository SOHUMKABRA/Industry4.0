import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Area, AreaKind, Factory, FactoryStructure, FactorySummary, Floor, LengthUnit } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { useToast } from "../components/Toast";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { fromMetres, titleCase, toMetres } from "../lib/format";
import { useApi } from "../lib/useApi";

const AREA_KINDS: AreaKind[] = ["production", "storage", "walkway", "safety", "utility", "office"];
const AREA_COLORS: Record<AreaKind, string> = {
  production: "#38bdf8", storage: "#a78bfa", walkway: "#94a3b8", safety: "#f59e0b", utility: "#22c55e", office: "#f472b6",
};
const UNITS: LengthUnit[] = ["mm", "cm", "m", "ft"];

function FactoryForm({ initial, onSaved, onClose }: { initial?: Factory; onSaved: (f: Factory) => void; onClose: () => void }) {
  const [f, setF] = useState({
    name: initial?.name ?? "", location: initial?.location ?? "", description: initial?.description ?? "",
    timezone: initial?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "UTC",
    length_unit: initial?.length_unit ?? ("m" as LengthUnit),
  });
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    try {
      onSaved(initial ? await api.patch<Factory>(`/factories/${initial.id}`, f) : await api.post<Factory>("/factories", f));
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <Modal title={initial ? "Factory settings" : "New factory"} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save} disabled={!f.name.trim()}>Save</button></>}>
      <div className="stack">
        <Field label="Name" required><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus /></Field>
        <Field label="Location"><input className="input" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
        <Field label="Description"><textarea className="input" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <div className="grid-2">
          <Field label="Time zone"><input className="input" value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })} /></Field>
          <Field label="Display length unit" help="Stored internally in metres">
            <select className="select" value={f.length_unit} onChange={(e) => setF({ ...f, length_unit: e.target.value as LengthUnit })}>
              {UNITS.map((u) => <option key={u}>{u}</option>)}
            </select>
          </Field>
        </div>
        {err && <div className="notice bad">{err}</div>}
      </div>
    </Modal>
  );
}

export function CreateFactoryButton() {
  const { can } = useAuth();
  const { reload, select } = useFactory();
  const [open, setOpen] = useState(false);
  if (!can("factory.write")) return null;
  return (
    <>
      <button className="btn primary" onClick={() => setOpen(true)}><Icon name="plus" />New factory</button>
      {open && <FactoryForm onClose={() => setOpen(false)} onSaved={async (f) => { setOpen(false); await reload(); select(f.id); }} />}
    </>
  );
}

function NumberInput({ value, onChange, unit }: { value: number; onChange: (n: number) => void; unit: string }) {
  return (
    <div className="input-unit">
      <input className="input" type="number" step="any" value={Number.isFinite(value) ? value : ""} onChange={(e) => onChange(Number(e.target.value))} />
      <span className="unit">{unit}</span>
    </div>
  );
}

function FloorForm({ factory, floor, onDone, onClose }: { factory: Factory; floor?: Floor; onDone: () => void; onClose: () => void }) {
  const u = factory.length_unit;
  const [f, setF] = useState({
    name: floor?.name ?? "", level: floor?.level ?? 0,
    elevation: fromMetres(floor?.elevation_m ?? 0, u), width: fromMetres(floor?.width_m ?? 50, u), depth: fromMetres(floor?.depth_m ?? 30, u),
  });
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    const body = { name: f.name, level: f.level, elevation_m: toMetres(f.elevation, u), width_m: toMetres(f.width, u), depth_m: toMetres(f.depth, u) };
    try {
      if (floor) await api.patch(`/floors/${floor.id}`, body);
      else await api.post(`/factories/${factory.id}/floors`, body);
      onDone();
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <Modal title={floor ? "Edit floor" : "Add floor"} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save} disabled={!f.name.trim()}>Save</button></>}>
      <div className="stack">
        <div className="grid-2">
          <Field label="Name" required><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus /></Field>
          <Field label="Level" help="0 = ground, negative = basement">
            <input className="input" type="number" step={1} value={f.level} onChange={(e) => setF({ ...f, level: Math.trunc(Number(e.target.value)) })} />
          </Field>
          <Field label="Width"><NumberInput unit={u} value={f.width} onChange={(width) => setF({ ...f, width })} /></Field>
          <Field label="Depth"><NumberInput unit={u} value={f.depth} onChange={(depth) => setF({ ...f, depth })} /></Field>
          <Field label="Elevation"><NumberInput unit={u} value={f.elevation} onChange={(elevation) => setF({ ...f, elevation })} /></Field>
        </div>
        {err && <div className="notice bad">{err}</div>}
      </div>
    </Modal>
  );
}

function AreaForm({ factory, floor, area, onDone, onClose }: { factory: Factory; floor: Floor; area?: Area; onDone: () => void; onClose: () => void }) {
  const u = factory.length_unit;
  const b = area?.bounds ?? { x: 0, z: 0, width: 10, depth: 10 };
  const [f, setF] = useState({
    name: area?.name ?? "", kind: area?.kind ?? ("production" as AreaKind),
    x: fromMetres(b.x, u), z: fromMetres(b.z, u), width: fromMetres(b.width, u), depth: fromMetres(b.depth, u),
  });
  const [err, setErr] = useState<string | null>(null);
  const save = async () => {
    const body = { name: f.name, kind: f.kind, bounds: { x: toMetres(f.x, u), z: toMetres(f.z, u), width: toMetres(f.width, u), depth: toMetres(f.depth, u) } };
    try {
      if (area) await api.patch(`/areas/${area.id}`, body);
      else await api.post(`/floors/${floor.id}/areas`, body);
      onDone();
    } catch (e) { setErr((e as Error).message); }
  };
  return (
    <Modal title={area ? "Edit area" : `Add area to ${floor.name}`} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" onClick={save} disabled={!f.name.trim()}>Save</button></>}>
      <div className="stack">
        <div className="grid-2">
          <Field label="Name" required><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus /></Field>
          <Field label="Kind">
            <select className="select" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as AreaKind })}>
              {AREA_KINDS.map((k) => <option key={k} value={k}>{titleCase(k)}</option>)}
            </select>
          </Field>
        </div>
        <div className="section-title">Footprint on floor</div>
        <div className="grid-2">
          <Field label="X offset"><NumberInput unit={u} value={f.x} onChange={(x) => setF({ ...f, x })} /></Field>
          <Field label="Z offset"><NumberInput unit={u} value={f.z} onChange={(z) => setF({ ...f, z })} /></Field>
          <Field label="Width"><NumberInput unit={u} value={f.width} onChange={(width) => setF({ ...f, width })} /></Field>
          <Field label="Depth"><NumberInput unit={u} value={f.depth} onChange={(depth) => setF({ ...f, depth })} /></Field>
        </div>
        {err && <div className="notice bad">{err}</div>}
      </div>
    </Modal>
  );
}

/** Top-down plan rendered from stored area bounds. The full 2D/3D editor is Phase 2. */
function FloorPlan({ floor, counts, onPick }: { floor: Floor; counts: Record<string, number>; onPick: (a: Area) => void }) {
  const pad = 1;
  const W = floor.width_m, D = floor.depth_m;
  const fs = Math.max(W, D) / 45;
  return (
    <svg className="floorplan" viewBox={`${-pad} ${-pad} ${W + 2 * pad} ${D + 2 * pad}`} role="img" aria-label={`Plan of ${floor.name}`}>
      <rect x={0} y={0} width={W} height={D} fill="none" stroke="var(--border-strong)" strokeWidth={0.2} />
      {Array.from({ length: Math.floor(W / 5) }, (_, i) => (
        <line key={`gx${i}`} x1={(i + 1) * 5} y1={0} x2={(i + 1) * 5} y2={D} stroke="var(--border)" strokeWidth={0.05} />
      ))}
      {Array.from({ length: Math.floor(D / 5) }, (_, i) => (
        <line key={`gz${i}`} x1={0} y1={(i + 1) * 5} x2={W} y2={(i + 1) * 5} stroke="var(--border)" strokeWidth={0.05} />
      ))}
      {floor.areas.map((a) => {
        const c = AREA_COLORS[a.kind] ?? "#94a3b8";
        return (
          <g key={a.id} onClick={() => onPick(a)}>
            <title>{a.name}</title>
            <rect className="area" x={a.bounds.x} y={a.bounds.z} width={a.bounds.width} height={a.bounds.depth}
              fill={c} fillOpacity={0.14} stroke={c} rx={0.3} />
            <text x={a.bounds.x + 0.8} y={a.bounds.z + 1.6 * fs} fontSize={1.2 * fs} fontWeight={600}>{a.name}</text>
            <text x={a.bounds.x + 0.8} y={a.bounds.z + 3 * fs} fontSize={fs} opacity={0.7}>
              {titleCase(a.kind)} · {counts[a.id] ?? 0} assets
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function FactoryPage() {
  const { factory, reload: reloadFactories } = useFactory();
  const { can } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const struct = useApi(() => (factory ? api.get<FactoryStructure>(`/factories/${factory.id}`) : Promise.resolve(undefined)), [factory?.id]);
  const summary = useApi(() => (factory ? api.get<FactorySummary>(`/factories/${factory.id}/summary`) : Promise.resolve(undefined)), [factory?.id]);
  const [modal, setModal] = useState<
    | { kind: "factory" } | { kind: "floor"; floor?: Floor } | { kind: "area"; floor: Floor; area?: Area }
    | { kind: "delFloor"; floor: Floor } | { kind: "delArea"; area: Area } | null
  >(null);
  const editable = can("factory.write");

  if (!factory) return <div className="panel"><Empty title="No factory selected" action={<CreateFactoryButton />} /></div>;
  if (struct.error) return <ErrorNote error={struct.error} onRetry={struct.reload} />;
  const s = struct.data;
  if (!s) return <Loading />;
  const counts = Object.fromEntries((summary.data?.by_area ?? []).map((r) => [r.key, r.count]));
  const done = () => { setModal(null); void struct.reload(); void summary.reload(); };
  const u = s.length_unit;

  const remove = async (path: string, label: string) => {
    try { await api.del(path); toast("ok", `${label} deleted`); done(); } catch (e) { toast("bad", (e as Error).message); setModal(null); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Factory layout</h1>
          <div className="sub">Floors and areas of {s.name}. Equipment placement in 2D/3D arrives with the twin editor.</div>
        </div>
        <div className="actions">
          {editable && <button className="btn" onClick={() => setModal({ kind: "factory" })}><Icon name="edit" />Settings</button>}
          {editable && <button className="btn primary" onClick={() => setModal({ kind: "floor" })}><Icon name="plus" />Add floor</button>}
          <CreateFactoryButton />
        </div>
      </div>

      {s.floors.length === 0 && <div className="panel"><Empty title="No floors yet">Add a floor to start laying out areas.</Empty></div>}

      <div className="stack" style={{ gap: 14 }}>
        {s.floors.map((fl) => (
          <section key={fl.id} className="panel">
            <div className="panel-head">
              <h2>{fl.name}</h2>
              <span className="faint small">Level {fl.level} · {fromMetres(fl.width_m, u)} × {fromMetres(fl.depth_m, u)} {u}</span>
              {editable && (
                <div className="row right">
                  <button className="btn sm" onClick={() => setModal({ kind: "area", floor: fl })}><Icon name="plus" size={14} />Area</button>
                  <button className="btn sm ghost" onClick={() => setModal({ kind: "floor", floor: fl })}>Edit</button>
                  <button className="btn sm ghost danger" onClick={() => setModal({ kind: "delFloor", floor: fl })}>Delete</button>
                </div>
              )}
            </div>
            <div className="split" style={{ padding: 14 }}>
              <FloorPlan floor={fl} counts={counts} onPick={(a) => navigate(`/assets?area=${a.id}`)} />
              <table className="table">
                <thead><tr><th>Area</th><th>Kind</th><th>Size ({u})</th><th className="num">Assets</th><th /></tr></thead>
                <tbody>
                  {fl.areas.map((a) => (
                    <tr key={a.id}>
                      <td><span className="swatch" style={{ background: AREA_COLORS[a.kind], marginRight: 8 }} />{a.name}</td>
                      <td className="muted">{titleCase(a.kind)}</td>
                      <td className="muted">{fromMetres(a.bounds.width, u)} × {fromMetres(a.bounds.depth, u)}</td>
                      <td className="num">{counts[a.id] ?? 0}</td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        <button className="btn sm ghost" onClick={() => navigate(`/assets?area=${a.id}`)}>Assets</button>
                        {editable && <button className="btn sm ghost" onClick={() => setModal({ kind: "area", floor: fl, area: a })}>Edit</button>}
                        {editable && <button className="btn sm ghost danger" onClick={() => setModal({ kind: "delArea", area: a })} aria-label="Delete area"><Icon name="trash" size={14} /></button>}
                      </td>
                    </tr>
                  ))}
                  {!fl.areas.length && <tr><td colSpan={5} className="faint">No areas on this floor.</td></tr>}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>

      {modal?.kind === "factory" && <FactoryForm initial={s} onClose={() => setModal(null)} onSaved={async () => { done(); await reloadFactories(); }} />}
      {modal?.kind === "floor" && <FloorForm factory={s} floor={modal.floor} onClose={() => setModal(null)} onDone={done} />}
      {modal?.kind === "area" && <AreaForm factory={s} floor={modal.floor} area={modal.area} onClose={() => setModal(null)} onDone={done} />}
      {modal?.kind === "delFloor" && (
        <Confirm title={`Delete ${modal.floor.name}?`} message="All areas on this floor are deleted. Assets in those areas become unassigned."
          onClose={() => setModal(null)} onConfirm={() => remove(`/floors/${modal.floor.id}`, "Floor")} />
      )}
      {modal?.kind === "delArea" && (
        <Confirm title={`Delete ${modal.area.name}?`} message="Areas that still contain assets can't be deleted. Move the assets to another area first."
          onClose={() => setModal(null)} onConfirm={() => remove(`/areas/${modal.area.id}`, "Area")} />
      )}
    </>
  );
}
