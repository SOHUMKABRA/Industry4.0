import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, qs } from "../api/client";
import { Asset, AssetType, Dashboard, Widget, WidgetType } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Gauge, TrendChart } from "../components/charts";
import { Icon } from "../components/Icon";
import { useToast } from "../components/Toast";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal, Pill } from "../components/ui";
import { uuid } from "../editor/store";
import { useFactory } from "../layout/FactoryContext";
import { formatValue, titleCase } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useNow, useTelemetry } from "../live/hooks";
import { useLiveMeta } from "../live/liveMeta";
import { LiveValue, useTrend } from "../live/LiveValue";
import { CONDITION_STYLE, freshness, severity } from "../live/status";
import { SourceBanner, usePlantStatus } from "../live/plant";

const WIDGET_TYPES: { type: WidgetType; label: string; needs: boolean; numeric?: boolean; size: Widget["size"] }[] = [
  { type: "value", label: "Live value", needs: true, size: "s" },
  { type: "gauge", label: "Gauge", needs: true, numeric: true, size: "s" },
  { type: "trend", label: "Trend chart", needs: true, numeric: true, size: "l" },
  { type: "state", label: "Equipment state", needs: true, size: "s" },
  { type: "kpis", label: "Plant status KPIs", needs: false, size: "w" },
  { type: "alarms", label: "Limit violations", needs: false, size: "m" },
  { type: "devices", label: "Data sources", needs: false, size: "m" },
];

interface Ctx { assets: Record<string, Asset>; types: Record<string, AssetType>; assetList: Asset[] }

function defOf(ctx: Ctx, w: Widget) {
  const a = w.asset_id ? ctx.assets[w.asset_id] : undefined;
  const t = a ? ctx.types[a.asset_type_id] : undefined;
  return { a, t, d: t?.telemetry.find((x) => x.key === w.measurement) };
}

function ValueWidget({ w, ctx }: { w: Widget; ctx: Ctx }) {
  const { a, d } = defOf(ctx, w);
  if (!a || !d) return <p className="faint small">Asset or measurement no longer exists.</p>;
  return (
    <div className="w-value">
      <LiveValue assetId={a.id} def={d} big />
      <div className="faint small">{a.code} · {d.label}</div>
    </div>
  );
}

function GaugeWidget({ w, ctx }: { w: Widget; ctx: Ctx }) {
  const { a, d } = defOf(ctx, w);
  const tv = useTelemetry(a?.id, d?.key);
  const now = useNow(1000);
  if (!a || !d) return <p className="faint small">Asset or measurement no longer exists.</p>;
  const f = freshness(tv, d, now);
  const v = typeof tv?.v === "number" ? tv.v : null;
  const sev = f === "fresh" ? severity(d, v) : "ok";
  return (
    <div className="w-gauge">
      <Gauge value={v} def={d} stale={f !== "fresh"} />
      <div className={`w-gauge-val ${sev === "alarm" ? "sev-alarm" : sev === "warn" ? "sev-warn" : ""}`}>
        {v === null ? "—" : formatValue(v, d.unit)}{f === "stale" && <span className="stale-tag">stale</span>}
      </div>
      <div className="faint small">{a.code} · {d.label}</div>
    </div>
  );
}

function TrendWidget({ w, ctx }: { w: Widget; ctx: Ctx }) {
  const { a, d } = defOf(ctx, w);
  const trend = useTrend(a?.id, d?.key, w.minutes, 150);
  if (!a || !d) return <p className="faint small">Asset or measurement no longer exists.</p>;
  if (trend.error) return <ErrorNote error={trend.error} />;
  return (
    <>
      <div className="row small"><span className="faint">{a.code} · {d.label} · last {w.minutes < 60 ? `${w.minutes} min` : `${w.minutes / 60} h`}</span><span className="right"><LiveValue assetId={a.id} def={d} /></span></div>
      <TrendChart points={trend.hist?.points ?? []} live={trend.live} def={d} from={trend.from} to={trend.to} height={150} />
    </>
  );
}

function StateWidget({ w, ctx }: { w: Widget; ctx: Ctx }) {
  const { a, d } = defOf(ctx, w);
  const tv = useTelemetry(a?.id, d?.key);
  const now = useNow(1000);
  if (!a || !d) return <p className="faint small">Asset or measurement no longer exists.</p>;
  const f = freshness(tv, d, now);
  const state = f === "fresh" ? String(tv!.v) : null;
  const key = (state === "emergency_stop" ? "estop" : state) as keyof typeof CONDITION_STYLE;
  const style = state && CONDITION_STYLE[key] ? CONDITION_STYLE[key] : f === "stale" ? CONDITION_STYLE.stale : f === "none" ? CONDITION_STYLE.nodata : CONDITION_STYLE.ok;
  return (
    <div className="w-state">
      <div className="w-state-badge" style={{ borderColor: style.color, color: style.color }}>{state ? titleCase(state) : style.label}</div>
      <div className="faint small">{a.code} · {a.name}</div>
    </div>
  );
}

