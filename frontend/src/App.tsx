import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { LoginPage } from "./auth/LoginPage";
import { ToastProvider } from "./components/Toast";
import { Loading } from "./components/ui";
import { AppShell } from "./layout/AppShell";
import { FactoryProvider } from "./layout/FactoryContext";
import { LiveProvider } from "./live/LiveProvider";
import { AssetsPage } from "./pages/AssetsPage";
import { AssetTypesPage } from "./pages/AssetTypesPage";
import { AuditPage } from "./pages/AuditPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DevicesPage } from "./pages/DevicesPage";
import { FactoryPage } from "./pages/FactoryPage";
import { AlertsPage } from "./pages/AlertsPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { AutomationsPage } from "./pages/AutomationsPage";
import { ReportPrintPage } from "./pages/ReportPrintPage";
import { SimulationPage } from "./pages/SimulationPage";
import { CommandsPage } from "./pages/CommandsPage";
import { ChangePassword, SettingsPage } from "./pages/SettingsPage";
import { OverviewPage } from "./pages/OverviewPage";

// 3D views pull in three.js; load them only when opened.
const EditorPage = lazy(() => import("./editor/EditorPage").then((m) => ({ default: m.EditorPage })));
const MonitorPage = lazy(() => import("./pages/MonitorPage").then((m) => ({ default: m.MonitorPage })));
const lazyPage = (el: JSX.Element) => <Suspense fallback={<Loading label="Loading 3D engine…" />}>{el}</Suspense>;

function FirstLogin() {
  const { me, refresh, logout } = useAuth();
  return (
    <div className="login-wrap">
      <div className="panel login-card stack">
        <h1>Set your password</h1>
        <p className="muted" style={{ margin: 0 }}>Welcome, {me?.user.name}. Your account has a temporary password. Choose your own to continue.</p>
        <ChangePassword onDone={refresh} />
        <button className="btn ghost" onClick={logout}>Sign out</button>
      </div>
    </div>
  );
}

function Gate() {
  const { me, ready } = useAuth();
  if (!ready) return <Loading />;
  if (!me) return <LoginPage />;
  if (me.user.must_change_password) return <FirstLogin />;
  return (
    <FactoryProvider key={me.organization.id}>
      <LiveProvider>
      <Routes>
        <Route path="reports/print" element={<ReportPrintPage />} />
        <Route element={<AppShell />}>
          <Route index element={<OverviewPage />} />
          <Route path="dashboards" element={<DashboardPage />} />
          <Route path="monitor" element={lazyPage(<MonitorPage />)} />
          <Route path="editor" element={lazyPage(<EditorPage />)} />
          <Route path="factory" element={<FactoryPage />} />
          <Route path="assets" element={<AssetsPage />} />
          <Route path="assets/:assetId" element={<AssetsPage />} />
          <Route path="devices" element={<DevicesPage />} />
          <Route path="asset-types" element={<AssetTypesPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="commands" element={<CommandsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="automations" element={<AutomationsPage />} />
          <Route path="simulation" element={<SimulationPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      </LiveProvider>
    </FactoryProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ToastProvider>
        <AuthProvider>
          <Gate />
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  );
}
