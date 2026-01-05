import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ResultPanel from "../components/ResultPanel";
import { getHistoryItem } from "../store/historyStore";
import "./HistoryDetail.css";

function escapeRegExp(s) {
  return String(s || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlightParts(text, needle) {
  const t = String(text || "");
  const n = String(needle || "").trim();
  if (!n) return t;

  try {
    const re = new RegExp(escapeRegExp(n), "ig");
    const parts = t.split(re);
    const matches = t.match(re) || [];

    const out = [];
    for (let i = 0; i < parts.length; i++) {
      out.push(parts[i]);
      if (i < matches.length) {
        out.push(
          <mark key={`${i}-${matches[i]}-${i}`} className="hd-mark">
            {matches[i]}
          </mark>
        );
      }
    }
    return out;
  } catch {
    return t;
  }
}

function PolicyModal({ open, title, meta, text, find, onClose }) {
  const preRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    // scroll to first match
    try {
      const root = preRef.current;
      if (!root) return;
      const mark = root.querySelector("mark");
      if (mark?.scrollIntoView) mark.scrollIntoView({ block: "center", behavior: "smooth" });
    } catch {
      // ignore
    }
  }, [open, find, text]);

  if (!open) return null;

  return (
    <div className="hd-modalOverlay" onMouseDown={onClose}>
      <div className="hd-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="hd-modalHeader">
          <div>
            <div className="hd-modalTitle">{title}</div>
            {meta ? <div className="hd-modalMeta">{meta}</div> : null}
          </div>
          <button className="hd-modalClose" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="hd-modalTools">
          <input className="hd-find" value={find || ""} readOnly placeholder="Find in policy (from Find buttons)" />
          <button className="hd-findBtn" onClick={() => { /* read-only */ }}>
            Find
          </button>
        </div>

        <div className="hd-modalBody">
          <pre ref={preRef} className="hd-policyText">
            {highlightParts(text, find)}
          </pre>
        </div>
      </div>
    </div>
  );
}

