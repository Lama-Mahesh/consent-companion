import React from "react";
import "./SourcePanel.css";

function SelectorPill({ active, children, onClick }) {
  return (
    <button
      type="button"
      className={`sp-pill ${active ? "active" : ""}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export default function SourcePanel({
  title,

  // type control
  sourceType,
  setSourceType,

  // text
  textValue,
  setTextValue,

  // url
  urlValue,
  setUrlValue,

  // file
  fileValue,
  setFileValue,

  // ota (NEW)
  otaTargets = [],
  otaValue = "",
  setOtaValue = () => {},
}) {
  const showText = sourceType === "text";
  const showUrl = sourceType === "url";
  const showFile = sourceType === "file";
  const showOta = sourceType === "ota";

  const handleFile = (e) => {
    const f = e.target.files?.[0] || null;
    setFileValue(f);
  };

  const formatOtaOption = (t) => {
    const label =
      t?.name ||
      `${t?.service_id || "service"}:${t?.doc_type || "doc"}`;
    const value = `${t.service_id}:${t.doc_type}`;
    return { label, value };
  };

  const otaOptions = (otaTargets || [])
    .map(formatOtaOption)
    .filter((x) => x.value && x.label);

  return (
    <section className="sp-card">
      <div className="sp-head">
        <div className="sp-title">{title}</div>

        <div className="sp-pills">
          <SelectorPill active={showText} onClick={() => setSourceType("text")}>
            Text
          </SelectorPill>
          <SelectorPill active={showUrl} onClick={() => setSourceType("url")}>
            URL
          </SelectorPill>
          <SelectorPill active={showFile} onClick={() => setSourceType("file")}>
            File
          </SelectorPill>
          <SelectorPill active={showOta} onClick={() => setSourceType("ota")}>
            OTA
          </SelectorPill>
        </div>
      </div>

      <div className="sp-body">
        {showText && (
          <div className="sp-block">
            <label className="sp-label">Paste policy text</label>
            <textarea
              className="sp-textarea"
              value={textValue}
              onChange={(e) => setTextValue(e.target.value)}
              placeholder="Paste the policy content here…"
              rows={10}
            />
          </div>
        )}

        {showUrl && (
          <div className="sp-block">
            <label className="sp-label">Policy URL</label>
            <input
              className="sp-input"
              value={urlValue}
              onChange={(e) => setUrlValue(e.target.value)}
              placeholder="https://…"
            />
            <div className="sp-hint">
              Tip: raw GitHub URLs work great (raw.githubusercontent.com).
            </div>
          </div>
        )}

        {showFile && (
          <div className="sp-block">
            <label className="sp-label">Upload a policy file</label>
            <input
              className="sp-file"
              type="file"
              accept=".txt,.md,.html,.htm,.pdf"
              onChange={handleFile}
            />
            {fileValue && (
              <div className="sp-filemeta">
                <span className="sp-filename">{fileValue.name}</span>
                <span className="sp-filesize">
                  {(fileValue.size / 1024).toFixed(1)} KB
                </span>
              </div>
            )}
            <div className="sp-hint">
              Supports: .txt, .md, .html (PDF is optional depending on backend).
            </div>
          </div>
        )}

        {showOta && (
          <div className="sp-block">
            <label className="sp-label">Open Terms Archive target</label>

            {otaOptions.length === 0 ? (
              <div className="sp-hint">
                Loading OTA targets… (backend: <code>/ota/targets</code>)
              </div>
            ) : (
              <select
                className="sp-select"
                value={otaValue}
                onChange={(e) => setOtaValue(e.target.value)}
              >
                {otaOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            )}

            <div className="sp-hint">
              Uses selector format: <code>service_id:doc_type</code>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
