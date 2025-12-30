import React from "react";
import { Routes, Route, Navigate, Link } from "react-router-dom";
import PolicyCompare from "./pages/PolicyCompare";
import History from "./pages/History";
import HistoryDetail from "./pages/HistoryDetail";
import "./App.css";

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-topbar">
        <div className="app-brand">
          <div className="app-title">Consent Companion</div>
          <div className="app-subtitle">Policy change analysis</div>
        </div>

        <nav className="app-nav">
          <Link to="/compare" className="app-link">Compare</Link>
          <Link to="/history" className="app-link">History</Link>
        </nav>
      </header>

      <main className="app-main">
        <Routes>
          <Route path="/" element={<Navigate to="/compare" replace />} />
          <Route path="/compare" element={<PolicyCompare />} />
          <Route path="/history" element={<History />} />
          <Route path="/history/:id" element={<HistoryDetail />} />
          <Route path="*" element={<Navigate to="/compare" replace />} />
        </Routes>
      </main>
    </div>
  );
}
