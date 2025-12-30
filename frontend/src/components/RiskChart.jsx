import React, { useMemo } from "react";
import "./RiskChart.css";

function clamp(n, lo, hi) {
  return Math.max(lo, Math.min(hi, n));
}

function bucket(score) {
  const s = Number(score ?? 0);
  if (s >= 3) return "high";
  if (s >= 2) return "med";
  if (s >= 1) return "low";
  return "info";
}

export default function RiskChart({ data }) {
  const summary = useMemo(() => {
    const changes = Array.isArray(data?.changes) ? data.changes : [];
    const counts = { high: 0, med: 0, low: 0, info: 0 };
    let maxRisk = 0;

    for (const ch of changes) {
      const r = Number(ch?.risk_score ?? 0);
      maxRisk = Math.max(maxRisk, r);
      counts[bucket(r)] += 1;
    }

    const total = changes.length || 0;
    return { total, counts, maxRisk };
  }, [data]);

  const rows = [
    { key: "high", label: "High (≥3)", value: summary.counts.high },
    { key: "med", label: "Medium (≥2)", value: summary.counts.med },
    { key: "low", label: "Low (≥1)", value: summary.counts.low },
    { key: "info", label: "Info (<1)", value: summary.counts.info },
  ];

  const maxBar = Math.max(1, ...rows.map((r) => r.value));

  return (
    <div className="rc-wrap">
      <div className="rc-head">
        <div className="rc-title">Risk breakdown</div>
        <div className="rc-sub">
          {summary.total} changes • max risk {summary.maxRisk.toFixed(1)}
        </div>
      </div>

      <div className="rc-bars">
        {rows.map((r) => {
          const pct = clamp((r.value / maxBar) * 100, 0, 100);
          return (
            <div className="rc-row" key={r.key}>
              <div className="rc-label">{r.label}</div>
              <div className="rc-bar">
                <div className={`rc-fill ${r.key}`} style={{ width: `${pct}%` }} />
              </div>
              <div className="rc-num">{r.value}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
