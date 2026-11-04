/**
 * Live telemetry store, deliberately outside React.
 *
 * Messages may arrive many times per second; values are written here
 * immediately and listeners are notified at most once per animation frame,
 * only for the keys that changed. The 3D view reads values directly every
 * frame (no React render at all).
 */

export type Quality = "good" | "uncertain" | "bad";
export type Source = "live" | "simulated" | "playback";
export interface TV { v: unknown; ts: number; q: Quality; src: Source }
/** [asset_id, measurement, value, ts_ms, quality, source] as sent by the server */
export type Frame = [string, string, unknown, number, Quality, Source];

const values = new Map<string, TV>();
const keyListeners = new Map<string, Set<() => void>>();
const allListeners = new Set<() => void>();
const dirty = new Set<string>();
let scheduled = false;
let version = 0;

export const tkey = (assetId: string, measurement: string) => `${assetId}:${measurement}`;

const schedule = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (fn: () => void) => setTimeout(fn, 16);

function flush() {
  scheduled = false;
  version++;
  const keys = [...dirty];
  dirty.clear();
  for (const k of keys) keyListeners.get(k)?.forEach((fn) => fn());
  allListeners.forEach((fn) => fn());
}

function markDirty(k: string) {
  dirty.add(k);
  if (!scheduled) { scheduled = true; schedule(flush); }
}

let paused = false; // playback: live frames are ignored so live and historical data never mix

export const telemetry = {
  /** Pause/resume live updates (playback). Resuming clears the store; the live client resyncs. */
  setLivePaused(p: boolean) {
    paused = p;
    this.clear();
  },
  livePaused: () => paused,
  /** Playback: set values at the replay instant (may move backwards in time). */
  applyPlayback(frames: Frame[]) {
    for (const [a, m, v, ts, q, src] of frames) {
      const k = tkey(a, m);
      const cur = values.get(k);
      if (cur && cur.ts === ts && cur.v === v) continue;
      values.set(k, { v, ts, q, src });
      markDirty(k);
    }
  },
  get: (assetId: string, measurement: string): TV | undefined => values.get(tkey(assetId, measurement)),
  getKey: (k: string) => values.get(k),
  apply(frames: Frame[]) {
    if (paused) return;
    for (const [a, m, v, ts, q, src] of frames) {
      const k = tkey(a, m);
      const cur = values.get(k);
      if (cur && cur.ts > ts) continue; // never let an older sample overwrite a newer one
      values.set(k, { v, ts, q, src });
      markDirty(k);
    }
  },
  clear() {
    const keys = [...values.keys()];
    values.clear();
    keys.forEach(markDirty);
  },
  forAsset(assetId: string): [string, TV][] {
    const prefix = `${assetId}:`;
    const out: [string, TV][] = [];
    for (const [k, v] of values) if (k.startsWith(prefix)) out.push([k.slice(prefix.length), v]);
    return out;
  },
  size: () => values.size,
  version: () => version,
  subscribe(k: string, fn: () => void) {
    let set = keyListeners.get(k);
    if (!set) keyListeners.set(k, (set = new Set()));
    set.add(fn);
    return () => { set!.delete(fn); if (!set!.size) keyListeners.delete(k); };
  },
  subscribeAll(fn: () => void) {
    allListeners.add(fn);
    return () => { allListeners.delete(fn); };
  },
};
