import { NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { EomBrandLockup } from "./components/EomBrandLockup";
import { Toolbar } from "./components/Toolbar";
import { LandingPage } from "./pages/LandingPage";
import { MapPage } from "./pages/MapPage";
import { TablePage } from "./pages/TablePage";

function GlobalHeader() {
  return (
    <header className="landing-header">
      <EomBrandLockup />
      <nav className="landing-nav" aria-label="Primary navigation">
        <NavLink to="/app" end>
          Map
        </NavLink>
        <NavLink to="/app/table">Records</NavLink>
      </nav>
    </header>
  );
}

function PlatformLayout() {
  return (
    <div className="app platform-app">
      <Toolbar />
      <Outlet />
    </div>
  );
}

export default function App() {
  return (
    <>
      <GlobalHeader />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/app" element={<PlatformLayout />}>
          <Route index element={<MapPage />} />
          <Route path="table" element={<TablePage />} />
        </Route>
        <Route path="/table" element={<Navigate to="/app/table" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
