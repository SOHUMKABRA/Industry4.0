import { useEffect, useRef, useState } from "react";
import { api, qs } from "../api/client";
import { HistoryOut, TelemetryDef } from "../api/types";
import { formatValue } from "../lib/format";
import { useNow, useTelemetry } from "./hooks";
import { freshness, severity } from "./status";
import { telemetry, tkey } from "./telemetryStore";

const SEV_CLASS = { ok: "", warn: "sev-warn", alarm: "sev-alarm" };

/** One live value with unit, limit colouring, freshness and data-source marking. */
export function LiveValue({ assetId, def, big }: { assetId: string; def: TelemetryDef; big?: boolean }) {
  const tv = useTelemetry(assetId, def.key);
  const now = useNow(1000);
  const f = freshness(tv, def, now);
  if (!tv) return <span className="faint">no data</span>;
  const sev = f === "fresh" ? severity(def, tv.v) : "ok";
  const age = Math.max(0, Math.round((now - tv.ts) / 1000));
  return (
    <span className={`live-val ${SEV_CLASS[sev]}${f === "stale" ? " stale" : ""}${big ? " big" : ""}`}
      title={`${tv.src === "simulated" ? "Simulated" : tv.src === "playback" ? "Replayed history" : "Live"} · quality ${tv.q} · ${new Date(tv.ts).toLocaleTimeString()}`}>
      {formatValue(tv.v, def.unit)}
      {f === "stale" && <span className="stale-tag">stale {age}s</span>}
      {tv.src === "simulated" && <span className="sim-tag" aria-label="simulated">SIM</span>}
      {tv.src === "playback" && <span className="replay-tag" aria-label="replayed history">REPLAY</span>}
    </span>
  );
}

/** History for a measurement plus the live tail since the last fetch. */
export function useTrend(assetId: string | null | undefined, measurement: string | null | undefined, minutes: number, buckets = 120) {
  const [hist, setHist] = useState<HistoryOut | null>(null);
  const [live, setLive] = useState<[number, number][]>([]);
  const [error, setError] = useState<Error | null>(null);
  const liveRef = useRef<[number, number][]>([]);

  useEffect(() => {
    if (!assetId || !measurement) return;
    let cancelled = false;
    const load = () =>
      api.get<HistoryOut>(`/assets/${assetId}/history${qs({ measurement, minutes, buckets })}`)
        .then((h) => { if (!cancelled) { setHist(h); setError(null); liveRef.current = []; setLive([]); } })
        .catch((e) => !cancelled && setError(e));
    void load();
    const refresh = setInterval(load, 30_000);
    const k = tkey(assetId, measurement);
    let pending = false;
    const off = telemetry.subscribe(k, () => {
      const tv = telemetry.getKey(k);
      if (!tv || typeof tv.v !== "number") return;
      const arr = liveRef.current;
      if (!arr.length || arr[arr.length - 1][0] < tv.ts) arr.push([tv.ts, tv.v]);
      if (arr.length > 2000) arr.splice(0, arr.length - 2000);
      if (!pending) { pending = true; setTimeout(() => { pending = false; setLive([...liveRef.current]); }, 1000); }
    });
    return () => { cancelled = true; clearInterval(refresh); off(); };
  }, [assetId, measurement, minutes, buckets]);

  const to = Date.now();
  return { hist, live, error, from: to - minutes * 60_000, to };
}
