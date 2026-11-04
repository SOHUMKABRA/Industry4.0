import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, qs } from "../api/client";
import { Asset, AssetType, Command, CommandStatus, ControlDef, ValidationResult } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";
import { Field, Modal, Pill, Tone } from "../components/ui";
import { titleCase } from "../lib/format";
import { useCommands } from "../live/liveMeta";

export const TERMINAL = new Set<CommandStatus>(["COMPLETED", "REJECTED", "FAILED", "TIMED_OUT", "CANCELLED"]);
const FLOW: CommandStatus[] = ["REQUESTED", "VALIDATING", "APPROVED", "SENT", "ACKNOWLEDGED", "COMPLETED"];

export function statusTone(c: Pick<Command, "status" | "verified">): Tone {
  switch (c.status) {
    case "COMPLETED": return c.verified ? "ok" : "warn";
    case "REJECTED": case "FAILED": return "bad";
    case "TIMED_OUT": return "warn";
    case "CANCELLED": return "neutral";
    case "PENDING_APPROVAL": return "warn";
    default: return "info";
  }
}

export function statusLabel(c: Pick<Command, "status" | "verified">): string {
  if (c.status === "COMPLETED") return c.verified ? "Completed · verified" : "Completed · not verified";
  if (c.status === "TIMED_OUT") return "Timed out · state unverified";
  if (c.status === "PENDING_APPROVAL") return "Awaiting approval";
  return titleCase(c.status.toLowerCase());
}

/** Follow one command: WebSocket updates, with a polling fallback. */
export function useCommand(id: string | null): Command | null {
  const pushed = useCommands((s) => (id ? s.byId[id] : undefined));
  const [polled, setPolled] = useState<Command | null>(null);
  useEffect(() => {
    if (!id) return;
    let stop = false;
    const tick = async () => {
      try {
        const c = await api.get<Command>(`/commands/${id}`);
        if (!stop) setPolled(c);
        if (TERMINAL.has(c.status)) return;
      } catch { /* retry */ }
      if (!stop) setTimeout(tick, 1500);
    };
    void tick();
    return () => { stop = true; };
  }, [id]);
  if (!pushed) return polled;
  if (!polled) return pushed;
  return pushed.events.length >= polled.events.length ? pushed : polled;
}

export function CommandTimeline({ cmd }: { cmd: Command }) {
  const seen = new Map(cmd.events.map((e) => [e.status, e]));
  const flow = cmd.events.some((e) => e.status === "PENDING_APPROVAL") ? [...FLOW.slice(0, 2), "PENDING_APPROVAL" as CommandStatus, ...FLOW.slice(2)] : FLOW;
  const failed = TERMINAL.has(cmd.status) && cmd.status !== "COMPLETED" ? cmd.events[cmd.events.length - 1] : null;
  return (
    <div className="timeline">
      {flow.map((s) => {
        const e = seen.get(s);
        const current = cmd.status === s && !TERMINAL.has(s);
        return (
          <div key={s} className={`tl-step${e ? " done" : ""}${current ? " current" : ""}`}>
            <span className="tl-dot" />
            <div>
              <div className="tl-name">{s === "PENDING_APPROVAL" ? "Awaiting approval" : titleCase(s.toLowerCase())}
                {e && <span className="faint small"> · {new Date(e.at).toLocaleTimeString()}</span>}</div>
              {e?.detail && <div className="faint small">{e.detail}</div>}
            </div>
          </div>
        );
      })}
      {failed && (
        <div className="tl-step done failed">
          <span className="tl-dot" />
          <div>
            <div className="tl-name">{statusLabel(cmd)} <span className="faint small">· {new Date(failed.at).toLocaleTimeString()}</span></div>
            <div className="small">{failed.detail}</div>
          </div>
        </div>
      )}
    </div>
  );
}

export function Checklist({ checks }: { checks: { name: string; ok: boolean; detail: string }[] }) {
  return (
    <ul className="checklist">
      {checks.map((c, i) => (
        <li key={i} className={c.ok ? "ok" : "bad"}>
          <span className="ck">{c.ok ? "✓" : "✕"}</span>
          <div><strong>{c.name}</strong><div className="small muted">{c.detail}</div></div>
        </li>
      ))}
    </ul>
  );
}

