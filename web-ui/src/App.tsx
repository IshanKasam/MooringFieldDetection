import { NavLink, Route, Routes } from "react-router-dom";
import { Toolbar } from "./components/Toolbar";
import { MapPage } from "./pages/MapPage";
import { TablePage } from "./pages/TablePage";

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">MF</span>
          <div>
            <h1>Mooring Fields</h1>
            <p className="tagline">Detection · enrichment · sales contacts</p>
          </div>
        </div>
        <nav>
          <NavLink to="/" end>
            Map
          </NavLink>
          <NavLink to="/table">Spreadsheet</NavLink>
        </nav>
      </header>
      <Toolbar />
      <Routes>
        <Route path="/" element={<MapPage />} />
        <Route path="/table" element={<TablePage />} />
      </Routes>
    </div>
  );
}
