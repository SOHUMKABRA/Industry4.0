import { useCallback, useEffect, useRef, useState } from "react";
import { api, qs } from "../api/client";
import { useToast } from "../components/Toast";
import { clock, usePlayback } from "./clock";
import { liveClient } from "./LiveClient";
import { Frame, telemetry } from "./telemetryStore";

interface Series { a: string; m: string; t: number[]; v: unknown[] }
interface PlaybackData { from: number; to: number; step_s: number; series: Series[]; samples: number }

const WINDOWS = [{ m: 15, l: "15 min" }, { m: 60, l: "1 h" }, { m: 360, l: "6 h" }, { m: 1440, l: "24 h" }];
const SPEEDS = [1, 10, 60, 300];

/** Index of the last sample at or before t (binary search), or -1. */
export function lastAtOrBefore(ts: number[], t: number): number {
  let lo = 0, hi = ts.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (ts[mid] <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

export function framesAt(series: Series[], t: number, maxAgeMs: number): Frame[] {
  const out: Frame[] = [];
  for (const s of series) {
    const i = lastAtOrBefore(s.t, t);
    if (i >= 0 && t - s.t[i] <= maxAgeMs) out.push([s.a, s.m, s.v[i], s.t[i], "good", "playback"]);
  }
  return out;
}

const fmt = (t: number) => new Date(t).toLocaleTimeString();

/** Replay recorded telemetry into the twin. Live data is paused while active. */
export function PlaybackBar({ factoryId }: { factoryId: string }) {
  const pb = usePlayback();
  const toast = useToast();
  const [data, setData] = useState<PlaybackData | null>(null);
  const [loading, setLoading] = useState(false);
  const raf = useRef<number>(0);
  const lastApply = useRef(0);

  const apply = useCallback((t: number, d: PlaybackData) => {
    clock.setVirtual(t);
    telemetry.clear();
    telemetry.applyPlayback(framesAt(d.series, t, Math.max(d.step_s * 3000, 30_000)));
  }, []);

  const exit = useCallback(() => {
    cancelAnimationFrame(raf.current);
    clock.setVirtual(null);
    telemetry.setLivePaused(false);
    liveClient.resync();
    usePlayback.getState().set({ active: false, playing: false });
    setData(null);
  }, []);

  useEffect(() => () => { if (usePlayback.getState().active) exit(); }, [exit]);

  const start = async (minutes: number) => {
    setLoading(true);
    try {
      const to = Date.now(), from = to - minutes * 60_000;
      const step = Math.max(1, Math.round((minutes * 60) / 1800));
      const d = await api.get<PlaybackData>(`/factories/${factoryId}/playback${qs({ from_ms: from, to_ms: to, step_s: step })}`);
      if (!d.samples) { toast("info", "No recorded data in that period"); return; }
      telemetry.setLivePaused(true);
      setData(d);
      // Start at the first recorded moment, not in an empty gap before it.
      const first = Math.min(...d.series.map((s) => s.t[0] ?? Infinity));
      const t0 = Math.max(from, Number.isFinite(first) ? first + 1000 : from);
      usePlayback.getState().set({ active: true, from, to, t: t0, playing: true });
      apply(t0, d);
      if (t0 > from + 60_000) toast("info", `No recordings before ${new Date(t0).toLocaleTimeString()}; starting there`);
    } catch (e) { toast("bad", (e as Error).message); } finally { setLoading(false); }
  };

  // Animation loop: advance replay time; push values to the store at most 5×/s.
  useEffect(() => {
    if (!data) return;
    let prev = performance.now();
    const loop = (now: number) => {
      const st = usePlayback.getState();
      const dt = now - prev;
      prev = now;
      if (st.active && st.playing) {
        let t = st.t + dt * st.speed;
        if (t >= st.to) { t = st.to; st.set({ playing: false }); }
        st.set({ t });
        clock.setVirtual(t);
        if (now - lastApply.current > 200) { lastApply.current = now; apply(t, data); }
      }
      raf.current = requestAnimationFrame(loop);
    };
    raf.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf.current);
  }, [data, apply]);

  if (!pb.active) {
    return (
      <div className="pb-bar idle">
        <span className="faint small">Replay history:</span>
        {WINDOWS.map((w) => <button key={w.m} className="btn sm" disabled={loading} onClick={() => start(w.m)}>Last {w.l}</button>)}
      </div>
    );
  }
  return (
    <div className="pb-bar active">
      <span className="pb-badge">PLAYBACK</span>
      <button className="btn sm" onClick={() => pb.set({ playing: !pb.playing, ...(pb.t >= pb.to ? { t: pb.from } : {}) })}>{pb.playing ? "❚❚ Pause" : "▶ Play"}</button>
      <input type="range" className="pb-slider" min={pb.from} max={pb.to} step={1000} value={pb.t} aria-label="Replay position"
        onChange={(e) => { const t = Number(e.target.value); pb.set({ t }); if (data) apply(t, data); }} />
      <span className="pb-time mono">{fmt(pb.t)}</span>
      <select className="select sm-select" value={pb.speed} onChange={(e) => pb.set({ speed: Number(e.target.value) })} aria-label="Speed">
        {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
      </select>
      <button className="btn sm primary" onClick={exit}>Back to live</button>
    </div>
  );
}