function CommandDialog({ asset, control, onClose }: { asset: Asset; control: ControlDef; onClose: () => void }) {
  const toast = useToast();
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [check, setCheck] = useState<ValidationResult | null>(null);
  const [sentId, setSentId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const cmd = useCommand(sentId);
  const seq = useRef(0);

  // Live dry-run: interlocks and device state can change while the dialog is open.
  useEffect(() => {
    if (sentId) return;
    let stop = false;
    const run = async () => {
      const id = ++seq.current;
      try {
        const r = await api.post<ValidationResult>(`/assets/${asset.id}/commands/validate`, { control: control.key, params, confirm: true });
        if (!stop && id === seq.current) setCheck(r);
      } catch { /* shown on send */ }
    };
    void run();
    const t = setInterval(run, 2000);
    return () => { stop = true; clearInterval(t); };
  }, [asset.id, control.key, params, sentId]);

  const send = async () => {
    setBusy(true);
    try {
      const c = await api.post<Command>(`/assets/${asset.id}/commands`, { control: control.key, params, confirm: confirmed || !control.requires_confirmation, reason });
      useCommands.getState().upsert(c);
      setSentId(c.id);
      if (c.status === "REJECTED") toast("bad", `${control.label} rejected`);
    } catch (e) { toast("bad", (e as Error).message); } finally { setBusy(false); }
  };

  const checks = (check?.checks ?? []).filter((c) => c.name !== "Confirmation");
  const blocking = checks.filter((c) => !c.ok);
  const canSend = !!check && blocking.length === 0 && (!control.requires_confirmation || confirmed) && !busy;

  return (
    <Modal wide title={<span className="row">{control.label} · <span className="code-chip">{asset.code}</span> {asset.name}{check?.simulated && <Pill tone="sim">Simulated device</Pill>}</span>}
      onClose={onClose}
      footer={sentId ? <button className="btn primary" onClick={onClose}>Close</button> : <>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className={`btn ${control.key === "stop" ? "danger solid" : "primary"}`} disabled={!canSend} onClick={send}>
          {check?.requires_approval ? "Request approval" : `Send ${control.label}`}
        </button>
      </>}>
      {!sentId ? (
        <div className="stack">
          {control.params.length > 0 && (
            <div className="grid-2">
              {control.params.map((p) => (
                <Field key={p.key} label={`${p.label}${p.unit ? ` (${p.unit})` : ""}`} required
                  help={p.min !== null || p.max !== null ? `Allowed ${p.min ?? "−∞"} – ${p.max ?? "∞"} ${p.unit}` : undefined}>
                  <input className="input" type="number" step="any" autoFocus min={p.min ?? undefined} max={p.max ?? undefined}
                    value={String(params[p.key] ?? "")} onChange={(e) => setParams({ ...params, [p.key]: e.target.value === "" ? undefined : Number(e.target.value) })} />
                </Field>
              ))}
            </div>
          )}
          <Field label="Reason (recorded in the audit log)">
            <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. restart after changeover" />
          </Field>
          <div>
            <div className="section-title">Pre-checks {check ? (blocking.length ? <Pill tone="bad">{blocking.length} blocking</Pill> : <Pill tone="ok">all passed</Pill>) : <span className="faint small">checking…</span>}</div>
            <Checklist checks={checks} />
          </div>
          {check?.requires_approval && <div className="notice warn"><span>This command needs a second person (engineer or admin) to approve it before anything is sent.</span></div>}
          {control.requires_confirmation && (
            <label className="check confirm-box">
              <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
              I have checked the area is clear and confirm sending <strong>{control.label}</strong> to {asset.code}.
            </label>
          )}
          <p className="faint small" style={{ margin: 0 }}>
            The platform is supervisory. PLC logic, safety relays and hardwired E-stops stay in control and may refuse this command.
            Success is reported only when the equipment's feedback confirms it.
          </p>
        </div>
      ) : cmd ? (
        <div className="stack">
          <div className="row"><Pill tone={statusTone(cmd)}>{statusLabel(cmd)}</Pill>{cmd.simulated && <Pill tone="sim">Simulated</Pill>}</div>
          <CommandTimeline cmd={cmd} />
          {cmd.status === "REJECTED" && <Checklist checks={cmd.checks.filter((c) => !c.ok)} />}
          {cmd.status === "PENDING_APPROVAL" && <p className="muted small">An engineer can approve it on the <Link to="/commands">Commands</Link> page. You can close this dialog.</p>}
        </div>
      ) : <p className="muted">Sending…</p>}
    </Modal>
  );
}

/** Controls for one asset + its recent command history. */
export function ControlPanel({ asset, type, compact }: { asset: Asset; type: AssetType; compact?: boolean }) {
  const { can } = useAuth();
  const [open, setOpen] = useState<ControlDef | null>(null);
  const [recent, setRecent] = useState<Command[]>([]);
  const pushed = useCommands((s) => s.byId);
  useEffect(() => {
    api.get<Command[]>(`/commands${qs({ asset_id: asset.id, limit: 8 })}`).then(setRecent).catch(() => {});
  }, [asset.id]);
  const merged = useMemo(() => {
    const m = new Map(recent.map((c) => [c.id, c]));
    Object.values(pushed).filter((c) => c.asset_id === asset.id).forEach((c) => m.set(c.id, c));
    return [...m.values()].sort((a, b) => b.requested_at.localeCompare(a.requested_at)).slice(0, compact ? 4 : 8);
  }, [recent, pushed, asset.id, compact]);

  if (!type.controls.length) return <p className="faint small" style={{ margin: 0 }}>This equipment type has no controls.</p>;
  const allowed = can("control.execute");
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row wrap">
        {type.controls.map((c) => (
          <button key={c.key} className={`btn ${c.key === "stop" ? "danger" : c.key === "start" ? "primary" : ""}`} disabled={!allowed}
            onClick={() => setOpen(c)} title={allowed ? undefined : "Your role can't issue commands"}>
            {c.label}{c.requires_approval && <span className="faint small"> · approval</span>}
          </button>
        ))}
      </div>
      {!allowed && <p className="faint small" style={{ margin: 0 }}>Viewing only. Your role can't issue commands.</p>}
      {merged.length > 0 && (
        <div className="cmd-list">
          {merged.map((c) => (
            <div key={c.id} className="cmd-row">
              <Pill tone={statusTone(c)}>{statusLabel(c)}</Pill>
              <span className="small">{c.control_label}{Object.keys(c.params).length ? ` (${Object.values(c.params).join(", ")})` : ""}</span>
              <span className="faint small right" title={c.result_message}>{c.requested_by.split("@")[0]} · {new Date(c.requested_at).toLocaleTimeString()}</span>
            </div>
          ))}
        </div>
      )}
      {open && <CommandDialog asset={asset} control={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
