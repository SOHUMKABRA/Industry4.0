import { create } from "zustand";

/**
 * Display clock. Live mode: wall time. Playback mode: the historical instant being
 * replayed, so freshness/staleness and animations behave as they did at that time.
 */
let virtual: number | null = null;

export const clock = {
  now: () => virtual ?? Date.now(),
  setVirtual: (t: number | null) => { virtual = t; },
  isVirtual: () => virtual !== null,
};

interface PlaybackState {
  active: boolean;
  from: number;
  to: number;
  t: number;
  playing: boolean;
  speed: number;
  set: (p: Partial<PlaybackState>) => void;
}

export const usePlayback = create<PlaybackState>((set) => ({
  active: false, from: 0, to: 0, t: 0, playing: false, speed: 10,
  set: (p) => set(p),
}));
