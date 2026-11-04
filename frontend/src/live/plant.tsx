import { useMemo } from "react";
import { Asset, AssetType } from "../api/types";
import { Pill } from "../components/ui";
import { useNow, useTelemetryVersion } from "./hooks";
import { useLiveMeta } from "./liveMeta";
import { AssetCondition, assetLive } from "./status";

export function usePlantStatus(assets: Asset[] | undefined, typeById: Record<string, AssetType>) {
  useTelemetryVersion();
  const now = useNow(1000);
  return useMemo(() => {
    const rows = (assets ?? [])
      .map((a) => ({ asset: a, type: typeById[a.asset_type_id], live: assetLive(a, typeById[a.asset_type_id], now) }))
      .filter((r) => (r.type?.telemetry.length ?? 0) > 0);
    const count = (f: (c: AssetCondition) => boolean) => rows.filter((r) => f(r.live.condition)).length;
    return {
      rows,
      running: count((c) => c === "running"),
      stopped: count((c) => c === "stopped" || c === "idle"),
      fault: count((c) => c === "fault" || c === "estop"),
      alarm: rows.reduce((n, r) => n + r.live.violations.filter((v) => v.sev === "alarm").length, 0),
      warn: rows.reduce((n, r) => n + r.live.violations.filter((v) => v.sev === "warn").length, 0),
      noData: count((c) => c === "stale" || c === "nodata"),
    };
  }, [assets, typeById, now]); // eslint-disable-line react-hooks/exhaustive-deps
}

export function SourceBanner() {
  const devices = useLiveMeta((s) => s.devices);
  const status = useLiveMeta((s) => s.status);
  const running = useLiveMeta((s) => s.running);
  const online = devices.filter((d) => d.online).length;
  const sim = devices.length > 0 && devices.every((d) => d.source === "simulated");
  if (status !== "open") return <div className="notice bad"><span><strong>Not connected to the live feed.</strong> Values shown are the last received and will turn stale. Reconnecting automatically…</span></div>;
  if (!running) return <div className="notice warn"><span>The telemetry runtime is switched off on the server (<code>TELEMETRY_ENABLED=false</code>). No live values will arrive.</span></div>;
  return (
    <div className={`notice ${sim ? "" : "info"}`}>
      {sim && <Pill tone="sim">Simulated data</Pill>}
      <span>{online}/{devices.length} data sources online.{sim && " All values come from software simulators, not physical equipment."}</span>
    </div>
  );
}

