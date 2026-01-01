import React, { useEffect, useMemo, useState } from "react";
import { fetchOtaTargets, fetchCacheHistory } from "../api/consent";
import "./OtaCache.css";

function maxRiskFromDiff(diff) {
  const arr = diff?.changes || [];
  if (!Array.isArray(arr) || arr.length === 0) return 0;
  return Math.max(0, ...arr.map((c) => Number(c?.risk_score ?? 0)));
}

function topCategories(diff, limit = 3) {
  const arr = diff?.changes || [];
  if (!Array.isArray(arr) || arr.length === 0) return [];
  const counts = new Map();
  for (const ch of arr) {
    const k = ch?.category || "Other";
    counts.set(k, (counts.get(k) || 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([k, v]) => ({ category: k, count: v }));
}

function formatWhen(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function OtaCache() {
  const [tab, setTab] = useState("latest"); // latest | browse
  const [targets, setTargets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  // feed: list of { service_id, doc_type, name, history, last_diff_at, summary... }
  const [feed, setFeed] = useState([]);

  // browse selection
  const [selected, setSelected] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      setErr("");
      try {
        const t = await fetchOtaTargets();
        const list = Array.isArray(t) ? t : [];
        setTargets(list);

        // default select first
        if (list.length) {
          setSelected(`${list[0].service_id}:${list[0].doc_type}`);
        }

        // build latest feed by fetching cache history for each target
        const results = await Promise.all(
          list.map(async (x) => {
            const sid = x.service_id;
            const dt = x.doc_type;
            try {
              const hist = await fetchCacheHistory(sid, dt);
              const lastDiff = hist?.last_diff;
              const last_diff_at =
                lastDiff?.generated_at ||
                hist?.latest?.fetched_at ||
                hist?.latest?.generated_at ||
                null;

              const summary = {
                num_changes:
                  lastDiff?.engine?.num_changes ??
                  (Array.isArray(lastDiff?.changes) ? lastDiff.changes.length : 0) ??
                  0,
                max_risk: maxRiskFromDiff(lastDiff),
                top_categories: topCategories(lastDiff, 3),
              };

              return {
                ...x,
                history: hist,
                last_diff_at,
                summary,
                ok: true,
              };
            } catch (e) {
              // if no cache yet, just skip from feed
              return { ...x, ok: false, error: e?.message || "No cache" };
            }
          })
        );

        const okOnes = results
          .filter((r) => r.ok && r.history)
          .sort((a, b) => {
            const aa = a.last_diff_at || "";
            const bb = b.last_diff_at || "";
            return bb.localeCompare(aa);
          });

        setFeed(okOnes);
      } catch (e) {
        setErr(e?.message || "Failed to load OTA cache");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const selectedTarget = useMemo(() => {
    if (!selected) return null;
    const [sid, dt] = selected.split(":");
    return targets.find((t) => t.service_id === sid && t.doc_type === dt) || null;
  }, [selected, targets]);

  const selectedItem = useMemo(() => {
    if (!selectedTarget) return null;
    return feed.find(
      (x) =>
        x.service_id === selectedTarget.service_id &&
        x.doc_type === selectedTarget.doc_type
    ) || null;
  }, [selectedTarget, feed]);

  const globalSummary = useMemo(() => {
    const totalTracked = feed.length;
    const changedRecently = feed.filter((x) => (x.summary?.num_changes || 0) > 0).length;
    const maxRisk = totalTracked
      ? Math.max(0, ...feed.map((x) => Number(x.summary?.max_risk ?? 0)))
      : 0;
    return { totalTracked, changedRecently, maxRisk };
  }, [feed]);

  if (loading) {
    return (
      <div className="oc-page">
        <div className="oc-loading">Loading OTA cache…</div>
      </div>
    );
  }

  if (err) {
    return (
      <div className="oc-page">
        <div className="oc-error">Error: {err}</div>
      </div>
    );
  }

  return (
    <div className="oc-page">
      <header className="oc-header">
        <div>
          <h1 className="oc-title">OTA Cache</h1>
          <p className="oc-sub">
            View rolling cache + latest diffs pulled by GitHub Actions.
          </p>
        </div>

        <div className="oc-kpis">
          <div className="oc-kpi">
            <div className="oc-kpi-num">{globalSummary.totalTracked}</div>
            <div className="oc-kpi-lbl">targets with cache</div>
          </div>
          <div className="oc-kpi">
            <div className="oc-kpi-num">{globalSummary.changedRecently}</div>
            <div className="oc-kpi-lbl">have diffs</div>
          </div>
          <div className="oc-kpi">
            <div className="oc-kpi-num">{globalSummary.maxRisk.toFixed(1)}</div>
            <div className="oc-kpi-lbl">max risk seen</div>
          </div>
        </div>
      </header>

      <div className="oc-tabs">
        <button
          className={`oc-tab ${tab === "latest" ? "active" : ""}`}
          onClick={() => setTab("latest")}
        >
          Latest updates
        </button>
        <button
          className={`oc-tab ${tab === "browse" ? "active" : ""}`}
          onClick={() => setTab("browse")}
        >
          Browse by service
        </button>
      </div>

      {tab === "latest" && (
        <section className="oc-feed">
          {feed.length === 0 ? (
            <div className="oc-empty">
              No cached targets found yet. Run the sync once to initialize cache.
            </div>
          ) : (
            <div className="oc-grid">
              {feed.map((x) => {
                const lastDiff = x.history?.last_diff;
                const summary = x.summary || {};
                return (
                  <div className="oc-card" key={`${x.service_id}:${x.doc_type}`}>
                    <div className="oc-card-top">
                      <div className="oc-card-name">{x.name}</div>
                      <div className="oc-card-meta">
                        <span>{x.service_id}</span>
                        <span>•</span>
                        <span>{x.doc_type}</span>
                      </div>
                    </div>

                    <div className="oc-card-mid">
                      <div className="oc-pill">
                        {summary.num_changes || 0} changes
                      </div>
                      <div className={`oc-pill risk r${Math.min(3, Math.floor(summary.max_risk || 0))}`}>
                        max risk {Number(summary.max_risk || 0).toFixed(1)}
                      </div>
                      <div className="oc-time">
                        last update: <strong>{formatWhen(x.last_diff_at)}</strong>
                      </div>
                    </div>

                    <div className="oc-card-btm">
                      <div className="oc-mini">
                        <div className="oc-mini-title">Top categories</div>
                        {summary.top_categories?.length ? (
                          <ul className="oc-mini-list">
                            {summary.top_categories.map((c) => (
                              <li key={c.category}>
                                {c.category} <span>({c.count})</span>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <div className="oc-mini-muted">—</div>
                        )}
                      </div>

                      <button
                        className="oc-btn"
                        onClick={() => {
                          setSelected(`${x.service_id}:${x.doc_type}`);
                          setTab("browse");
                        }}
                      >
                        View details →
                      </button>
                    </div>

                    {/* quick teaser */}
                    {lastDiff?.changes?.[0]?.explanation && (
                      <div className="oc-teaser">
                        <strong>Example:</strong> {lastDiff.changes[0].explanation}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {tab === "browse" && (
        <section className="oc-browse">
          <div className="oc-browse-bar">
            <label className="oc-label">Select target</label>
            <select
              className="oc-select"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              {targets.map((t) => {
                const v = `${t.service_id}:${t.doc_type}`;
                return (
                  <option key={v} value={v}>
                    {t.name} ({v})
                  </option>
                );
              })}
            </select>
          </div>

          {!selectedItem ? (
            <div className="oc-empty">
              No cache found yet for this target. Wait for sync to create it.
            </div>
          ) : (
            <div className="oc-detail">
              <div className="oc-detail-head">
                <div>
                  <div className="oc-detail-title">{selectedItem.name}</div>
                  <div className="oc-detail-sub">
                    {selectedItem.service_id}:{selectedItem.doc_type}
                  </div>
                </div>

                <div className="oc-detail-pills">
                  <span className="oc-pill">
                    {selectedItem.summary?.num_changes || 0} changes
                  </span>
                  <span className="oc-pill">
                    max risk {Number(selectedItem.summary?.max_risk || 0).toFixed(1)}
                  </span>
                </div>
              </div>

              <div className="oc-hint">
                Tip: to see the **full policy text**, use “View latest policy text” (see below in section 3).
              </div>

              {/* show diff summary only */}
              <div className="oc-diff-summary">
                <div><strong>Latest fetched:</strong> {formatWhen(selectedItem.history?.latest?.fetched_at)}</div>
                <div><strong>Last diff generated:</strong> {formatWhen(selectedItem.history?.last_diff?.generated_at)}</div>
              </div>

              {/* show changes list (summary style) */}
              <div className="oc-changes">
                {(selectedItem.history?.last_diff?.changes || []).map((ch, idx) => (
                  <div className="oc-change" key={idx}>
                    <div className="oc-change-top">
                      <div className="oc-change-cat">{ch.category || "Other"}</div>
                      <div className="oc-change-risk">
                        Risk {Number(ch.risk_score ?? 0).toFixed(1)}
                      </div>
                      <div className="oc-change-type">{ch.type}</div>
                    </div>
                    <div className="oc-change-exp">{ch.explanation}</div>
                    <div className="oc-change-act">
                      <strong>Suggested action:</strong> {ch.suggested_action}
                    </div>
                  </div>
                ))}
                {(!selectedItem.history?.last_diff?.changes ||
                  selectedItem.history.last_diff.changes.length === 0) && (
                  <div className="oc-empty">No differences detected in last diff.</div>
                )}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
