import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  clearHistory,
  loadHistory,
  removeHistoryItem,
  updateHistoryItem,
} from "../store/historyStore";
import "./History.css";

export default function History() {
  const [items, setItems] = useState(() => {
    const h = loadHistory();
    return Array.isArray(h) ? h : [];
});

  // filters
  const [q, setQ] = useState("");
  const [modeFilter, setModeFilter] = useState("all");
  const [serviceFilter, setServiceFilter] = useState("all");
  const [riskMin, setRiskMin] = useState(0);

  useEffect(() => {
    setItems(loadHistory());
  }, []);

  const services = useMemo(() => {
    const s = new Set(items.map((x) => x.service_id).filter(Boolean));
    return ["all", ...Array.from(s).sort()];
  }, [items]);

  const summary = useMemo(() => {
    return {
      total: items.length,
      changes: items.reduce((a, x) => a + (x.num_changes || 0), 0),
    };
  }, [items]);

  const filtered = useMemo(() => {
    const qq = q.trim().toLowerCase();
    return items.filter((x) => {
      if (modeFilter !== "all" && x.mode !== modeFilter) return false;
      if (serviceFilter !== "all" && x.service_id !== serviceFilter) return false;
      if ((x.max_risk ?? 0) < riskMin) return false;

      if (!qq) return true;

      const hay = [
        x.title,
        x.service_id,
        x.doc_type,
        x.source,
        x.mode,
        x.id,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return hay.includes(qq);
    });
  }, [items, q, modeFilter, serviceFilter, riskMin]);

  const onClear = () => {
    clearHistory();
    setItems([]);
  };

  const onDeleteOne = (id) => {
    setItems(removeHistoryItem(id));
  };

  const onTogglePin = (id, pinned) => {
    setItems(updateHistoryItem(id, { pinned: !pinned }));
  };

  return (
    <div className="hist-page">
      <header className="hist-header">
        <div>
          <h1 className="hist-h1">History</h1>
          <p className="hist-p">Saved comparison results on this device.</p>
        </div>

        <div className="hist-actions">
          <div className="hist-metrics">
            <span>{summary.total} results</span>
            <span>•</span>
            <span>{summary.changes} total changes</span>
          </div>
          <button
            className="hist-btn danger"
            onClick={onClear}
            disabled={!items.length}
          >
            Clear all
          </button>
        </div>
      </header>

      {items.length > 0 && (
        <div className="hist-filters">
          <input
            className="hist-input"
            placeholder="Search (service, mode, id, title…) "
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />

          <select
            className="hist-select"
            value={modeFilter}
            onChange={(e) => setModeFilter(e.target.value)}
          >
            <option value="all">All modes</option>
            <option value="semantic">semantic</option>
            <option value="basic">basic</option>
          </select>

          <select
            className="hist-select"
            value={serviceFilter}
            onChange={(e) => setServiceFilter(e.target.value)}
          >
            {services.map((s) => (
              <option key={s} value={s}>
                {s === "all" ? "All services" : s}
              </option>
            ))}
          </select>

          <select
            className="hist-select"
            value={riskMin}
            onChange={(e) => setRiskMin(Number(e.target.value))}
          >
            <option value={0}>Any risk</option>
            <option value={1}>Risk ≥ 1</option>
            <option value={2}>Risk ≥ 2</option>
            <option value={3}>Risk ≥ 3</option>
          </select>
        </div>
      )}

      {!items.length ? (
        <div className="hist-empty">
          No saved results yet. Run a comparison and it will appear here.
        </div>
      ) : (
        <div className="hist-list">
          {[...filtered]
            .sort(
              (a, b) =>
                Number(b.pinned) - Number(a.pinned) ||
                (b.created_at > a.created_at ? 1 : -1)
            )
            .map((x) => (
              <div className="hist-card" key={x.id}>
                <div className="hist-card-top">
                  <div className="hist-card-title">
                    {x.pinned && "📌 "} {x.title}
                  </div>
                  <div className="hist-card-meta">
                    <span>{new Date(x.created_at).toLocaleString()}</span>
                    <span>•</span>
                    <span>{x.mode}</span>
                    <span>•</span>
                    <span>{x.service_id || x.source}</span>
                    <span>•</span>
                    <span>{x.num_changes} changes</span>
                  </div>
                </div>

                <div className="hist-card-bottom">
                  <Link className="hist-btn" to={`/history/${x.id}`}>
                    View details
                  </Link>

                  <button
                    className="hist-btn ghost"
                    onClick={() => onTogglePin(x.id, x.pinned)}
                  >
                    {x.pinned ? "Unpin" : "Pin"}
                  </button>

                  <button
                    className="hist-btn ghost"
                    onClick={() => onDeleteOne(x.id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