export default function HistoryDetail() {
  const nav = useNavigate();
  const { id } = useParams();

  const item = useMemo(() => getHistoryItem(id), [id]);
  const result = item?.result;

  const [modalOpen, setModalOpen] = useState(false);
  const [modalTitle, setModalTitle] = useState("");
  const [modalMeta, setModalMeta] = useState("");
  const [modalText, setModalText] = useState("");
  const [findNeedle, setFindNeedle] = useState("");
  const [warn, setWarn] = useState("");

  if (!item) {
    return (
      <div style={{ padding: 24, textAlign: "left" }}>
        <button onClick={() => nav("/history")}>← Back</button>
        <h2>Not found</h2>
        <p>This history item doesn’t exist on this browser (deleted or cleared).</p>
      </div>
    );
  }

  // ✅ NEW SOURCE OF TRUTH: saved sources from PolicyCompare
  const sources = item.sources || null;

  const oldSavedText = sources?.old?.text || "";
  const newSavedText = sources?.new?.text || "";

  const hasSavedPolicies = Boolean(oldSavedText || newSavedText);

  // fallback: OTA cache tools
  const hasCacheTarget = Boolean(item.service_id && item.doc_type);

  function openModal(kind, findText = "") {
    setWarn("");
    setFindNeedle(findText || "");

    const txt = kind === "old" ? oldSavedText : newSavedText;
    if (!txt) {
      setWarn(
        "This history entry does not contain stored policy text. Re-run the comparison once (after the PolicyCompare update) so the old/new policy text is saved into history."
      );
      return;
    }

    setModalTitle(`${item.title} — ${kind === "old" ? "old policy" : "new policy"}`);
    setModalMeta(
      [
        `${item.mode}`,
        sources?.old?.type || sources?.new?.type ? `source: ${kind === "old" ? sources?.old?.type : sources?.new?.type}` : null,
        item.created_at ? `saved: ${new Date(item.created_at).toLocaleString()}` : null,
      ]
        .filter(Boolean)
        .join(" • ")
    );
    setModalText(txt);
    setModalOpen(true);
  }

  function openOtaCache(version) {
    if (!hasCacheTarget) return;
    nav(
      `/ota-cache?service_id=${encodeURIComponent(item.service_id)}&doc_type=${encodeURIComponent(
        item.doc_type
      )}&version=${encodeURIComponent(version)}`
    );
  }

  // used by ResultPanel Find buttons (we highlight in modal)
  function snippetForChange(ch, side) {
    const s = side === "old" ? ch?.old : ch?.new;
    const fallback = ch?.explanation || "";
    const raw = String(s || fallback || "").trim();
    if (!raw) return "";
    return raw.length > 220 ? raw.slice(0, 220) : raw;
  }

  return (
    <div className="hd-page">
      <header className="hd-header">
        <div>
          <button className="hd-back" onClick={() => nav("/history")}>
            ← Back
          </button>

          <div className="hd-title">{item.title}</div>

          <div className="hd-sub">
            {new Date(item.created_at).toLocaleString()} • {item.mode} • {item.service_id || item.source}
            {item.doc_type ? ` • ${item.doc_type}` : ""} {" • "}
            {item.num_changes} changes
          </div>

          <div className="hd-sub" style={{ marginTop: 6 }}>
            <strong>Request:</strong> {result?.request_id || "—"} &nbsp; • &nbsp;
            <strong>Generated:</strong> {result?.generated_at || "—"} &nbsp; • &nbsp;
            <strong>Max risk:</strong> {item.max_risk ?? 0}
          </div>
        </div>
      </header>

      {/* ✅ Policy tools */}
      <section className="hd-tools">
        <div className="hd-toolsTop">
          <div>
            <div className="hd-toolsTitle">Policy tools</div>
            <div className="hd-toolsSub">
              View the full old/new policy and use Find-in-policy to highlight text from specific changes.
            </div>
          </div>
        </div>

        <div className="hd-toolsGrid">
          <div className="hd-toolCard">
            <div className="hd-toolLabel">Old policy</div>

            {oldSavedText ? (
              <button className="hd-btn" onClick={() => openModal("old", "")}>
                View old policy
              </button>
            ) : hasCacheTarget ? (
              <button className="hd-btn" onClick={() => openOtaCache("previous")}>
                View previous policy (OTA cache)
              </button>
            ) : (
              <div className="hd-toolsMuted">Old policy not available (not stored yet).</div>
            )}
          </div>

          <div className="hd-toolCard">
            <div className="hd-toolLabel">New policy</div>

            {newSavedText ? (
              <button className="hd-btn" onClick={() => openModal("new", "")}>
                View new policy
              </button>
            ) : hasCacheTarget ? (
              <button className="hd-btn" onClick={() => openOtaCache("latest")}>
                View latest policy (OTA cache)
              </button>
            ) : (
              <div className="hd-toolsMuted">New policy not available (not stored yet).</div>
            )}
          </div>
        </div>

        {!hasSavedPolicies ? (
          <div className="hd-toolsMuted" style={{ marginTop: 10 }}>
            This history entry was saved before policy text storage existed. Re-run the comparison once and it will be stored here automatically.
          </div>
        ) : null}

        {warn ? <div className="hd-warn">{warn}</div> : null}
      </section>

      <div className="hd-body">
        <ResultPanel
          data={result}
          loading={false}
          error={""}
          showMeta={false}
          onFindOld={(ch) => openModal("old", snippetForChange(ch, "old"))}
          onFindNew={(ch) => openModal("new", snippetForChange(ch, "new"))}
        />
      </div>

      <PolicyModal
        open={modalOpen}
        title={modalTitle}
        meta={modalMeta}
        text={modalText}
        find={findNeedle}
        onClose={() => setModalOpen(false)}
      />
    </div>
  );
}
