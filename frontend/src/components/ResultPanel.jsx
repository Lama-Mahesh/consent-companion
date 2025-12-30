import React, { useMemo, useState } from "react";
import "./ResultPanel.css";
import RiskChart from "./RiskChart";

function Badge({ children, tone = "neutral", onClick, active = false, title }) {
  const Tag = onClick ? "button" : "span";
  return (
    <Tag
      type={onClick ? "button" : undefined}
      className={`rp-badge rp-${tone} ${onClick ? "rp-chip" : ""} ${active ? "is-active" : ""}`}
      onClick={onClick}
      title={title}
    >
      {children}
    </Tag>
  );
}

function riskTone(score) {
  if (score >= 3.0) return "high";
  if (score >= 2.0) return "med";
  return "low";
}

function toNum(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Props:
 * - data, loading, error
 * - showMeta (default true) -> set false in HistoryDetail
 */
export default function ResultPanel({ data, loading, error, showMeta = true }) {
  const [expanded, setExpanded] = useState({});
  const [riskView, setRiskView] = useState("all"); // all | high | med | low
  const [catFilter, setCatFilter] = useState("all"); // all | <category>

  const allChanges = useMemo(
    () => (Array.isArray(data?.changes) ? data.changes : []),
    [data]
  );

  // ----------------------------
  // Stats
  // ----------------------------
  const stats = useMemo(() => {
    const counts = { high: 0, med: 0, low: 0 };
    for (const ch of allChanges) {
      const r = toNum(ch?.risk_score);
      if (r >= 3) counts.high += 1;
      else if (r >= 2) counts.med += 1;
      else if (r >= 1) counts.low += 1;
    }
    return {
      total: allChanges.length,
      high: counts.high,
      med: counts.med,
      low: counts.low,
    };
  }, [allChanges]);

  const categories = useMemo(() => {
    const map = new Map(); // category -> count
    for (const ch of allChanges) {
      const cat = (ch?.category || "Uncategorized").trim() || "Uncategorized";
      map.set(cat, (map.get(cat) || 0) + 1);
    }
    const arr = Array.from(map.entries()).map(([category, count]) => ({ category, count }));
    arr.sort((a, b) => b.count - a.count);
    return arr;
  }, [allChanges]);

  const topCategories = useMemo(() => categories.slice(0, 5), [categories]);

  // ----------------------------
  // Filtering (risk + category)
  // ----------------------------
  const filteredChanges = useMemo(() => {
    let xs = allChanges;

    // risk filter
    if (riskView !== "all") {
      xs = xs.filter((ch) => {
        const r = toNum(ch?.risk_score);
        if (riskView === "high") return r >= 3;
        if (riskView === "med") return r >= 2 && r < 3;
        if (riskView === "low") return r >= 1 && r < 2;
        return true;
      });
    }

    // category filter
    if (catFilter !== "all") {
      xs = xs.filter((ch) => ((ch?.category || "Uncategorized").trim() || "Uncategorized") === catFilter);
    }

    return xs;
  }, [allChanges, riskView, catFilter]);

  const copyJson = async () => {
    await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
    alert("Copied JSON to clipboard");
  };

  const StatCard = ({ label, value, active, onClick }) => (
    <button
      type="button"
      className={`rp-stat rp-stat-btn ${active ? "is-active" : ""}`}
      onClick={onClick}
      disabled={!data || loading}
      title="Click to filter"
    >
      <div className="rp-stat-k">{label}</div>
      <div className="rp-stat-v">{value}</div>
    </button>
  );

  const showNoMatch =
    !loading &&
    !error &&
    data &&
    allChanges.length > 0 &&
    filteredChanges.length === 0;

  return (
    <div className="rp-wrap">
      <div className="rp-top">
        <h3>Results</h3>

        <div className="rp-actions" style={{ gap: 10 }}>
          <button className="rp-btn" type="button" onClick={copyJson} disabled={!data || loading}>
            Copy JSON
          </button>
        </div>
      </div>

      {loading && <div className="rp-state">Analyzing…</div>}
      {error && <div className="rp-error">Error: {error}</div>}

      {!loading && !error && !data && (
        <div className="rp-state">Run an analysis to see results here.</div>
      )}

      {data && (
        <>
          {/* ✅ Hide in HistoryDetail by showMeta={false} */}
          {showMeta && (
            <div className="rp-meta">
              <div className="rp-meta-row">
                <span className="rp-meta-k">request_id</span>
                <span className="rp-meta-v">{data.request_id}</span>
              </div>
              <div className="rp-meta-row">
                <span className="rp-meta-k">generated_at</span>
                <span className="rp-meta-v">{data.generated_at}</span>
              </div>
              <div className="rp-meta-row">
                <span className="rp-meta-k">mode</span>
                <span className="rp-meta-v">{data.engine?.mode}</span>
              </div>
              <div className="rp-meta-row">
                <span className="rp-meta-k">num_changes</span>
                <span className="rp-meta-v">{data.engine?.num_changes}</span>
              </div>
            </div>
          )}

          {/* ✅ Risk cards (click-to-filter) */}
          <div className="rp-stats">
            <StatCard
              label="High"
              value={stats.high}
              active={riskView === "high"}
              onClick={() => setRiskView((v) => (v === "high" ? "all" : "high"))}
            />
            <StatCard
              label="Medium"
              value={stats.med}
              active={riskView === "med"}
              onClick={() => setRiskView((v) => (v === "med" ? "all" : "med"))}
            />
            <StatCard
              label="Low"
              value={stats.low}
              active={riskView === "low"}
              onClick={() => setRiskView((v) => (v === "low" ? "all" : "low"))}
            />
            <StatCard
              label="Total"
              value={stats.total}
              active={riskView === "all"}
              onClick={() => setRiskView("all")}
            />
          </div>

          {/* ✅ Top categories mini summary */}
          <div className="rp-cats">
            <div className="rp-cats-head">
              <div className="rp-cats-title">Top categories</div>

              <div className="rp-cats-actions">
                {catFilter !== "all" && (
                  <button className="rp-linkbtn" type="button" onClick={() => setCatFilter("all")}>
                    Clear category filter
                  </button>
                )}
                {(riskView !== "all") && (
                  <button className="rp-linkbtn" type="button" onClick={() => setRiskView("all")}>
                    Clear risk filter
                  </button>
                )}
                {(riskView !== "all" || catFilter !== "all") && (
                  <button
                    className="rp-linkbtn"
                    type="button"
                    onClick={() => {
                      setRiskView("all");
                      setCatFilter("all");
                    }}
                  >
                    Reset all
                  </button>
                )}
              </div>
            </div>

            <div className="rp-chiprow">
              <Badge
                tone="neutral"
                onClick={() => setCatFilter("all")}
                active={catFilter === "all"}
                title="Show all categories"
              >
                All
              </Badge>

              {topCategories.map((c) => (
                <Badge
                  key={c.category}
                  tone="neutral"
                  onClick={() => setCatFilter((cur) => (cur === c.category ? "all" : c.category))}
                  active={catFilter === c.category}
                  title="Click to filter by this category"
                >
                  {c.category} · {c.count}
                </Badge>
              ))}
            </div>
          </div>

          {/* chart */}
          <RiskChart data={data} />

          {showNoMatch && (
            <div className="rp-state">
              No changes match the selected filters.
            </div>
          )}

          <div className="rp-list">
            {allChanges.length === 0 && <div className="rp-state">No differences detected.</div>}

            {filteredChanges.map((ch, idx) => {
              const cat = (ch?.category || "Uncategorized").trim() || "Uncategorized";
              const key = `${idx}-${cat}-${ch.type || ""}-${ch.old_index ?? ""}-${ch.new_index ?? ""}`;
              const open = !!expanded[key];
              const tone = riskTone(toNum(ch.risk_score));

              return (
                <div className="rp-card" key={key}>
                  <div className="rp-card-head">
                    <div className="rp-title">
                      <div className="rp-cat">
                        {/* ✅ Category chip inside cards too */}
                        <Badge
                          tone="neutral"
                          onClick={() => setCatFilter((cur) => (cur === cat ? "all" : cat))}
                          active={catFilter === cat}
                          title="Filter by this category"
                        >
                          {cat}
                        </Badge>
                      </div>

                      <div className="rp-sub">
                        <Badge tone={tone}>Risk {toNum(ch.risk_score).toFixed(1)}</Badge>
                        <Badge>{ch.type}</Badge>
                        {typeof ch.similarity === "number" && <Badge>Sim {ch.similarity.toFixed(2)}</Badge>}
                      </div>
                    </div>

                    <button
                      className="rp-toggle"
                      type="button"
                      onClick={() => setExpanded((s) => ({ ...s, [key]: !s[key] }))}
                    >
                      {open ? "Hide" : "Details"}
                    </button>
                  </div>

                  <div className="rp-explain">{ch.explanation}</div>
                  <div className="rp-action">
                    <strong>Suggested action:</strong> {ch.suggested_action}
                  </div>

                  {open && (
                    <div className="rp-diff">
                      <div className="rp-diff-col">
                        <div className="rp-diff-label">Old</div>
                        <pre className="rp-pre">{ch.old ?? ""}</pre>
                      </div>
                      <div className="rp-diff-col">
                        <div className="rp-diff-label">New</div>
                        <pre className="rp-pre">{ch.new ?? ""}</pre>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
