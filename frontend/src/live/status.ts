import { Asset, AssetType, TelemetryDef } from "../api/types";
import { telemetry, TV } from "./telemetryStore";

export type Severity = "ok" | "warn" | "alarm";
export type Freshness = "fresh" | "stale" | "none";
export type AssetCondition = "running" | "stopped" | "fault" | "maintenance" | "estop" | "idle" | "alarm" | "warn" | "ok" | "stale" | "nodata";

/** A value is stale when older than 3× the measurement's expected interval. */
export function freshness(tv: TV | undefined, def: TelemetryDef | undefined, now: number): Freshness {
  if (!tv) return "none";
  const limit = Math.max(3 * (def?.expected_interval_s ?? 5), 6) * 1000;
  return now - tv.ts > limit ? "stale" : "fresh";
}

export function severity(def: TelemetryDef | undefined, v: unknown): Severity {
  if (!def || typeof v !== "number") return "ok";
  if ((def.alarm_high != null && v >= def.alarm_high) || (def.alarm_low != null && v <= def.alarm_low)) return "alarm";
  if ((def.warn_high != null && v >= def.warn_high) || (def.warn_low != null && v <= def.warn_low)) return "warn";
  return "ok";
}

const STATE_MAP: Record<string, AssetCondition> = {
  running: "running", run: "running", loaded: "running", stopped: "stopped", stop: "stopped", unloaded: "idle",
  idle: "idle", fault: "fault", maintenance: "maintenance", emergency_stop: "estop", tripped: "estop",
};

export interface AssetLive {
  condition: AssetCondition;
  state: string | null;
  worst: Severity;
  violations: { def: TelemetryDef; value: number; sev: Severity }[];
  fresh: number;
  stale: number;
  lastTs: number | null;
}

/** Derive an asset's displayed condition. Never infers "running" from stale data. */
export function assetLive(asset: Pick<Asset, "id">, type: AssetType | undefined, now: number): AssetLive {
  const defs = type?.telemetry ?? [];
  let worst: Severity = "ok";
  let fresh = 0, stale = 0, lastTs: number | null = null;
  let state: string | null = null;
  let stateFresh = false;
  const violations: AssetLive["violations"] = [];
  for (const d of defs) {
    const tv = telemetry.get(asset.id, d.key);
    const f = freshness(tv, d, now);
    if (f === "none") continue;
    lastTs = Math.max(lastTs ?? 0, tv!.ts);
    if (f === "stale") { stale++; continue; }
    fresh++;
    if (d.key === "state" || d.key === "estop_status" || d.key === "run_mode") {
      if (d.key === "state" || state === null) { state = String(tv!.v); stateFresh = true; }
      if (d.key === "estop_status" && tv!.v === "tripped") state = "tripped";
    }
    const sev = severity(d, tv!.v);
    if (sev !== "ok") {
      violations.push({ def: d, value: tv!.v as number, sev });
      if (sev === "alarm" || worst === "ok") worst = sev;
    }
  }
  let condition: AssetCondition;
  if (fresh === 0) condition = stale > 0 ? "stale" : "nodata";
  else if (stateFresh && state && STATE_MAP[state] && STATE_MAP[state] !== "running") condition = STATE_MAP[state];
  else if (worst === "alarm") condition = "alarm";
  else if (worst === "warn") condition = "warn";
  else if (stateFresh && state && STATE_MAP[state] === "running") condition = "running";
  else condition = "ok";
  return { condition, state, worst, violations, fresh, stale, lastTs };
}

export const CONDITION_STYLE: Record<AssetCondition, { label: string; tone: "ok" | "warn" | "bad" | "neutral" | "info" | "sim"; color: string }> = {
  running: { label: "Running", tone: "ok", color: "#22c55e" },
  ok: { label: "Normal", tone: "ok", color: "#22c55e" },
  idle: { label: "Idle", tone: "neutral", color: "#94a3b8" },
  stopped: { label: "Stopped", tone: "neutral", color: "#94a3b8" },
  maintenance: { label: "Maintenance", tone: "info", color: "#38bdf8" },
  warn: { label: "Warning", tone: "warn", color: "#f59e0b" },
  alarm: { label: "Alarm", tone: "bad", color: "#ef4444" },
  fault: { label: "Fault", tone: "bad", color: "#ef4444" },
  estop: { label: "E-stop", tone: "bad", color: "#dc2626" },
  stale: { label: "Stale data", tone: "neutral", color: "#64748b" },
  nodata: { label: "No data", tone: "neutral", color: "#475569" },
};
