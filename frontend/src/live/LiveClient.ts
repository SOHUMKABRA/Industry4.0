import { api } from "../api/client";
import { Alert, Command } from "../api/types";
import { emitAlert, useAlerts, useCommands, useLiveMeta } from "./liveMeta";
import { Frame, telemetry } from "./telemetryStore";

const PING_EVERY_MS = 5000;
const MAX_BACKOFF_MS = 15000;

/** WebSocket client: single-use ticket auth, factory subscription,
 *  reconnect with exponential backoff, heartbeat/latency tracking. */
export class LiveClient {
  private ws: WebSocket | null = null;
  private factoryId: string | null = null;
  private closedByUser = false;
  private backoff = 1000;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;

  connect(factoryId: string) {
    this.factoryId = factoryId;
    this.closedByUser = false;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.subscribe();
      return;
    }
    void this.open();
  }

  /** Re-request the snapshot (e.g. after leaving playback). */
  resync() {
    this.subscribe();
  }

  close() {
    this.closedByUser = true;
    this.cleanup();
    this.ws?.close();
    this.ws = null;
    useLiveMeta.getState().set({ status: "idle" });
  }

  private cleanup() {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.retryTimer = this.pingTimer = null;
  }

  private subscribe() {
    if (this.ws?.readyState === WebSocket.OPEN && this.factoryId) {
      telemetry.clear();
      this.ws.send(JSON.stringify({ type: "subscribe", factory_id: this.factoryId }));
      // Alerts raised while disconnected: resync from the server.
      const fid = this.factoryId;
      api.get<Alert[]>(`/alerts?factory_id=${fid}&state=active`).then((a) => { if (fid === this.factoryId) useAlerts.getState().seed(a); }).catch(() => {});
    }
  }

  private async open() {
    const meta = useLiveMeta.getState();
    meta.set({ status: "connecting" });
    let ticket: string;
    try {
      ticket = (await api.post<{ ticket: string }>("/live/ticket")).ticket;
    } catch {
      this.scheduleRetry();
      return;
    }
    if (this.closedByUser) return;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/api/live/ws?ticket=${encodeURIComponent(ticket)}`);
    this.ws = ws;
    ws.onopen = () => {
      this.backoff = 1000;
      meta.set({ status: "open" });
      this.subscribe();
      this.pingTimer = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ type: "ping", t: performance.now() })), PING_EVERY_MS);
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      const m = useLiveMeta.getState();
      m.set({ lastMessageAt: Date.now() });
      switch (msg.type) {
        case "snapshot":
          telemetry.clear();
          telemetry.apply(msg.points as Frame[]);
          m.set({ devices: msg.devices, running: msg.running });
          break;
        case "telemetry":
          telemetry.apply(msg.points as Frame[]);
          break;
        case "heartbeat":
          m.set({ devices: msg.devices, running: msg.running });
          break;
        case "pong":
          m.set({ latencyMs: Math.round(performance.now() - msg.t) });
          break;
        case "alert": {
          const a = msg.alert as Alert;
          const isNew = a.active && !useAlerts.getState().active[a.id];
          useAlerts.getState().upsert(a);
          emitAlert(a, isNew);
          break;
        }
        case "command":
          useCommands.getState().upsert(msg.command as Command);
          break;
      }
    };
    ws.onclose = () => {
      this.cleanup();
      if (this.ws === ws) this.ws = null;
      if (!this.closedByUser) {
        useLiveMeta.getState().set({ status: "closed" });
        this.scheduleRetry();
      }
    };
  }

  private scheduleRetry() {
    if (this.closedByUser) return;
    useLiveMeta.getState().set({ status: "closed" });
    this.retryTimer = setTimeout(() => void this.open(), this.backoff);
    this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
  }
}

export const liveClient = new LiveClient();
