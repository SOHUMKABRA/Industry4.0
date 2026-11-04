import { useMemo, useState } from "react";
import { ApiError, api, qs } from "../api/client";
import { Asset, AssetType, Channel, Execution, Rule } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { useToast } from "../components/Toast";
import { Confirm, Empty, ErrorNote, Field, Loading, Modal, Pill } from "../components/ui";
import { useFactory } from "../layout/FactoryContext";
import { timeAgo, titleCase } from "../lib/format";
import { useApi } from "../lib/useApi";

const OPS = ["==", "!=", ">", ">=", "<", "<="];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
type Draft = Omit<Rule, "id" | "created_by" | "version" | "last_fired_at"> & { id?: string };

const blank = (fid: string): Draft => ({
  factory_id: fid, name: "", description: "", enabled: false, cooldown_s: 60,
  trigger: { type: "condition", days: [0, 1, 2, 3, 4, 5, 6] },
  conditions: { match: "all", for_s: 0, items: [] },
  actions: [{ type: "alert", severity: "warning", message: "" }],
});

function execTone(s: string) {
  return s === "succeeded" ? "ok" : s === "failed" ? "bad" : s === "partial" ? "warn" : s === "dry_run" ? "info" : "neutral";
}

function describe(r: Rule | Draft, assets: Record<string, Asset>) {
  const t = r.trigger.type === "schedule"
    ? (r.trigger.every_minutes ? `Every ${r.trigger.every_minutes} min` : `Daily at ${r.trigger.daily_at}`)
    : r.conditions.items.map((c) => `${assets[c.asset_id]?.code ?? "?"}.${c.measurement} ${c.operator} ${c.value}`).join(r.conditions.match === "all" ? " AND " : " OR ")
      + (r.conditions.for_s ? ` for ${r.conditions.for_s}s` : "");
  const a = r.actions.map((x) => x.type === "command" ? `${x.control} ${assets[x.asset_id ?? ""]?.code ?? "?"}` : x.type === "delay" ? `wait ${x.seconds}s` : x.type).join(" → ");
  return { t, a };
}

