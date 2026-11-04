import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { Icon } from "../components/Icon";
import { Pill } from "../components/ui";
import { usePlayback } from "../live/clock";
import { useLiveMeta } from "../live/liveMeta";
import { AlertBell } from "./AlertBell";
import { useFactory } from "./FactoryContext";

const NAV = [
  { to: "/", label: "Overview", icon: "overview", end: true },
  { to: "/dashboards", label: "Dashboards", icon: "analytics" },
  { to: "/monitor", label: "Live monitoring", icon: "live" },
  { to: "/alerts", label: "Alerts", icon: "alert" },
  { to: "/commands", label: "Commands", icon: "control" },
  { to: "/analytics", label: "Analytics", icon: "analytics" },
  { to: "/automations", label: "Automations", icon: "automation" },
  { to: "/simulation", label: "Simulation", icon: "sim" },
  { to: "/editor", label: "Twin editor", icon: "editor" },
  { to: "/factory", label: "Factory structure", icon: "factory" },
  { to: "/assets", label: "Assets", icon: "assets" },
  { to: "/devices", label: "Devices", icon: "devices" },
  { to: "/asset-types", label: "Asset types", icon: "types" },
];
const ADMIN_NAV = [
  { to: "/audit", label: "Audit log", icon: "audit", perm: "audit.read" },
  { to: "/settings", label: "Settings", icon: "types", perm: "read" },
];
// Shown so the roadmap is visible, but not navigable until built.
const ROADMAP: { label: string; icon: string; phase: string }[] = [];

// Pages that manage their own full-height layout (canvas views).
const FULL_BLEED = ["/editor", "/monitor"];

function useTheme() {
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    try { return (localStorage.getItem("twin.theme") as "dark" | "light") || "dark"; } catch { return "dark"; }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("twin.theme", theme); } catch { /* ignore */ }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))] as const;
}

function LiveIndicator() {
  const pb = usePlayback();
  if (pb.active) return <span title="Replaying recorded history; live data is paused"><Pill tone="warn">Playback · {new Date(pb.t).toLocaleTimeString()}</Pill></span>;
  return <LiveStatus />;
}

function LiveStatus() {
  const status = useLiveMeta((s) => s.status);
  const running = useLiveMeta((s) => s.running);
  const devices = useLiveMeta((s) => s.devices);
  const latency = useLiveMeta((s) => s.latencyMs);
  const online = devices.filter((d) => d.online).length;
  const sim = devices.length > 0 && devices.every((d) => d.source === "simulated");
  const mixed = devices.some((d) => d.source === "simulated") && devices.some((d) => d.source !== "simulated");
  const tip = `${online}/${devices.length} data sources online${latency !== null ? ` · ${latency} ms` : ""}`;
  if (status === "connecting" || status === "idle") return <Pill tone="neutral">Connecting…</Pill>;
  if (status === "closed") return <span title="Live feed lost; values will turn stale. Reconnecting automatically."><Pill tone="bad">Disconnected · reconnecting</Pill></span>;
  if (!running) return <span title="TELEMETRY_ENABLED=false on the server"><Pill tone="warn">Telemetry off</Pill></span>;
  if (!devices.length) return <span title="No active devices are bound to assets"><Pill tone="neutral">Live · no active devices</Pill></span>;
  return <span title={tip}><Pill tone={sim ? "sim" : "ok"}>{sim ? "Simulated data" : mixed ? "Live + simulated" : "Live"} · {online}/{devices.length}</Pill></span>;
}

export function AppShell() {
  const { me, logout, can } = useAuth();
  const { factories, factory, select } = useFactory();
  const [theme, toggleTheme] = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  return (
    <div className={`shell${collapsed ? " collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <img className="brand-mark" src="/favicon.svg" alt="" />
          <span className="brand-name">Twin Platform</span>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} title={n.label}>
              <Icon name={n.icon} /><span className="nav-label">{n.label}</span>
            </NavLink>
          ))}
          {ADMIN_NAV.filter((n) => can(n.perm)).map((n) => (
            <NavLink key={n.to} to={n.to} title={n.label}>
              <Icon name={n.icon} /><span className="nav-label">{n.label}</span>
            </NavLink>
          ))}
          {ROADMAP.length > 0 && <div className="nav-group">Coming next</div>}
          {ROADMAP.map((n) => (
            <div key={n.label} className="nav-disabled" title={`${n.label} — planned for phase ${n.phase.slice(1)}`} aria-disabled="true">
              <Icon name={n.icon} /><span className="nav-label">{n.label}</span><span className="phase">{n.phase}</span>
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <button className="btn ghost icon" onClick={() => setCollapsed((c) => !c)} title="Collapse sidebar" aria-label="Collapse sidebar">
            <Icon name="menu" />
          </button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          {factories.length > 0 && (
            <select className="select" style={{ width: 220 }} value={factory?.id ?? ""} onChange={(e) => select(e.target.value)}
              aria-label="Factory">
              {factories.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          )}
          <LiveIndicator />
          <div className="spacer" />
          <AlertBell />
          <button className="btn ghost icon" onClick={toggleTheme} title="Toggle theme" aria-label="Toggle theme">
            <Icon name={theme === "dark" ? "sun" : "moon"} />
          </button>
          <div style={{ textAlign: "right", lineHeight: 1.2 }}>
            <div style={{ fontWeight: 550 }}>{me?.user.name}</div>
            <div className="faint small">{me?.organization.name} · {me?.user.role}</div>
          </div>
          <button className="btn ghost icon" onClick={logout} title="Sign out" aria-label="Sign out"><Icon name="logout" /></button>
        </header>
        <main className={`content${FULL_BLEED.some((p) => location.pathname.startsWith(p)) ? " full" : ""}`}>
          <ErrorBoundary resetKey={location.pathname}><Outlet /></ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
