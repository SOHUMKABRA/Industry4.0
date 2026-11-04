import { Fragment, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, qs } from "../api/client";
import { Asset, AssetType, FactoryStructure, ModelFile, SceneWithObjects } from "../api/types";
import { TrendChart } from "../components/charts";
import { Empty, ErrorNote, Loading, Pill } from "../components/ui";
import { SceneCtx } from "../editor/objects";
import { SceneView, SceneViewHandle } from "../editor/SceneView";
import { useFactory } from "../layout/FactoryContext";
import { useApi } from "../lib/useApi";
import { usePlayback } from "../live/clock";
import { PlaybackBar } from "../live/PlaybackBar";
import { ControlPanel } from "../control/ControlPanel";
import { useNow } from "../live/hooks";
import { SourceBanner, usePlantStatus } from "../live/plant";
import { LiveValue, useTrend } from "../live/LiveValue";
import { AssetCondition, assetLive, CONDITION_STYLE } from "../live/status";

const FILTERS: { key: string; label: string; match: (c: AssetCondition) => boolean }[] = [
  { key: "all", label: "All", match: () => true },
  { key: "attention", label: "Needs attention", match: (c) => ["alarm", "fault", "estop", "warn"].includes(c) },
  { key: "running", label: "Running", match: (c) => c === "running" || c === "ok" },
  { key: "stopped", label: "Stopped / idle", match: (c) => c === "stopped" || c === "idle" },
  { key: "nodata", label: "Stale / no data", match: (c) => c === "stale" || c === "nodata" },
];

function AssetDetail({ asset, type }: { asset: Asset; type: AssetType }) {
  const playing = usePlayback((s) => s.active);
  const numeric = type.telemetry.filter((d) => d.data_type === "number" || d.data_type === "integer");
  const [m, setM] = useState(numeric[0]?.key ?? "");
  const [minutes, setMinutes] = useState(30);
  const def = type.telemetry.find((d) => d.key === m);
  const trend = useTrend(asset.id, m || null, minutes);
  const now = useNow(1000);
  const live = assetLive(asset, type, now);
  const st = CONDITION_STYLE[live.condition];
  return (
    <div className="stack">
      <div>
        <div className="row"><span className="code-chip">{asset.code}</span><Pill tone={st.tone}>{st.label}</Pill></div>
        <h2 style={{ marginTop: 6 }}>{asset.name}</h2>
        <div className="faint small">{type.name} · <Link to={`/assets/${asset.id}`}>Configuration</Link></div>
      </div>
      {live.violations.length > 0 && (
        <div className="notice bad"><span>{live.violations.map((v) => `${v.def.label} ${v.sev === "alarm" ? "ALARM" : "warning"} (${v.value}${v.def.unit ? ` ${v.def.unit}` : ""})`).join(" · ")}</span></div>
      )}
      {type.controls.length > 0 && !playing && (
        <div>
          <div className="section-title" style={{ marginTop: 0 }}>Control</div>
          <ControlPanel asset={asset} type={type} compact />
        </div>
      )}
      <dl className="kv small">
        {type.telemetry.map((d) => <Fragment key={d.key}><dt>{d.label}</dt><dd><LiveValue assetId={asset.id} def={d} /></dd></Fragment>)}
      </dl>
      {numeric.length > 0 && playing && <p className="faint small" style={{ margin: 0 }}>Trend charts show live history; they're hidden during playback. Use the timeline above.</p>}
      {numeric.length > 0 && !playing && (
        <div>
          <div className="row" style={{ marginBottom: 6 }}>
            <select className="select" value={m} onChange={(e) => setM(e.target.value)} aria-label="Measurement">
              {numeric.map((d) => <option key={d.key} value={d.key}>{d.label}{d.unit ? ` (${d.unit})` : ""}</option>)}
            </select>
            <select className="select" style={{ width: 110 }} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} aria-label="Period">
              {[5, 15, 30, 60, 180, 360].map((x) => <option key={x} value={x}>{x < 60 ? `${x} min` : `${x / 60} h`}</option>)}
            </select>
          </div>
          {trend.error ? <ErrorNote error={trend.error} /> : <TrendChart points={trend.hist?.points ?? []} live={trend.live} def={def} from={trend.from} to={trend.to} height={170} />}
        </div>
      )}
    </div>
  );
}

