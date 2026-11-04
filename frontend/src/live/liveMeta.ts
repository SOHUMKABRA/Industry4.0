import { create } from "zustand";
import { Alert, Command } from "../api/types";

export interface DeviceState {
  device_id: string; asset_id: string; online: boolean; source: string; protocol?: string;
  last_seen: number | null; error: string; samples?: number; errors?: number; poll_ms?: number | null;
}
export type ConnStatus = "idle" | "connecting" | "open" | "closed";

interface LiveMeta {
  status: ConnStatus;
  running: boolean;          // backend telemetry runtime is active
  latencyMs: number | null;
  devices: DeviceState[];
  lastMessageAt: number | null;
  set: (p: Partial<LiveMeta>) => void;
}

export const useLiveMeta = create<LiveMeta>((set) => ({
  status: "idle", running: false, latencyMs: null, devices: [], lastMessageAt: null,
  set: (p) => set(p),
}));

/** Active alerts, kept current by WebSocket events (seeded from REST on connect). */
interface AlertState {
  active: Record<string, Alert>;
  seed: (alerts: Alert[]) => void;
  upsert: (a: Alert) => void;
}
export const useAlerts = create<AlertState>((set) => ({
  active: {},
  seed: (alerts) => set({ active: Object.fromEntries(alerts.filter((a) => a.active).map((a) => [a.id, a])) }),
  upsert: (a) => set((s) => {
    const next = { ...s.active };
    if (a.active) next[a.id] = a;
    else delete next[a.id];
    return { active: next };
  }),
}));

/** Latest state of commands seen in this session (pushed over WebSocket). */
interface CommandState {
  byId: Record<string, Command>;
  upsert: (c: Command) => void;
}
export const useCommands = create<CommandState>((set) => ({
  byId: {},
  upsert: (c) => set((s) => ({ byId: { ...s.byId, [c.id]: c } })),
}));

type AlertListener = (a: Alert, isNew: boolean) => void;
const alertListeners = new Set<AlertListener>();
export const onAlert = (fn: AlertListener) => { alertListeners.add(fn); return () => { alertListeners.delete(fn); }; };
export const emitAlert = (a: Alert, isNew: boolean) => alertListeners.forEach((fn) => fn(a, isNew));
