import React, { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { fetchOtaTargets, fetchCacheHistory, fetchCachePolicy } from "../api/consent";
import "./OtaCache.css";

/**
 * =========================
 * Helpers
 * =========================
 */

function formatWhen(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function maxRiskFromDiff(diff) {
  const arr = Array.isArray(diff?.changes) ? diff.changes : [];
  if (!arr.length) return 0;
  return Math.max(0, ...arr.map((c) => Number(c?.risk_score ?? 0)));
}

/**
 * Human-friendly impact mapping (hide raw risk unless user asks for evidence).
 */
function impactFromRisk(risk) {
  const r = Number(risk ?? 0);
  if (r >= 3) return { label: "High impact", cls: "oc-impact oc-impact-high" };
  if (r >= 2) return { label: "Medium impact", cls: "oc-impact oc-impact-medium" };
  return { label: "Minor change", cls: "oc-impact oc-impact-minor" };
}

/**
 * Very lightweight heuristic “Key insights” (no LLM).
 * Keep this short and practical; avoid spammy category counts.
 */
const ENTITY_PATTERNS = [
  { label: "Email", re: /\bemail\b/i },
  { label: "Phone", re: /\bphone\b|\bmobile\b/i },
  { label: "Location", re: /\blocation\b|\bgps\b|\bgeolocation\b/i },
  { label: "Payment", re: /\bcard\b|\bpayment\b|\bbilling\b/i },
  { label: "Contacts", re: /\bcontacts?\b|\baddress book\b/i },
  { label: "Cookies/IDs", re: /\bcookie\b|\bidentifier\b|\bdevice id\b/i },
  { label: "Ads", re: /\bads?\b|\badvertis/i },
  { label: "Biometric", re: /\bbiometric\b|\bface\b|\bfingerprint\b/i },
  { label: "Health", re: /\bhealth\b|\bmedical\b/i },
];

function scanEntities(text) {
  const found = new Set();
  const t = String(text || "");
  for (const p of ENTITY_PATTERNS) {
    if (p.re.test(t)) found.add(p.label);
  }
  return [...found];
}

function pickHighRiskExamples(diff, limit = 2) {
  const changes = Array.isArray(diff?.changes) ? diff.changes : [];
  const seen = new Set();
  const out = [];

  for (const ch of changes) {
    const risk = Number(ch?.risk_score ?? 0);
    if (risk < 3) continue;

    const exp = String(ch?.explanation || "").trim();
    if (!exp) continue;

    const key = exp.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);

    out.push(exp);
    if (out.length >= limit) break;
  }

  return out;
}

function buildInsights(diff) {
  const changes = Array.isArray(diff?.changes) ? diff.changes : [];
  if (!changes.length) return ["No differences detected in the latest diff."];

  const allText = changes
    .map((c) => [c.category, c.explanation, c.old, c.new].filter(Boolean).join(" "))
    .join("\n");

  const insights = [];

  const ents = scanEntities(allText);
  if (/\bcollect\b|\bgather\b|\bobtain\b|\bwe receive\b/i.test(allText) && ents.length) {
    insights.push(`Possible expanded collection: ${ents.slice(0, 5).join(", ")}.`);
  }

  if (/\bthird part(y|ies)\b|\bshare\b|\bdisclos(e|ure)\b|\bpartners?\b/i.test(allText)) {
    insights.push("Sharing/disclosure language changed (review third-party sharing clauses).");
  }

  if (/\btrack\b|\bprofil(e|ing)\b|\banalytics\b|\bpersonaliz(e|ation)\b|\btarget(ed)? ads?\b/i.test(allText)) {
    insights.push("Tracking/analytics language changed (check cookies + ads controls).");
  }

  if (/\bretain\b|\bretention\b|\bstorage\b|\bkeep\b.*\bfor\b/i.test(allText)) {
    insights.push("Retention wording changed (review how long data is kept and deletion rules).");
  }

  const hi = pickHighRiskExamples(diff, 2);
  if (hi[0]) insights.push(`High-risk highlight: ${hi[0]}`);
  if (hi[1]) insights.push(`Another high-risk highlight: ${hi[1]}`);

  if (!insights.length) insights.push("Changes detected—review items below for details.");

  const seen = new Set();
  const out = [];
  for (const line of insights) {
    const k = String(line).trim().toLowerCase();
    if (!k || seen.has(k)) continue;
    seen.add(k);
    out.push(line);
  }
  return out.slice(0, 5);
}

/**
 * Action-first summary (the “assistant” layer).
 * - Uses suggested_action + category + impact.
 * - Keeps it human, short, and non-numeric.
 */
function buildActionSummary(diff, maxItems = 3) {
  const changes = Array.isArray(diff?.changes) ? diff.changes : [];
  if (!changes.length) {
    return {
      headline: "No action needed.",
      bullets: ["No meaningful differences were detected in the latest update."],
    };
  }

  const sorted = [...changes].sort((a, b) => Number(b?.risk_score ?? 0) - Number(a?.risk_score ?? 0));

  const high = sorted.filter((c) => Number(c?.risk_score ?? 0) >= 3);
  const medium = sorted.filter((c) => Number(c?.risk_score ?? 0) >= 2 && Number(c?.risk_score ?? 0) < 3);

  let headline = "Review the key changes.";
  if (high.length) headline = "Important update — review the highlighted sections.";
  else if (medium.length) headline = "Some changes may affect your privacy — worth a quick check.";
  else headline = "Minor update — skim if you want reassurance.";

  const bullets = [];
  const used = new Set();

  for (const ch of sorted) {
    const impact = impactFromRisk(ch?.risk_score);
    const cat = String(ch?.category || "Other").trim();
    const act = String(ch?.suggested_action || "").trim();
    if (!act) continue;

    const key = `${cat}::${act}`.toLowerCase();
    if (used.has(key)) continue;
    used.add(key);

    // Example bullet:
    // "High impact: Tracking, analytics & profiling — Review privacy settings to limit tracking..."
    bullets.push(`${impact.label}: ${cat} — ${act}`);

    if (bullets.length >= maxItems) break;
  }

  // Fallback: if suggested_action missing, use explanation
  if (!bullets.length) {
    for (const ch of sorted) {
      const impact = impactFromRisk(ch?.risk_score);
      const cat = String(ch?.category || "Other").trim();
      const exp = String(ch?.explanation || "").trim();
      if (!exp) continue;

      const key = `${cat}::${exp}`.toLowerCase();
      if (used.has(key)) continue;
      used.add(key);

      bullets.push(`${impact.label}: ${cat} — ${exp}`);
      if (bullets.length >= maxItems) break;
    }
  }

  if (!bullets.length) bullets.push("Open the details below to see what changed and where it appears in the policy.");

  return { headline, bullets };
}

function escapeRegExp(str) {
  return String(str || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Renders policy text and highlights the first match of `query`.
 * Adds id="cc-hit" so we can scroll into view.
 */
function renderHighlightedText(text, query) {
  const t = String(text || "");
  const q = String(query || "").trim();
  if (!q) return <pre className="oc-modal-pre">{t}</pre>;

  let idx = t.indexOf(q);
  let len = q.length;

  if (idx < 0) {
    const re = new RegExp(escapeRegExp(q), "i");
    const m = re.exec(t);
    if (!m) return <pre className="oc-modal-pre">{t}</pre>;
    idx = m.index;
    len = m[0].length;
  }

  const before = t.slice(0, idx);
  const hit = t.slice(idx, idx + len);
  const after = t.slice(idx + len);

  return (
    <pre className="oc-modal-pre">
      {before}
      <mark id="cc-hit" className="oc-hit">
        {hit}
      </mark>
      {after}
    </pre>
  );
}

/**
 * Choose a “search snippet” likely to exist in policy text.
 */
function snippetFor(ch) {
  const newText = String(ch?.new ?? "").trim();
  const oldText = String(ch?.old ?? "").trim();
  if (newText) return { version: "latest", query: newText };
  if (oldText) return { version: "previous", query: oldText };
  const exp = String(ch?.explanation ?? "").trim();
  return { version: "latest", query: exp };
}

/**
 * =========================
 * Modal
 * =========================
 */
function PolicyModal({ open, title, subtitle, text, highlight, onClose }) {
  const bodyRef = useRef(null);

  useEffect(() => {
    if (!open) return;

    const t = setTimeout(() => {
      const hit = document.getElementById("cc-hit");
      if (hit) hit.scrollIntoView({ block: "center", behavior: "smooth" });
      else if (bodyRef.current) bodyRef.current.scrollTop = 0;
    }, 50);

    return () => clearTimeout(t);
  }, [open, text, highlight]);

  if (!open) return null;

  return (
    <div className="oc-modal-overlay" onMouseDown={onClose}>
      <div className="oc-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="oc-modal-head">
          <div>
            <div className="oc-modal-title">{title}</div>
            <div className="oc-modal-sub">{subtitle}</div>
          </div>
          <button className="oc-modal-x" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="oc-modal-body" ref={bodyRef}>
          {renderHighlightedText(text, highlight)}
        </div>
      </div>
    </div>
  );
}

/**
 * =========================
 * Component
 * =========================
 */
export default function OtaCache() {
  const [tab, setTab] = useState("latest"); // latest | browse
  const [targets, setTargets] = useState([]);
  const [feed, setFeed] = useState([]);

  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  // Expanded/collapsed state for diff items
  const [openChanges, setOpenChanges] = useState({});

  // Evidence toggles (per change)
  const [openEvidence, setOpenEvidence] = useState({});

  // Policy modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [modalTitle, setModalTitle] = useState("");
  const [modalSubtitle, setModalSubtitle] = useState("");
  const [modalText, setModalText] = useState("");
  const [modalLoading, setModalLoading] = useState(false);
  const [modalHighlight, setModalHighlight] = useState("");

  const toggleChange = (key) => setOpenChanges((s) => ({ ...s, [key]: !s[key] }));
  const toggleEvidence = (key) => setOpenEvidence((s) => ({ ...s, [key]: !s[key] }));

    // ✅ Deep-link support (SPA)
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();


  /**
   * Initial load:
   * - targets list
   * - history for each target (for latest feed)
   */
  useEffect(() => {
    (async () => {
      setLoading(true);
      setErr("");

      try {
        const t = await fetchOtaTargets();
        const list = Array.isArray(t) ? t : [];
        setTargets(list);

        if (list.length) setSelected(`${list[0].service_id}:${list[0].doc_type}`);

        // ✅ Deep-link: /ota-cache?service_id=facebook&doc_type=privacy_policy
        // When present, force selection + switch to browse tab.
        useEffect(() => {
          if (!targets.length) return;

          const sid = searchParams.get("service_id");
          const dt = searchParams.get("doc_type");
          if (!sid || !dt) return;

          const match = targets.find((t) => t.service_id === sid && t.doc_type === dt);
          if (!match) return;

          const next = `${match.service_id}:${match.doc_type}`;

          // Avoid loops / unnecessary state updates
          if (selected !== next) setSelected(next);

          // If user came from extension, show the details view
          if (tab !== "browse") setTab("browse");
        }, [targets, searchParams, selected, tab]);


        const results = await Promise.all(
          list.map(async (x) => {
            try {
              const hist = await fetchCacheHistory(x.service_id, x.doc_type);
              const lastDiff = hist?.last_diff;

              const last_diff_at =
                lastDiff?.generated_at ||
                hist?.latest?.fetched_at ||
                hist?.latest?.generated_at ||
                null;

              return {
                ...x,
                history: hist,
                last_diff_at,
                summary: {
                  num_changes:
                    lastDiff?.engine?.num_changes ??
                    (Array.isArray(lastDiff?.changes) ? lastDiff.changes.length : 0) ??
                    0,
                  max_risk: maxRiskFromDiff(lastDiff),
                  insights: buildInsights(lastDiff),
                },
                ok: true,
              };
            } catch (e) {
              return { ...x, ok: false, error: e?.message || "No cache" };
            }
          })
        );

        const okOnes = results
          .filter((r) => r.ok && r.history)
          .sort((a, b) => (b.last_diff_at || "").localeCompare(a.last_diff_at || ""));

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
    return (
      feed.find(
        (x) => x.service_id === selectedTarget.service_id && x.doc_type === selectedTarget.doc_type
      ) || null
    );
  }, [selectedTarget, feed]);

  /**
   * Auto-expand ONLY high-risk items (risk >= 3) whenever selection changes.
   * Also reset evidence toggles for new selection (keeps UI clean).
   */
  useEffect(() => {
    if (!selectedItem?.history?.last_diff?.changes) return;

    const expanded = {};
    selectedItem.history.last_diff.changes.forEach((ch, idx) => {
      if (Number(ch?.risk_score ?? 0) >= 3) {
        const key = `${selectedItem.service_id}:${selectedItem.doc_type}:${idx}`;
        expanded[key] = true;
      }
    });

    setOpenChanges(expanded);
    setOpenEvidence({});
  }, [selectedItem]);

  const globalSummary = useMemo(() => {
    const totalTracked = feed.length;
    const withDiffs = feed.filter((x) => (x.summary?.num_changes || 0) > 0).length;
    const maxRisk = totalTracked ? Math.max(0, ...feed.map((x) => Number(x.summary?.max_risk ?? 0))) : 0;
    return { totalTracked, withDiffs, maxRisk };
  }, [feed]);

  const selectedActionSummary = useMemo(() => {
    return buildActionSummary(selectedItem?.history?.last_diff, 3);
  }, [selectedItem]);

  /**
   * Open policy modal and optionally highlight a query snippet
   */
  const openPolicy = async (serviceId, docType, version, highlight = "") => {
    setModalOpen(true);
    setModalLoading(true);
    setModalTitle(`${serviceId}:${docType}`);
    setModalSubtitle(`${version} policy text`);
    setModalText("");
    setModalHighlight(highlight || "");

    try {
      const res = await fetchCachePolicy(serviceId, docType, version);
      const fetchedAt = res?.fetched_at ? ` • fetched: ${formatWhen(res.fetched_at)}` : "";
      const sha = res?.content_sha256 ? ` • sha: ${String(res.content_sha256).slice(0, 12)}…` : "";
      setModalSubtitle(`${version} policy text${fetchedAt}${sha}`);
      setModalText(res?.text || "");
    } catch (e) {
      setModalText(`Failed to load policy: ${e?.message || "Unknown error"}`);
    } finally {
      setModalLoading(false);
    }
  };

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
          <p className="oc-sub">Rolling cache + diffs pulled by GitHub Actions.</p>
        </div>

        {/* Keep KPIs, but they’re small + not the focus */}
        <div className="oc-kpis">
          <div className="oc-kpi">
            <div className="oc-kpi-num">{globalSummary.totalTracked}</div>
            <div className="oc-kpi-lbl">targets with cache</div>
          </div>
          <div className="oc-kpi">
            <div className="oc-kpi-num">{globalSummary.withDiffs}</div>
            <div className="oc-kpi-lbl">have diffs</div>
          </div>
          <div className="oc-kpi">
            <div className="oc-kpi-num">{globalSummary.maxRisk.toFixed(1)}</div>
            <div className="oc-kpi-lbl">max risk seen</div>
          </div>
        </div>
      </header>

      <div className="oc-tabs">
        <button className={`oc-tab ${tab === "latest" ? "active" : ""}`} onClick={() => setTab("latest")}>
          Latest updates
        </button>
        <button className={`oc-tab ${tab === "browse" ? "active" : ""}`} onClick={() => setTab("browse")}>
          Browse by service
        </button>
      </div>

      {/* =========================
          Latest Feed
      ========================= */}
      {tab === "latest" && (
        <section className="oc-feed">
          {feed.length === 0 ? (
            <div className="oc-empty">No cached targets found yet. Run the sync once to initialize cache.</div>
          ) : (
            <div className="oc-grid">
              {feed.map((x) => {
                const summary = x.summary || {};
                const impact = impactFromRisk(summary.max_risk || 0);

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
                      <div className="oc-pill">{summary.num_changes || 0} change(s)</div>
                      <span className={impact.cls}>{impact.label}</span>
                      <div className="oc-time">
                        last update: <strong>{formatWhen(x.last_diff_at)}</strong>
                      </div>
                    </div>

                    <div className="oc-mini">
                      <div className="oc-mini-title">Key insights</div>
                      <ul className="oc-mini-list">
                        {(summary.insights || []).map((line, i) => (
                          <li key={i}>{line}</li>
                        ))}
                      </ul>
                    </div>

                    <div className="oc-card-btm">
                      <button
                        className="oc-btn"
                        onClick={() => {
                          const v = `${x.service_id}:${x.doc_type}`;
                          setSelected(v);
                          setTab("browse");

                          // ✅ Keep URL in sync
                          navigate(
                            `/ota-cache?service_id=${encodeURIComponent(x.service_id)}&doc_type=${encodeURIComponent(x.doc_type)}`,
                            { replace: true }
                          );
                        }}
                      >
                        View details →
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* =========================
          Browse View
      ========================= */}
      {tab === "browse" && (
        <section className="oc-browse">
          <div className="oc-browse-bar">
            <label className="oc-label">Select target</label>
            <select
              className="oc-select"
              value={selected}
              onChange={(e) => {
                const v = e.target.value;
                setSelected(v);

                // ✅ Keep URL in sync for deep-linking
                const [sid, dt] = v.split(":");
                if (sid && dt) {
                  navigate(
                    `/ota-cache?service_id=${encodeURIComponent(sid)}&doc_type=${encodeURIComponent(dt)}`,
                    { replace: true }
                  );
                }
              }}
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
            <div className="oc-empty">No cache found yet for this target. Wait for sync to create it.</div>
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
                  <span className="oc-pill">{selectedItem.summary?.num_changes || 0} change(s)</span>
                  <span className={impactFromRisk(selectedItem.summary?.max_risk || 0).cls}>
                    {impactFromRisk(selectedItem.summary?.max_risk || 0).label}
                  </span>
                </div>
              </div>

              {/* ✅ ACTION-FIRST SUMMARY (big marks booster) */}
              <div className="oc-action">
                <div className="oc-action-title">What you should do</div>
                <div className="oc-action-headline">{selectedActionSummary.headline}</div>
                <ul className="oc-action-list">
                  {(selectedActionSummary.bullets || []).map((b, i) => (
                    <li key={i}>{b}</li>
                  ))}
                </ul>
              </div>

              <div className="oc-detail-actions">
                <button
                  className="oc-btn"
                  type="button"
                  onClick={() => openPolicy(selectedItem.service_id, selectedItem.doc_type, "latest")}
                >
                  View latest policy
                </button>
                <button
                  className="oc-btn ghost"
                  type="button"
                  onClick={() => openPolicy(selectedItem.service_id, selectedItem.doc_type, "previous")}
                >
                  View previous policy
                </button>
              </div>

              <div className="oc-insights">
                <div className="oc-insights-title">Key insights</div>
                <ul className="oc-insights-list">
                  {(selectedItem.summary?.insights || []).map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </div>

              <div className="oc-diff-summary">
                <div>
                  <strong>Latest fetched:</strong> {formatWhen(selectedItem.history?.latest?.fetched_at)}
                </div>
                <div>
                  <strong>Last diff generated:</strong> {formatWhen(selectedItem.history?.last_diff?.generated_at)}
                </div>
              </div>

              <div className="oc-changes">
                {(selectedItem.history?.last_diff?.changes || []).map((ch, idx) => {
                  const key = `${selectedItem.service_id}:${selectedItem.doc_type}:${idx}`;
                  const isOpen = !!openChanges[key];
                  const evidenceOpen = !!openEvidence[key];
                  const impact = impactFromRisk(ch?.risk_score);

                  return (
                    <div className="oc-change" key={key}>
                      <div className="oc-change-top">
                        <div className="oc-change-cat">{ch.category || "Other"}</div>
                        <div className="oc-change-type">{ch.type}</div>
                        <span className={impact.cls}>{impact.label}</span>

                        <button
                          className="oc-change-toggle oc-btn sm"
                          type="button"
                          onClick={() => toggleChange(key)}
                        >
                          {isOpen ? "Hide" : "Details"}
                        </button>
                      </div>

                      <div className="oc-change-exp">{ch.explanation}</div>

                      <div className="oc-change-act">
                        <strong>Suggested action:</strong> {ch.suggested_action}
                      </div>

                      {isOpen && (
                        <>
                          <div className="oc-diff">
                            {/* Old */}
                            <div className="oc-diff-col">
                              <div className="oc-diff-head">
                                <div className="oc-diff-label">Old</div>
                                <button
                                  className="oc-btn sm ghost"
                                  type="button"
                                  disabled={!String(ch?.old ?? "").trim()}
                                  title={!String(ch?.old ?? "").trim() ? "No old snippet available" : ""}
                                  onClick={() =>
                                    openPolicy(
                                      selectedItem.service_id,
                                      selectedItem.doc_type,
                                      "previous",
                                      String(ch?.old ?? "")
                                    )
                                  }
                                >
                                  Find in policy →
                                </button>
                              </div>
                              <pre className="oc-diff-pre">{String(ch?.old ?? "").trim() || "—"}</pre>
                            </div>

                            {/* New */}
                            <div className="oc-diff-col">
                              <div className="oc-diff-head">
                                <div className="oc-diff-label">New</div>
                                <button
                                  className="oc-btn sm ghost"
                                  type="button"
                                  disabled={!String(ch?.new ?? "").trim()}
                                  title={!String(ch?.new ?? "").trim() ? "No new snippet available" : ""}
                                  onClick={() =>
                                    openPolicy(
                                      selectedItem.service_id,
                                      selectedItem.doc_type,
                                      "latest",
                                      String(ch?.new ?? "")
                                    )
                                  }
                                >
                                  Find in policy →
                                </button>
                              </div>
                              <pre className="oc-diff-pre">{String(ch?.new ?? "").trim() || "—"}</pre>
                            </div>
                          </div>

                          {/* ✅ Evidence toggle (keeps UI calm; numbers on demand) */}
                          <div className="oc-evidence">
                            <button
                              className="oc-evidence-toggle"
                              type="button"
                              onClick={() => toggleEvidence(key)}
                            >
                              {evidenceOpen ? "Hide evidence & technical details" : "Evidence & technical details"}
                            </button>

                            {evidenceOpen && (
                              <div className="oc-evidence-box">
                                <div>
                                  <strong>Risk score:</strong> {Number(ch?.risk_score ?? 0).toFixed(1)}
                                </div>
                                <div>
                                  <strong>Similarity:</strong>{" "}
                                  {ch?.similarity == null ? "—" : Number(ch.similarity).toFixed(3)}
                                </div>
                                <div>
                                  <strong>Old index:</strong> {ch?.old_index == null ? "—" : String(ch.old_index)}
                                </div>
                                <div>
                                  <strong>New index:</strong> {ch?.new_index == null ? "—" : String(ch.new_index)}
                                </div>

                                {/* If old/new missing, provide best-effort “find” */}
                                {!String(ch?.old ?? "").trim() && !String(ch?.new ?? "").trim() && (
                                  <button
                                    className="oc-btn sm"
                                    type="button"
                                    onClick={() => {
                                      const snip = snippetFor(ch);
                                      openPolicy(selectedItem.service_id, selectedItem.doc_type, snip.version, snip.query);
                                    }}
                                  >
                                    Find best match →
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  );
                })}

                {(!selectedItem.history?.last_diff?.changes || selectedItem.history.last_diff.changes.length === 0) && (
                  <div className="oc-empty">No differences detected in last diff.</div>
                )}
              </div>
            </div>
          )}
        </section>
      )}

      <PolicyModal
        open={modalOpen}
        title={modalTitle}
        subtitle={modalLoading ? "Loading policy…" : modalSubtitle}
        text={modalLoading ? "Loading…" : modalText}
        highlight={modalHighlight}
        onClose={() => setModalOpen(false)}
      />
    </div>
  );
}