export function MonitorPage() {
  const { factory } = useFactory();
  const playback = usePlayback((s) => s.active);
  const fid = factory?.id;
  const sceneRef = useRef<SceneViewHandle>(null);
  const [view, setView] = useState<"3d" | "2d">("3d");
  const [filter, setFilter] = useState("all");
  const [selected, setSelected] = useState<string | null>(null);
  const scene = useApi(() => (fid ? api.get<SceneWithObjects>(`/factories/${fid}/scene`) : Promise.resolve(undefined)), [fid]);
  const types = useApi(() => api.get<AssetType[]>("/asset-types"), []);
  const assets = useApi(() => (fid ? api.get<Asset[]>(`/assets${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const structure = useApi(() => (fid ? api.get<FactoryStructure>(`/factories/${fid}`) : Promise.resolve(undefined)), [fid]);
  const models = useApi(() => api.get<ModelFile[]>("/models"), []);

  const typeById = useMemo(() => Object.fromEntries((types.data ?? []).map((t) => [t.id, t])), [types.data]);
  const assetById = useMemo(() => Object.fromEntries((assets.data ?? []).map((a) => [a.id, a])), [assets.data]);
  const plant = usePlantStatus(assets.data, typeById);
  const { objects, order, objByAsset } = useMemo(() => {
    const objs = scene.data?.objects ?? [];
    return {
      objects: Object.fromEntries(objs.map((o) => [o.id, o])), order: objs.map((o) => o.id),
      objByAsset: Object.fromEntries(objs.filter((o) => o.asset_id).map((o) => [o.asset_id!, o.id])),
    };
  }, [scene.data]);
  const ctx: SceneCtx = useMemo(() => ({
    typeOfAsset: (id) => typeById[assetById[id]?.asset_type_id], assetLabel: (id) => assetById[id]?.code ?? "",
    models: Object.fromEntries((models.data ?? []).map((m) => [m.id, m])), live: true, animate: true, labels: true, view,
  }), [typeById, assetById, models.data, view]);

  if (!factory) return <div className="panel"><Empty title="No factory selected" /></div>;
  if (scene.error) return <ErrorNote error={scene.error} onRetry={scene.reload} />;
  if (!scene.data || !types.data || !assets.data) return <Loading label="Loading live twin…" />;

  const sel = selected ? assetById[selected] : undefined;
  const selObj = selected ? objByAsset[selected] : undefined;
  const fdef = FILTERS.find((f) => f.key === filter)!;
  const rows = plant.rows.filter((r) => fdef.match(r.live.condition));
  const tiles = [
    { label: "Running", value: plant.running, tone: "ok" },
    { label: "Stopped / idle", value: plant.stopped, tone: "neutral" },
    { label: "Fault / E-stop", value: plant.fault, tone: plant.fault ? "bad" : "neutral" },
    { label: "Alarms", value: plant.alarm, tone: plant.alarm ? "bad" : "neutral" },
    { label: "Warnings", value: plant.warn, tone: plant.warn ? "warn" : "neutral" },
    { label: "Stale / no data", value: plant.noData, tone: plant.noData ? "warn" : "neutral" },
  ];

  return (
    <div className="monitor">
      <div className="mon-head">
        <h1>Live monitoring</h1>
        <div className="mon-kpis">
          {tiles.map((t) => <div key={t.label} className={`mon-kpi ${t.tone}`}><span>{t.label}</span><strong>{t.value}</strong></div>)}
        </div>
      </div>
      {fid && <PlaybackBar factoryId={fid} />}
      {!playback && <SourceBanner />}
      {playback && <div className="notice warn"><span><strong>Historical playback.</strong> Values are recorded history (tagged REPLAY), not the current plant state. Controls are disabled until you return to live.</span></div>}
      <div className="mon-body">
        <section className="panel mon-list">
          <div className="toolbar">
            <select className="select" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter">
              {FILTERS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select>
            <span className="faint small right">{rows.length}</span>
          </div>
          <div className="scroll">
            {rows.map(({ asset, live }) => {
              const st = CONDITION_STYLE[live.condition];
              return (
                <div key={asset.id} className={`mon-row${asset.id === selected ? " selected" : ""}`} onClick={() => setSelected(asset.id)}>
                  <span className="dot-lg" style={{ background: st.color }} />
                  <div style={{ minWidth: 0 }}>
                    <div className="mono small">{asset.code}</div>
                    <div className="lib-name small muted">{asset.name}</div>
                  </div>
                  <span className="right small" style={{ color: st.color }}>{st.label}</span>
                </div>
              );
            })}
            {!rows.length && <p className="faint small" style={{ padding: 12 }}>Nothing matches.</p>}
          </div>
        </section>
        <div className="mon-canvas">
          <SceneView ref={sceneRef} objects={objects} order={order} selected={selObj ? [selObj] : []} structure={structure.data} ctx={ctx} editable={false}
            onSelect={(ids) => setSelected(ids.length ? objects[ids[0]]?.asset_id ?? null : null)} />
          <div className="mon-overlay">
            <div className="seg">
              <button className={`btn sm${view === "3d" ? " active" : ""}`} onClick={() => setView("3d")}>3D</button>
              <button className={`btn sm${view === "2d" ? " active" : ""}`} onClick={() => setView("2d")}>2D</button>
            </div>
            <button className="btn sm" onClick={() => sceneRef.current?.frame()}>Frame</button>
          </div>
          <div className="legend">
            {(["running", "stopped", "warn", "alarm", "fault", "stale", "nodata"] as AssetCondition[]).map((c) => (
              <span key={c}><i style={{ background: CONDITION_STYLE[c].color }} />{CONDITION_STYLE[c].label}</span>
            ))}
          </div>
        </div>
        <section className="panel mon-detail">
          <div className="panel-body">
            {sel && typeById[sel.asset_type_id] ? <AssetDetail key={sel.id} asset={sel} type={typeById[sel.asset_type_id]} /> : (
              <Empty title="Select equipment">Click a machine in the twin or the list to see its live values and trends.</Empty>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
