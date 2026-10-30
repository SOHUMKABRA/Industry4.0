import { useEffect, useState } from "react";
import { api } from "../api/client";
import { AssetType, ControlDef, PropertyDef, Shape, TelemetryDef } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Col, DefTable } from "../components/DefTable";
import { Icon } from "../components/Icon";
import { useToast } from "../components/Toast";
import { Confirm, Empty, ErrorNote, Field, Loading, Tabs } from "../components/ui";
import { titleCase } from "../lib/format";
import { useApi } from "../lib/useApi";

const TYPES = ["number", "integer", "string", "boolean", "enum"];
const SHAPES: Shape[] = ["box", "cylinder", "sphere", "conveyor", "robot_arm", "tank", "panel", "sensor", "line"];

const propCols: Col<PropertyDef>[] = [
  { key: "key", label: "Key", kind: "text", width: 130, placeholder: "rated_power" },
  { key: "label", label: "Label", kind: "text", width: 150 },
  { key: "type", label: "Type", kind: "select", options: TYPES, width: 95 },
  { key: "unit", label: "Unit", kind: "text", width: 60 },
  { key: "min", label: "Min", kind: "num", width: 70 },
  { key: "max", label: "Max", kind: "num", width: 70 },
  { key: "options", label: "Options (enum)", kind: "list", width: 140, placeholder: "a, b, c" },
  { key: "default", label: "Default", kind: "any", width: 80 },
  { key: "required", label: "Req.", kind: "bool", width: 40, title: "Required" },
];
const telCols: Col<TelemetryDef>[] = [
  { key: "key", label: "Key", kind: "text", width: 120, placeholder: "temp" },
  { key: "label", label: "Label", kind: "text", width: 140 },
  { key: "data_type", label: "Type", kind: "select", options: TYPES, width: 95 },
  { key: "unit", label: "Unit", kind: "text", width: 60 },
  { key: "warn_low", label: "Warn ↓", kind: "num", width: 70 },
  { key: "warn_high", label: "Warn ↑", kind: "num", width: 70 },
  { key: "alarm_low", label: "Alarm ↓", kind: "num", width: 70 },
  { key: "alarm_high", label: "Alarm ↑", kind: "num", width: 70 },
  { key: "options", label: "States (enum)", kind: "list", width: 140 },
  { key: "expected_interval_s", label: "Interval s", kind: "num", width: 70, title: "Expected max seconds between samples; older values are shown as stale" },
];
const ctlCols: Col<ControlDef>[] = [
  { key: "key", label: "Key", kind: "text", width: 120, placeholder: "start" },
  { key: "label", label: "Label", kind: "text", width: 130 },
  { key: "kind", label: "Kind", kind: "select", options: ["command", "setpoint"], width: 100 },
  { key: "min_role", label: "Min role", kind: "select", options: ["operator", "engineer", "admin"], width: 100 },
  { key: "requires_confirmation", label: "Confirm", kind: "bool", width: 60 },
  { key: "feedback_measurement", label: "Verified by measurement", kind: "text", width: 150, title: "Telemetry key that confirms the effect" },
];

const blankProp = (): PropertyDef => ({ key: "", label: "", type: "number", unit: "", required: false, min: null, max: null, options: [], default: null, group: "General", help: "" });
const blankTel = (): TelemetryDef => ({ key: "", label: "", data_type: "number", unit: "", min: null, max: null, warn_low: null, warn_high: null, alarm_low: null, alarm_high: null, options: [], expected_interval_s: 5 });
const blankCtl = (): ControlDef => ({ key: "", label: "", kind: "command", params: [], requires_confirmation: true, min_role: "operator", feedback_measurement: null, description: "" });
const blankType = (): AssetType => ({
  id: "", key: "", name: "", category: "", description: "", icon: "box", property_schema: [], telemetry: [], controls: [],
  visual: { shape: "box", color: "#6b7a90", model_url: null, size: [1, 1, 1] }, version: 0, asset_count: 0, created_at: "", updated_at: "",
});

