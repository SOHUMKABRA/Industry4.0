import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/Icon";
import { Pill } from "../components/ui";
import { useFactory } from "./FactoryContext";

const NAV = [
  { to: "/", label: "Overview", icon: "overview", end: true },
  { to: "/factory", label: "Factory layout", icon: "factory" },
  { to: "/assets", label: "Assets", icon: "assets" },
  { to: "/devices", label: "Devices", icon: "devices" },
  { to: "/asset-types", label: "Asset types", icon: "types" },
];
const ADMIN_NAV = [{ to: "/audit", label: "Audit log", icon: "audit", perm: "audit.read" }];
// Shown so the roadmap is visible, but not navigable until built.
const ROADMAP = [
  { label: "Twin editor (2D/3D)", icon: "editor", phase: "P2" },
  { label: "Live monitoring", icon: "live", phase: "P4" },
  { label: "Control", icon: "control", phase: "P5" },
  { label: "Alerts", icon: "alert", phase: "P6" },
  { label: "Automations", icon: "automation", phase: "P6" },
  { label: "Simulation", icon: "sim", phase: "P6" },
  { label: "Analytics", icon: "analytics", phase: "P6" },
];

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

export function AppShell() {
  const { me, logout, can } = useAuth();
  const { factories, factory, select } = useFactory();
  const [theme, toggleTheme] = useTheme();
  const [collapsed, setCollapsed] = useState(false);

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
          <div className="nav-group">Coming next</div>
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
          <span title="Live telemetry arrives in Phase 4. No values shown in this build are live.">
            <Pill tone="neutral">Configuration mode · no live data</Pill>
          </span>
          <div className="spacer" />
          <button className="btn ghost icon" onClick={toggleTheme} title="Toggle theme" aria-label="Toggle theme">
            <Icon name={theme === "dark" ? "sun" : "moon"} />
          </button>
          <div style={{ textAlign: "right", lineHeight: 1.2 }}>
            <div style={{ fontWeight: 550 }}>{me?.user.name}</div>
            <div className="faint small">{me?.organization.name} · {me?.user.role}</div>
          </div>
          <button className="btn ghost icon" onClick={logout} title="Sign out" aria-label="Sign out"><Icon name="logout" /></button>
        </header>
        <main className="content"><Outlet /></main>
      </div>
    </div>
  );
}
