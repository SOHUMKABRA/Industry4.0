import { useEffect, useState, useSyncExternalStore } from "react";
import { clock } from "./clock";
import { telemetry, tkey, TV } from "./telemetryStore";

/** Subscribe to one telemetry value; re-renders only when that key changes. */
export function useTelemetry(assetId: string | null | undefined, measurement: string | null | undefined): TV | undefined {
  const k = assetId && measurement ? tkey(assetId, measurement) : "";
  return useSyncExternalStore(
    (fn) => (k ? telemetry.subscribe(k, fn) : () => {}),
    () => (k ? telemetry.getKey(k) : undefined),
  );
}

/** Re-render when any telemetry changes (throttled to animation frames by the store). */
export function useTelemetryVersion(): number {
  return useSyncExternalStore(telemetry.subscribeAll, telemetry.version);
}

/** Ticking clock for freshness checks. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => clock.now());
  useEffect(() => {
    const t = setInterval(() => setNow(clock.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}