function RuleEditor({ initial, assets, types, channels, onClose, onSaved }: {
  initial: Draft; assets: Asset[]; types: Record<string, AssetType>; channels: Channel[]; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const [r, setR] = useState<Draft>(initial);
  const [err, setErr] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const byId = useMemo(() => Object.fromEntries(assets.map((a) => [a.id, a])), [assets]);
  const withTelemetry = assets.filter((a) => (types[a.asset_type_id]?.telemetry.length ?? 0) > 0);
  const withControls = assets.filter((a) => (types[a.asset_type_id]?.controls.length ?? 0) > 0);
  const defsOf = (id: string) => types[byId[id]?.asset_type_id]?.telemetry ?? [];
  const setItem = (i: number, p: Partial<Draft["conditions"]["items"][0]>) =>
    setR({ ...r, conditions: { ...r.conditions, items: r.conditions.items.map((x, j) => (j === i ? { ...x, ...p } : x)) } });
  const setAction = (i: number, p: Partial<Draft["actions"][0]>) => setR({ ...r, actions: r.actions.map((x, j) => (j === i ? { ...x, ...p } : x)) });

  const save = async () => {
    setErr(null);
    const body = { ...r, id: undefined };
    try {
      const res = r.id ? await api.put<Rule>(`/automations/${r.id}`, body) : await api.post<Rule>("/automations", body);
      if (res.warnings?.length) toast("info", res.warnings.join(" "));
      toast("ok", `Automation '${res.name}' saved${res.enabled ? " and enabled" : ""}`);
      onSaved();
    } catch (e) {
      const fields = e instanceof ApiError ? Object.values(e.fieldErrors) : [];
      setErr(fields.length ? fields.join(" · ") : (e as Error).message);
    }
  };
  const check = async () => {
    try { setWarnings((await api.post<{ warnings: string[] }>("/automations/validate", { ...r, id: undefined })).warnings); setErr(null); toast("ok", "Rule is valid"); }
    catch (e) { const f = e instanceof ApiError ? Object.values(e.fieldErrors) : []; setErr(f.length ? f.join(" · ") : (e as Error).message); }
  };

  return (
    <Modal wide title={r.id ? `Edit automation` : "New automation"} onClose={onClose} footer={<>
      <button className="btn ghost" style={{ marginRight: "auto" }} onClick={check}>Validate</button>
      <label className="check"><input type="checkbox" checked={r.enabled} onChange={(e) => setR({ ...r, enabled: e.target.checked })} />Enabled</label>
      <button className="btn" onClick={onClose}>Cancel</button>
      <button className="btn primary" disabled={!r.name.trim()} onClick={save}>Save</button>
    </>}>
      <div className="stack">
        <div className="grid-2">
          <Field label="Name" required><input className="input" value={r.name} onChange={(e) => setR({ ...r, name: e.target.value })} autoFocus /></Field>
          <Field label="Description"><input className="input" value={r.description} onChange={(e) => setR({ ...r, description: e.target.value })} /></Field>
        </div>

        <div className="rule-block">
          <div className="rule-head">
            <strong>WHEN</strong>
            <div className="seg">
              <button className={`btn sm${r.trigger.type === "condition" ? " active" : ""}`} onClick={() => setR({ ...r, trigger: { ...r.trigger, type: "condition" } })}>Condition</button>
              <button className={`btn sm${r.trigger.type === "schedule" ? " active" : ""}`} onClick={() => setR({ ...r, trigger: { ...r.trigger, type: "schedule", daily_at: r.trigger.daily_at ?? "06:00" } })}>Schedule</button>
            </div>
          </div>
          {r.trigger.type === "schedule" && (
            <div className="row wrap" style={{ marginBottom: 10 }}>
              <select className="select" style={{ width: 160 }} value={r.trigger.every_minutes ? "every" : "daily"}
                onChange={(e) => setR({ ...r, trigger: e.target.value === "every" ? { ...r.trigger, every_minutes: 15, daily_at: null } : { ...r.trigger, every_minutes: null, daily_at: "06:00" } })}>
                <option value="daily">Daily at</option><option value="every">Every N minutes</option>
              </select>
              {r.trigger.every_minutes ? (
                <input className="input" type="number" min={1} max={1440} style={{ width: 100 }} value={r.trigger.every_minutes}
                  onChange={(e) => setR({ ...r, trigger: { ...r.trigger, every_minutes: Number(e.target.value) } })} />
              ) : (
                <>
                  <input className="input" type="time" style={{ width: 120 }} value={r.trigger.daily_at ?? "06:00"} onChange={(e) => setR({ ...r, trigger: { ...r.trigger, daily_at: e.target.value } })} />
                  {DAYS.map((d, i) => (
                    <label key={d} className="check small chip-check"><input type="checkbox" checked={r.trigger.days.includes(i)}
                      onChange={(e) => setR({ ...r, trigger: { ...r.trigger, days: e.target.checked ? [...r.trigger.days, i].sort() : r.trigger.days.filter((x) => x !== i) } })} />{d}</label>
                  ))}
                </>
              )}
              <span className="faint small">Factory local time. Conditions below act as a guard (run only if true).</span>
            </div>
          )}
          {r.conditions.items.map((c, i) => {
            const defs = defsOf(c.asset_id);
            const def = defs.find((d) => d.key === c.measurement);
            return (
              <div key={i} className="rule-row">
                <span className="rule-joiner">{i === 0 ? "IF" : r.conditions.match === "all" ? "AND" : "OR"}</span>
                <select className="select" value={c.asset_id} onChange={(e) => setItem(i, { asset_id: e.target.value, measurement: defsOf(e.target.value)[0]?.key ?? "" })} aria-label="Equipment">
                  {withTelemetry.map((a) => <option key={a.id} value={a.id}>{a.code} – {a.name}</option>)}
                </select>
                <select className="select" value={c.measurement} onChange={(e) => setItem(i, { measurement: e.target.value })} aria-label="Measurement">
                  {defs.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
                </select>
                <select className="select" style={{ width: 70 }} value={c.operator} onChange={(e) => setItem(i, { operator: e.target.value })} aria-label="Operator">
                  {OPS.map((o) => <option key={o}>{o}</option>)}
                </select>
                {def?.options.length ? (
                  <select className="select" value={c.value} onChange={(e) => setItem(i, { value: e.target.value })} aria-label="Value">
                    <option value="">Select…</option>{def.options.map((o) => <option key={o}>{o}</option>)}
                  </select>
                ) : (
                  <div className="input-unit" style={{ width: 140 }}><input className="input" value={c.value} onChange={(e) => setItem(i, { value: e.target.value })} aria-label="Value" />{def?.unit && <span className="unit">{def.unit}</span>}</div>
                )}
                <button className="btn sm ghost danger" onClick={() => setR({ ...r, conditions: { ...r.conditions, items: r.conditions.items.filter((_, j) => j !== i) } })} aria-label="Remove"><Icon name="x" size={13} /></button>
              </div>
            );
          })}
          <div className="row wrap">
            <button className="btn sm" onClick={() => { const a = withTelemetry[0]; if (a) setR({ ...r, conditions: { ...r.conditions, items: [...r.conditions.items, { asset_id: a.id, measurement: defsOf(a.id)[0]?.key ?? "", operator: ">", value: "" }] } }); }}>
              <Icon name="plus" size={13} />Condition</button>
            {r.conditions.items.length > 1 && (
              <select className="select sm-select" value={r.conditions.match} onChange={(e) => setR({ ...r, conditions: { ...r.conditions, match: e.target.value as "all" | "any" } })}>
                <option value="all">ALL must be true</option><option value="any">ANY can be true</option>
              </select>
            )}
            {r.trigger.type === "condition" && <label className="small row">held for <input className="input" type="number" min={0} style={{ width: 80, height: 26 }} value={r.conditions.for_s}
              onChange={(e) => setR({ ...r, conditions: { ...r.conditions, for_s: Number(e.target.value) } })} /> s</label>}
          </div>
          <p className="faint small" style={{ margin: "8px 0 0" }}>Missing or stale values count as <strong>false</strong>: rules never act on data they can't trust.</p>
        </div>

        <div className="rule-block">
          <div className="rule-head"><strong>THEN</strong></div>
          {r.actions.map((a, i) => {
            const target = a.asset_id ? assets.find((x) => x.id === a.asset_id) : undefined;
            const controls = target ? types[target.asset_type_id]?.controls ?? [] : [];
            const ctl = controls.find((c) => c.key === a.control);
            return (
              <div key={i} className="rule-row">
                <span className="rule-joiner">{i + 1}</span>
                <select className="select" style={{ width: 150 }} value={a.type} onChange={(e) => setAction(i, { type: e.target.value as Draft["actions"][0]["type"] })} aria-label="Action">
                  <option value="alert">Raise alert</option><option value="notify">Notify</option><option value="command">Send command</option><option value="delay">Wait</option>
                </select>
                {(a.type === "alert" || a.type === "notify") && (
                  <>
                    <select className="select" style={{ width: 110 }} value={a.severity ?? "warning"} onChange={(e) => setAction(i, { severity: e.target.value })} aria-label="Severity">
                      <option value="info">Info</option><option value="warning">Warning</option><option value="alarm">Alarm</option>
                    </select>
                    {a.type === "notify" && (
                      <select className="select" value={a.channel_id ?? ""} onChange={(e) => setAction(i, { channel_id: e.target.value })} aria-label="Channel">
                        <option value="">Channel…</option>{channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                      </select>
                    )}
                    <input className="input" style={{ flex: 2 }} placeholder="Message: {rule}, {value}, {detail} are filled in" value={a.message ?? ""} onChange={(e) => setAction(i, { message: e.target.value })} aria-label="Message" />
                  </>
                )}
                {a.type === "command" && (
                  <>
                    <select className="select" value={a.asset_id ?? ""} onChange={(e) => { const t = assets.find((x) => x.id === e.target.value); setAction(i, { asset_id: e.target.value, control: types[t?.asset_type_id ?? ""]?.controls[0]?.key ?? null, params: {} }); }} aria-label="Target">
                      <option value="">Equipment…</option>{withControls.map((x) => <option key={x.id} value={x.id}>{x.code} – {x.name}</option>)}
                    </select>
                    <select className="select" value={a.control ?? ""} onChange={(e) => setAction(i, { control: e.target.value, params: {} })} aria-label="Command">
                      {controls.map((c) => <option key={c.key} value={c.key}>{c.label}{c.requires_approval ? " (needs approval)" : ""}</option>)}
                    </select>
                    {ctl?.params.map((p) => (
                      <div key={p.key} className="input-unit" style={{ width: 130 }}>
                        <input className="input" type="number" step="any" placeholder={p.label} value={String(a.params?.[p.key] ?? "")}
                          onChange={(e) => setAction(i, { params: { ...a.params, [p.key]: e.target.value === "" ? undefined : Number(e.target.value) } })} aria-label={p.label} />
                        {p.unit && <span className="unit">{p.unit}</span>}
                      </div>
                    ))}
                  </>
                )}
                {a.type === "delay" && <label className="small row"><input className="input" type="number" min={0} max={3600} style={{ width: 90 }} value={a.seconds ?? 0}
                  onChange={(e) => setAction(i, { seconds: Number(e.target.value) })} /> seconds</label>}
                <button className="btn sm ghost danger" onClick={() => setR({ ...r, actions: r.actions.filter((_, j) => j !== i) })} aria-label="Remove"><Icon name="x" size={13} /></button>
              </div>
            );
          })}
          <button className="btn sm" onClick={() => setR({ ...r, actions: [...r.actions, { type: "alert", severity: "warning", message: "" }] })}><Icon name="plus" size={13} />Action</button>
          <p className="faint small" style={{ margin: "8px 0 0" }}>Commands run with <strong>your</strong> permissions through the full safety chain (limits, interlocks, verification). Controls that need approval create a request and wait for a person.</p>
        </div>

        <div className="grid-2">
          <Field label="Cooldown (s)" help="Minimum time between two runs of this rule">
            <input className="input" type="number" min={0} value={r.cooldown_s} onChange={(e) => setR({ ...r, cooldown_s: Number(e.target.value) })} />
          </Field>
        </div>
        {warnings.length > 0 && <div className="notice warn"><span>{warnings.join(" · ")}</span></div>}
        {err && <div className="notice bad">{err}</div>}
      </div>
    </Modal>
  );
}

function RuleHistory({ rule, assets, onClose }: { rule: Rule; assets: Asset[]; onClose: () => void }) {
  const ex = useApi(() => api.get<Execution[]>(`/automations/${rule.id}/executions`), [rule.id]);
  const toast = useToast();
  const [dry, setDry] = useState<Execution | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const byId = Object.fromEntries(assets.map((a) => [a.id, a]));
  const runDry = async () => {
    try {
      const ov = Object.fromEntries(Object.entries(overrides).filter(([, v]) => v !== "").map(([k, v]) => [k, isNaN(Number(v)) ? v : Number(v)]));
      setDry(await api.post<Execution>(`/automations/${rule.id}/dry-run`, { overrides: ov }));
      void ex.reload();
    } catch (e) { toast("bad", (e as Error).message); }
  };
  return (
    <Modal wide title={`${rule.name} · runs`} onClose={onClose}>
      <div className="stack">
        <div className="rule-block">
          <div className="rule-head"><strong>Dry run</strong><span className="faint small">Evaluate against live data (or what-if values) and preview every action. Nothing is sent.</span></div>
          {rule.conditions.items.length > 0 && (
            <div className="row wrap">
              {rule.conditions.items.map((c) => {
                const k = `${c.asset_id}:${c.measurement}`;
                return <label key={k} className="small row">{byId[c.asset_id]?.code}.{c.measurement} = <input className="input" style={{ width: 100, height: 26 }} placeholder="live" value={overrides[k] ?? ""}
                  onChange={(e) => setOverrides({ ...overrides, [k]: e.target.value })} /></label>;
              })}
            </div>
          )}
          <div style={{ marginTop: 8 }}><button className="btn sm primary" onClick={runDry}>Run dry run</button></div>
          {dry && <ExecutionView e={dry} />}
        </div>
        <div className="section-title">History</div>
        {!ex.data ? <Loading /> : ex.data.length === 0 ? <p className="faint">No runs yet.</p> : ex.data.map((e) => <ExecutionView key={e.id} e={e} />)}
      </div>
    </Modal>
  );
}

function ExecutionView({ e }: { e: Execution }) {
  return (
    <div className="exec">
      <div className="row"><Pill tone={execTone(e.status)}>{e.dry_run ? "Dry run" : titleCase(e.status)}</Pill><span className="faint small">{new Date(e.started_at).toLocaleString()}</span></div>
      <pre className="exec-detail">{e.trigger_detail}</pre>
      {e.steps.map((s, i) => (
        <div key={i} className={`exec-step ${s.status}`}><span className="tag">{s.type}</span> <span className="small">{s.detail}</span></div>
      ))}
    </div>
  );
}

export function AutomationsPage() {
  const { factory } = useFactory();
  const { can } = useAuth();
  const toast = useToast();
  const fid = factory?.id;
  const rules = useApi(() => (fid ? api.get<Rule[]>(`/automations${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const assets = useApi(() => (fid ? api.get<Asset[]>(`/assets${qs({ factory_id: fid })}`) : Promise.resolve([])), [fid]);
  const types = useApi(() => api.get<AssetType[]>("/asset-types"), []);
  const channels = useApi(() => api.get<Channel[]>("/notification-channels"), []);
  const [edit, setEdit] = useState<Draft | null>(null);
  const [history, setHistory] = useState<Rule | null>(null);
  const [del, setDel] = useState<Rule | null>(null);
  const typeById = useMemo(() => Object.fromEntries((types.data ?? []).map((t) => [t.id, t])), [types.data]);
  const assetById = useMemo(() => Object.fromEntries((assets.data ?? []).map((a) => [a.id, a])), [assets.data]);
  const editable = can("factory.write");

  const toggle = async (r: Rule) => {
    try { await api.post(`/automations/${r.id}/enabled?enabled=${!r.enabled}`); await rules.reload(); }
    catch (e) { toast("bad", (e as Error).message); }
  };
  if (!factory || !fid) return <div className="panel"><Empty title="No factory selected" /></div>;
  if (rules.error) return <ErrorNote error={rules.error} />;
  const ready = rules.data && assets.data && types.data && channels.data;
  return (
    <>
      <div className="page-head">
        <div><h1>Automations</h1><div className="sub">No-code rules: WHEN a condition holds (or on a schedule) THEN raise alerts, notify, or send commands through the safety engine.</div></div>
        <div className="actions">{editable && <button className="btn primary" disabled={!ready} onClick={() => setEdit(blank(fid))}><Icon name="plus" />New automation</button>}</div>
      </div>
      <section className="panel">
        {!ready ? <Loading /> : rules.data!.length === 0 ? <Empty title="No automations yet">Create a rule, dry-run it, then enable it.</Empty> : (
          <table className="table">
            <thead><tr><th>On</th><th>Rule</th><th>When</th><th>Then</th><th>Last run</th><th /></tr></thead>
            <tbody>
              {rules.data!.map((r) => {
                const d = describe(r, assetById);
                return (
                  <tr key={r.id}>
                    <td><label className="switch" title={r.enabled ? "Enabled" : "Disabled"}><input type="checkbox" checked={r.enabled} disabled={!editable} onChange={() => toggle(r)} /><span /></label></td>
                    <td><strong>{r.name}</strong><div className="faint small">{r.description}</div></td>
                    <td className="small mono">{d.t}</td>
                    <td className="small">{d.a}</td>
                    <td className="faint small">{r.last_fired_at ? timeAgo(r.last_fired_at) : "never"}</td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button className="btn sm ghost" onClick={() => setHistory(r)}>Runs &amp; dry run</button>
                      {editable && <button className="btn sm ghost" onClick={() => setEdit(r)}>Edit</button>}
                      {editable && <button className="btn sm ghost danger" onClick={() => setDel(r)} aria-label="Delete"><Icon name="trash" size={13} /></button>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
      {edit && ready && <RuleEditor initial={edit} assets={assets.data!} types={typeById} channels={channels.data!} onClose={() => setEdit(null)}
        onSaved={() => { setEdit(null); void rules.reload(); }} />}
      {history && assets.data && <RuleHistory rule={history} assets={assets.data} onClose={() => setHistory(null)} />}
      {del && <Confirm title={`Delete '${del.name}'?`} message="The rule and its run history are removed." onClose={() => setDel(null)}
        onConfirm={async () => { setDel(null); try { await api.del(`/automations/${del.id}`); await rules.reload(); } catch (e) { toast("bad", (e as Error).message); } }} />}
    </>
  );
}