function TypeEditor({ initial, onSaved, onDeleted, categories }: {
  initial: AssetType; onSaved: (t: AssetType) => void; onDeleted: () => void; categories: string[];
}) {
  const { can } = useAuth();
  const toast = useToast();
  const editable = can("asset_type.write");
  const isNew = !initial.id;
  const [t, setT] = useState(initial);
  const [tab, setTab] = useState<"general" | "properties" | "telemetry" | "controls">("general");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState(false);
  useEffect(() => { setT(initial); setErr(null); }, [initial]);
  const dirty = JSON.stringify(t) !== JSON.stringify(initial);

  const save = async () => {
    setSaving(true);
    setErr(null);
    const body = { name: t.name, category: t.category, description: t.description, icon: t.icon,
      property_schema: t.property_schema, telemetry: t.telemetry, controls: t.controls, visual: t.visual };
    try {
      const saved = isNew ? await api.post<AssetType>("/asset-types", { ...body, key: t.key }) : await api.patch<AssetType>(`/asset-types/${t.id}`, body);
      toast("ok", `${saved.name} saved (v${saved.version})`);
      onSaved(saved);
    } catch (e) { setErr((e as Error).message); } finally { setSaving(false); }
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <span className="swatch" style={{ background: t.visual.color }} />
        <h2>{isNew ? "New asset type" : t.name}</h2>
        {!isNew && <span className="faint small">v{t.version} · used by {t.asset_count} asset(s)</span>}
        {editable && !isNew && (
          <button className="btn sm ghost danger right" onClick={() => setConfirmDel(true)} disabled={t.asset_count > 0}
            title={t.asset_count ? "In use; can't delete" : "Delete"}><Icon name="trash" size={14} /></button>
        )}
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[
        { key: "general", label: "General & visual" },
        { key: "properties", label: `Properties (${t.property_schema.length})` },
        { key: "telemetry", label: `Telemetry (${t.telemetry.length})` },
        { key: "controls", label: `Controls (${t.controls.length})` },
      ]} />
      <div className="panel-body">
        {tab === "general" && (
          <div className="stack">
            <div className="grid-2">
              <Field label="Name" required><input className="input" value={t.name} disabled={!editable} onChange={(e) => setT({ ...t, name: e.target.value })} /></Field>
              <Field label="Key" required help={isNew ? "Lowercase id, e.g. vibration_probe. Can't be changed later." : "Fixed after creation"}>
                <input className="input mono" value={t.key} disabled={!isNew || !editable} onChange={(e) => setT({ ...t, key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} />
              </Field>
              <Field label="Category" required help="Type a new one or reuse an existing category">
                <input className="input" list="cat-list" value={t.category} disabled={!editable} onChange={(e) => setT({ ...t, category: e.target.value.toLowerCase().replace(/\s+/g, "_") })} />
                <datalist id="cat-list">{categories.map((c) => <option key={c} value={c} />)}</datalist>
              </Field>
              <Field label="Default shape" help="Placeholder geometry until a 3D model is uploaded (Phase 2)">
                <select className="select" value={t.visual.shape} disabled={!editable} onChange={(e) => setT({ ...t, visual: { ...t.visual, shape: e.target.value as Shape } })}>
                  {SHAPES.map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
                </select>
              </Field>
              <Field label="Colour">
                <div className="row">
                  <input type="color" value={t.visual.color} disabled={!editable} onChange={(e) => setT({ ...t, visual: { ...t.visual, color: e.target.value } })}
                    style={{ width: 40, height: 32, border: "none", background: "none", padding: 0 }} aria-label="Colour" />
                  <span className="mono muted">{t.visual.color}</span>
                </div>
              </Field>
              <Field label="Default size W × H × D (m)">
                <div className="row">
                  {[0, 1, 2].map((i) => (
                    <input key={i} className="input" type="number" step="any" min={0.01} value={t.visual.size[i]} disabled={!editable}
                      aria-label={["Width", "Height", "Depth"][i]}
                      onChange={(e) => { const size = [...t.visual.size] as [number, number, number]; size[i] = Number(e.target.value); setT({ ...t, visual: { ...t.visual, size } }); }} />
                  ))}
                </div>
              </Field>
            </div>
            <Field label="Description"><textarea className="input" value={t.description} disabled={!editable} onChange={(e) => setT({ ...t, description: e.target.value })} /></Field>
          </div>
        )}
        {tab === "properties" && (
          <>
            <p className="muted small" style={{ marginTop: 0 }}>Custom attributes every asset of this type carries (ratings, sizes, options). Removing a property deletes its values from existing assets.</p>
            <DefTable rows={t.property_schema} cols={propCols} blank={blankProp} disabled={!editable} addLabel="Add property"
              onChange={(rows) => setT({ ...t, property_schema: rows })} />
          </>
        )}
        {tab === "telemetry" && (
          <>
            <p className="muted small" style={{ marginTop: 0 }}>Measurements devices can report for this type. Warn/alarm limits drive alerts in Phase 6.</p>
            <DefTable rows={t.telemetry} cols={telCols} blank={blankTel} disabled={!editable} addLabel="Add measurement"
              onChange={(rows) => setT({ ...t, telemetry: rows })} />
          </>
        )}
        {tab === "controls" && (
          <>
            <div className="notice warn" style={{ marginBottom: 10 }}>
              <span>These only declare which commands are possible. Commands can't be executed until the Phase 5 control engine (validation, interlocks, acknowledgement) exists. Physical safety stays with PLCs and hardwired safety circuits.</span>
            </div>
            <DefTable rows={t.controls} cols={ctlCols} blank={blankCtl} disabled={!editable} addLabel="Add control"
              onChange={(rows) => setT({ ...t, controls: rows.map((r) => ({ ...r, feedback_measurement: r.feedback_measurement || null })) })} />
          </>
        )}
        {err && <div className="notice bad" style={{ marginTop: 12 }}>{err}</div>}
        {editable && (
          <div className="row" style={{ justifyContent: "flex-end", borderTop: "1px solid var(--border)", paddingTop: 12, marginTop: 14 }}>
            {dirty && <span className="faint small" style={{ marginRight: "auto" }}>Unsaved changes{!isNew && t.asset_count > 0 ? ` · applies to ${t.asset_count} asset(s)` : ""}</span>}
            <button className="btn" disabled={!dirty} onClick={() => setT(initial)}>Revert</button>
            <button className="btn primary" disabled={!dirty || saving || !t.name || !t.key || !t.category} onClick={save}>{isNew ? "Create type" : "Save type"}</button>
          </div>
        )}
      </div>
      {confirmDel && (
        <Confirm title={`Delete ${t.name}?`} message="This asset type will be removed. It's not used by any asset." onClose={() => setConfirmDel(false)}
          onConfirm={async () => { try { await api.del(`/asset-types/${t.id}`); toast("ok", "Deleted"); onDeleted(); } catch (e) { toast("bad", (e as Error).message); } }} />
      )}
    </section>
  );
}

export function AssetTypesPage() {
  const { can } = useAuth();
  const types = useApi(() => api.get<AssetType[]>("/asset-types"), []);
  const [selected, setSelected] = useState<AssetType | null>(null);
  const [q, setQ] = useState("");
  if (types.error) return <ErrorNote error={types.error} onRetry={types.reload} />;
  if (!types.data) return <Loading />;
  const list = types.data.filter((t) => `${t.name} ${t.category} ${t.key}`.toLowerCase().includes(q.toLowerCase()));
  const cats = [...new Set(list.map((t) => t.category))];
  const allCats = [...new Set(types.data.map((t) => t.category))];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Asset types</h1>
          <div className="sub">Define kinds of machines and sensors (properties, measurements, controls) without code changes.</div>
        </div>
        <div className="actions">
          {can("asset_type.write") && <button className="btn primary" onClick={() => setSelected(blankType())}><Icon name="plus" />New type</button>}
        </div>
      </div>
      <div className="split" style={{ gridTemplateColumns: "minmax(260px, 0.5fr) minmax(0, 1.5fr)" }}>
        <section className="panel">
          <div className="toolbar"><input className="input" placeholder="Search types…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <div className="scroll" style={{ maxHeight: "calc(100vh - 220px)" }}>
            {cats.map((c) => (
              <div key={c}>
                <div className="section-title" style={{ margin: "12px 12px 4px" }}>{titleCase(c)}</div>
                <table className="table"><tbody>
                  {list.filter((t) => t.category === c).map((t) => (
                    <tr key={t.id} className={`clickable${selected?.id === t.id ? " selected" : ""}`} onClick={() => setSelected(t)}>
                      <td><span className="swatch" style={{ background: t.visual.color, marginRight: 8 }} />{t.name}</td>
                      <td className="faint small num">{t.asset_count}</td>
                    </tr>
                  ))}
                </tbody></table>
              </div>
            ))}
          </div>
        </section>
        {selected ? (
          <TypeEditor key={selected.id || "new"} initial={selected} categories={allCats}
            onSaved={async (t) => { await types.reload(); setSelected(t); }}
            onDeleted={async () => { setSelected(null); await types.reload(); }} />
        ) : (
          <section className="panel"><Empty title="Select an asset type">Or create a new one for equipment the library doesn't cover.</Empty></section>
        )}
      </div>
    </>
  );
}