function KpisWidget({ ctx }: { ctx: Ctx }) {
  const p = usePlantStatus(ctx.assetList, ctx.types);
  const tiles = [
    ["Running", p.running, "ok"], ["Stopped / idle", p.stopped, ""], ["Fault / E-stop", p.fault, p.fault ? "bad" : ""],
    ["Alarms", p.alarm, p.alarm ? "bad" : ""], ["Warnings", p.warn, p.warn ? "warn" : ""], ["Stale / no data", p.noData, p.noData ? "warn" : ""],
  ] as const;
  return <div className="mon-kpis">{tiles.map(([l, v, t]) => <div key={l} className={`mon-kpi ${t}`}><span>{l}</span><strong>{v}</strong></div>)}</div>;
}

function AlarmsWidget({ ctx }: { ctx: Ctx }) {
  const p = usePlantStatus(ctx.assetList, ctx.types);
  const list = p.rows.flatMap((r) => r.live.violations.map((v) => ({ ...v, asset: r.asset }))).sort((a, b) => (a.sev === b.sev ? 0 : a.sev === "alarm" ? -1 : 1));
  if (!list.length) return <p className="muted small" style={{ margin: 0 }}>No measurement is outside its limits right now.</p>;
  return (
    <table className="table compact">
      <tbody>
        {list.map((v) => (
          <tr key={`${v.asset.id}${v.def.key}`}>
            <td><Pill tone={v.sev === "alarm" ? "bad" : "warn"}>{v.sev === "alarm" ? "Alarm" : "Warning"}</Pill></td>
            <td><Link to={`/monitor`} className="mono small">{v.asset.code}</Link></td>
            <td className="small">{v.def.label}</td>
            <td className="num small">{formatValue(v.value, v.def.unit)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DevicesWidget({ ctx }: { ctx: Ctx }) {
  const devices = useLiveMeta((s) => s.devices);
  const status = useLiveMeta((s) => s.status);
  const off = devices.filter((d) => !d.online);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row">
        <strong style={{ fontSize: 22 }}>{devices.length - off.length}/{devices.length}</strong><span className="muted small">online</span>
        <span className="right">{status === "open" ? <Pill tone="ok">Feed connected</Pill> : <Pill tone="bad">Feed disconnected</Pill>}</span>
      </div>
      {off.slice(0, 6).map((d) => <div key={d.device_id} className="small"><Pill tone="bad" dot>{ctx.assets[d.asset_id]?.code ?? "?"}</Pill> <span className="faint">{d.error || "no recent data"}</span></div>)}
      {!off.length && devices.length > 0 && <p className="faint small" style={{ margin: 0 }}>All active data sources are reporting.</p>}
    </div>
  );
}

function WidgetBody({ w, ctx }: { w: Widget; ctx: Ctx }) {
  switch (w.type) {
    case "value": return <ValueWidget w={w} ctx={ctx} />;
    case "gauge": return <GaugeWidget w={w} ctx={ctx} />;
    case "trend": return <TrendWidget w={w} ctx={ctx} />;
    case "state": return <StateWidget w={w} ctx={ctx} />;
    case "kpis": return <KpisWidget ctx={ctx} />;
    case "alarms": return <AlarmsWidget ctx={ctx} />;
    case "devices": return <DevicesWidget ctx={ctx} />;
  }
}

function WidgetModal({ initial, ctx, onClose, onSave }: { initial?: Widget; ctx: Ctx; onClose: () => void; onSave: (w: Widget) => void }) {
  const [w, setW] = useState<Widget>(initial ?? { id: uuid().slice(0, 8), type: "value", title: "", size: "s", asset_id: null, measurement: null, minutes: 30 });
  const meta = WIDGET_TYPES.find((x) => x.type === w.type)!;
  const asset = w.asset_id ? ctx.assets[w.asset_id] : undefined;
  const defs = (asset ? ctx.types[asset.asset_type_id]?.telemetry ?? [] : []).filter((d) => !meta.numeric || d.data_type === "number" || d.data_type === "integer");
  const withTelemetry = ctx.assetList.filter((a) => (ctx.types[a.asset_type_id]?.telemetry.length ?? 0) > 0);
  const valid = !meta.needs || (w.asset_id && w.measurement && defs.some((d) => d.key === w.measurement));
  return (
    <Modal title={initial ? "Edit widget" : "Add widget"} onClose={onClose} footer={<>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn primary" disabled={!valid} onClick={() => onSave(meta.needs ? w : { ...w, asset_id: null, measurement: null })}>{initial ? "Update" : "Add"}</button>
    </>}>
      <div className="stack">
        <div className="choice-grid">
          {WIDGET_TYPES.map((t) => (
            <button key={t.type} className={`choice${w.type === t.type ? " selected" : ""}`} onClick={() => setW({ ...w, type: t.type, size: initial ? w.size : t.size })}>
              <div className="t">{t.label}</div>
            </button>
          ))}
        </div>
        <div className="grid-2">
          <Field label="Title" help="Optional"><input className="input" value={w.title} onChange={(e) => setW({ ...w, title: e.target.value })} /></Field>
          <Field label="Size">
            <select className="select" value={w.size} onChange={(e) => setW({ ...w, size: e.target.value as Widget["size"] })}>
              <option value="s">Small (1 column)</option><option value="m">Medium (2 columns)</option>
              <option value="l">Large (2 columns, tall)</option><option value="w">Full width</option>
            </select>
          </Field>
          {meta.needs && (
            <>
              <Field label="Asset" required>
                <select className="select" value={w.asset_id ?? ""} onChange={(e) => setW({ ...w, asset_id: e.target.value || null, measurement: null })}>
                  <option value="">Select…</option>
                  {withTelemetry.map((a) => <option key={a.id} value={a.id}>{a.code} – {a.name}</option>)}
                </select>
              </Field>
              <Field label="Measurement" required>
                <select className="select" value={w.measurement ?? ""} disabled={!asset} onChange={(e) => setW({ ...w, measurement: e.target.value || null })}>
                  <option value="">Select…</option>
                  {defs.map((d) => <option key={d.key} value={d.key}>{d.label}{d.unit ? ` (${d.unit})` : ""}</option>)}
                </select>
              </Field>
            </>
          )}
          {w.type === "trend" && (
            <Field label="Period">
              <select className="select" value={w.minutes} onChange={(e) => setW({ ...w, minutes: Number(e.target.value) })}>
                {[5, 15, 30, 60, 180, 360, 720, 1440].map((x) => <option key={x} value={x}>{x < 60 ? `${x} min` : `${x / 60} h`}</option>)}
              </select>
            </Field>
          )}
        </div>
      </div>
    </Modal>
  );
}

export function DashboardPage() {
  const { factory } = useFactory();
  const { me, can } = useAuth();
  const toast = useToast();
  const fid = factory?.id;
  const dashboards = useApi(() => (fid ? api.get<Dashboard[]>(`/dashboards${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const assets = useApi(() => (fid ? api.get<Asset[]>(`/assets${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const types = useApi(() => api.get<AssetType[]>("/asset-types"), []);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Widget[]>([]);
  const [modal, setModal] = useState<{ w?: Widget } | null>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const [confirmDel, setConfirmDel] = useState(false);
  const [newName, setNewName] = useState<string | null>(null);

  const list = dashboards.data ?? [];
  const active = list.find((d) => d.id === activeId) ?? list[0];
  useEffect(() => { setEditing(false); }, [active?.id]);

  const ctx: Ctx = useMemo(() => ({
    assets: Object.fromEntries((assets.data ?? []).map((a) => [a.id, a])),
    types: Object.fromEntries((types.data ?? []).map((t) => [t.id, t])),
    assetList: assets.data ?? [],
  }), [assets.data, types.data]);

  if (!factory) return <div className="panel"><Empty title="No factory selected" /></div>;
  if (dashboards.error) return <ErrorNote error={dashboards.error} onRetry={dashboards.reload} />;
  if (!dashboards.data || !assets.data || !types.data) return <Loading />;

  const mayEdit = !!active && (active.created_by === me?.user.email || can("factory.write"));
  const widgets = editing ? draft : active?.widgets ?? [];

  const create = async (name: string) => {
    try {
      const d = await api.post<Dashboard>("/dashboards", { factory_id: factory.id, name, widgets: [
        { id: "k1", type: "kpis", title: "Plant status", size: "w", asset_id: null, measurement: null, minutes: 30 },
        { id: "a1", type: "alarms", title: "Limit violations", size: "m", asset_id: null, measurement: null, minutes: 30 },
        { id: "d1", type: "devices", title: "Data sources", size: "m", asset_id: null, measurement: null, minutes: 30 },
      ] });
      await dashboards.reload();
      setActiveId(d.id);
      setDraft(d.widgets);
      setEditing(true);
    } catch (e) { toast("bad", (e as Error).message); }
  };
  const save = async () => {
    try {
      await api.patch(`/dashboards/${active!.id}`, { widgets: draft });
      await dashboards.reload();
      setEditing(false);
      toast("ok", "Dashboard saved");
    } catch (e) { toast("bad", (e as Error).message); }
  };
  const move = (from: number, to: number) => {
    if (from === to) return;
    const next = [...draft];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    setDraft(next);
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboards</h1>
          <div className="sub">Live operational views for {factory.name}. Anyone can create their own; layouts are shared within the organization.</div>
        </div>
        <div className="actions">
          {editing ? (
            <>
              <button className="btn" onClick={() => setModal({})}><Icon name="plus" />Add widget</button>
              <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
              <button className="btn primary" onClick={save}>Save dashboard</button>
            </>
          ) : (
            <>
              {mayEdit && <button className="btn" onClick={() => { setDraft(active!.widgets); setEditing(true); }}><Icon name="edit" />Edit</button>}
              <button className="btn primary" onClick={() => setNewName("")}><Icon name="plus" />New dashboard</button>
            </>
          )}
        </div>
      </div>
      <SourceBanner />
      {list.length > 0 && (
        <div className="dash-tabs">
          {list.map((d) => (
            <button key={d.id} className={d.id === active?.id ? "active" : ""} onClick={() => setActiveId(d.id)}>{d.name}</button>
          ))}
          {editing && mayEdit && <button className="btn sm ghost danger right" onClick={() => setConfirmDel(true)}>Delete dashboard</button>}
        </div>
      )}
      {!active ? (
        <div className="panel"><Empty title="No dashboards yet" action={<button className="btn primary" onClick={() => setNewName("Plant overview")}>Create dashboard</button>}>Build a dashboard from live values, gauges, trends and plant KPIs.</Empty></div>
      ) : (
        <div className={`dash-grid${editing ? " editing" : ""}`}>
          {widgets.map((w, i) => (
            <section key={w.id} className={`panel widget size-${w.size}${drag === i ? " dragging" : ""}`}
              draggable={editing} onDragStart={() => setDrag(i)} onDragEnd={() => setDrag(null)}
              onDragOver={(e) => { if (editing && drag !== null) { e.preventDefault(); } }}
              onDrop={(e) => { e.preventDefault(); if (drag !== null) move(drag, i); setDrag(null); }}>
              <div className="widget-head">
                <h3>{w.title || WIDGET_TYPES.find((x) => x.type === w.type)?.label}</h3>
                {editing && (
                  <div className="row right">
                    <span className="faint small drag-handle" title="Drag to reorder">⠿</span>
                    <button className="btn sm ghost" onClick={() => setModal({ w })} aria-label="Edit widget"><Icon name="edit" size={13} /></button>
                    <button className="btn sm ghost danger" onClick={() => setDraft(draft.filter((x) => x.id !== w.id))} aria-label="Remove widget"><Icon name="x" size={13} /></button>
                  </div>
                )}
              </div>
              <div className="widget-body"><WidgetBody w={w} ctx={ctx} /></div>
            </section>
          ))}
          {editing && !widgets.length && <div className="panel"><Empty title="Empty dashboard" action={<button className="btn primary" onClick={() => setModal({})}>Add widget</button>} /></div>}
        </div>
      )}
      {modal && (
        <WidgetModal initial={modal.w} ctx={ctx} onClose={() => setModal(null)}
          onSave={(w) => { setDraft(modal.w ? draft.map((x) => (x.id === w.id ? w : x)) : [...draft, w]); setModal(null); }} />
      )}
      {newName !== null && (
        <Modal title="New dashboard" onClose={() => setNewName(null)} footer={<>
          <button className="btn" onClick={() => setNewName(null)}>Cancel</button>
          <button className="btn primary" disabled={!newName.trim()} onClick={() => { const n = newName; setNewName(null); void create(n); }}>Create</button>
        </>}>
          <Field label="Name" required><input className="input" value={newName} onChange={(e) => setNewName(e.target.value)} autoFocus /></Field>
        </Modal>
      )}
      {confirmDel && active && (
        <Confirm title={`Delete ${active.name}?`} message="This dashboard will be removed for everyone in the organization." onClose={() => setConfirmDel(false)}
          onConfirm={async () => {
            setConfirmDel(false);
            try { await api.del(`/dashboards/${active.id}`); setActiveId(null); setEditing(false); await dashboards.reload(); } catch (e) { toast("bad", (e as Error).message); }
          }} />
      )}
    </>
  );
}
