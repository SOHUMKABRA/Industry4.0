import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { LoginPage } from "./auth/LoginPage";
import { ToastProvider } from "./components/Toast";
import { Loading } from "./components/ui";
import { AppShell } from "./layout/AppShell";
import { FactoryProvider } from "./layout/FactoryContext";
import { AssetsPage } from "./pages/AssetsPage";
import { AssetTypesPage } from "./pages/AssetTypesPage";
import { AuditPage } from "./pages/AuditPage";
import { DevicesPage } from "./pages/DevicesPage";
import { FactoryPage } from "./pages/FactoryPage";
import { OverviewPage } from "./pages/OverviewPage";

function Gate() {
  const { me, ready } = useAuth();
  if (!ready) return <Loading />;
  if (!me) return <LoginPage />;
  return (
    <FactoryProvider key={me.organization.id}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<OverviewPage />} />
          <Route path="factory" element={<FactoryPage />} />
          <Route path="assets" element={<AssetsPage />} />
          <Route path="assets/:assetId" element={<AssetsPage />} />
          <Route path="devices" element={<DevicesPage />} />
          <Route path="asset-types" element={<AssetTypesPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
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
