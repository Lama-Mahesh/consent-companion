import React, { useEffect, useMemo, useState } from "react";
import { compareIngest, fetchOtaTargets } from "../api/consent";
import SourcePanel from "../components/SourcePanel";
import ResultPanel from "../components/ResultPanel";
import { saveToHistory } from "../store/historyStore";
import "./PolicyCompare.css";

const DEFAULT_API_BASE = "http://127.0.0.1:8000";

// tries to match your extension behavior
function getApiBase() {
  const v =
    localStorage.getItem("cc_api_base") ||
    localStorage.getItem("CC_API_BASE") ||
    DEFAULT_API_BASE;
  return String(v || DEFAULT_API_BASE).replace(/\/$/, "");
}

async function readFileAsText(file, maxChars = 250000) {
  if (!file) return "";
  const text = await new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result || ""));
    fr.onerror = () => reject(new Error("Failed to read file"));
    fr.readAsText(file);
  });
  if (text.length > maxChars) {
    return (
      text.slice(0, maxChars) +
      "\n\n[Truncated for history storage]\n"
    );
  }
  return text;
}

async function fetchUrlTextViaBackend(urlToLoad) {
  const apiBase = getApiBase();
  const endpoint = `${apiBase}/load/url?url=${encodeURIComponent(urlToLoad)}`;
  const res = await fetch(endpoint);
  if (!res.ok) throw new Error(`Failed to load URL policy (${res.status})`);
  const payload = await res.json();
  return String(payload?.text || "");
}

function parseOtaSelector(sel) {
  const s = String(sel || "").trim();
  const [service_id, doc_type] = s.split(":");
  if (!service_id || !doc_type) return null;
  return { service_id, doc_type };
}

async function fetchCachedPolicyText(service_id, doc_type, version) {
  const apiBase = getApiBase();
  const endpoint =
    `${apiBase}/cache/${encodeURIComponent(service_id)}/${encodeURIComponent(
      doc_type
    )}/policy?version=${encodeURIComponent(version)}`;

  const res = await fetch(endpoint);
  if (!res.ok) throw new Error(`Failed to load cached policy (${res.status})`);
  const payload = await res.json();
  return String(payload?.text || "");
}

async function fetchOtaOldText(otaSelector) {
  // Old = previous (fallback to latest)
  const parsed = parseOtaSelector(otaSelector);
  if (!parsed) return "";
  try {
    return await fetchCachedPolicyText(parsed.service_id, parsed.doc_type, "previous");
  } catch {
    return await fetchCachedPolicyText(parsed.service_id, parsed.doc_type, "latest");
  }
}

async function fetchOtaNewText(otaSelector) {
  // New = latest
  const parsed = parseOtaSelector(otaSelector);
  if (!parsed) return "";
  return await fetchCachedPolicyText(parsed.service_id, parsed.doc_type, "latest");
}

export default function PolicyCompare() {
  const [mode, setMode] = useState("semantic");
  const [maxChanges, setMaxChanges] = useState(50);

  // OTA
  const [otaTargets, setOtaTargets] = useState([]);
  const [oldOta, setOldOta] = useState("");
  const [newOta, setNewOta] = useState("");

  // OLD
  const [oldType, setOldType] = useState("text");
  const [oldText, setOldText] = useState("");
  const [oldUrl, setOldUrl] = useState("");
  const [oldFile, setOldFile] = useState(null);

  // NEW
  const [newType, setNewType] = useState("text");
  const [newText, setNewText] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [newFile, setNewFile] = useState(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);

  const [firstSemanticNoteShown, setFirstSemanticNoteShown] = useState(
    () => localStorage.getItem("cc_model_loaded") === "1"
  );

  useEffect(() => {
    (async () => {
      const t = await fetchOtaTargets();
      setOtaTargets(t || []);
      if (t?.length) {
        const first = `${t[0].service_id}:${t[0].doc_type}`;
        setOldOta(first);
        setNewOta(first);
      }
    })();
  }, []);

  const canRun = useMemo(() => {
    const ok = (type, text, url, file) => {
      if (type === "text") return text.trim().length > 0;
      if (type === "url") return url.trim().length > 0;
      if (type === "file") return !!file;
      if (type === "ota") return true;
      return false;
    };
    return (
      ok(oldType, oldText, oldUrl, oldFile) &&
      ok(newType, newText, newUrl, newFile)
    );
  }, [oldType, oldText, oldUrl, oldFile, newType, newText, newUrl, newFile]);

  const buildFormData = () => {
    const fd = new FormData();
    fd.append("mode", mode);
    fd.append("max_changes", String(maxChanges));

    if (oldType === "text") fd.append("old_text", oldText);
    if (oldType === "url") fd.append("old_url", oldUrl);
    if (oldType === "file" && oldFile) fd.append("old_file", oldFile);
    if (oldType === "ota") fd.append("old_ota", oldOta);

    if (newType === "text") fd.append("new_text", newText);
    if (newType === "url") fd.append("new_url", newUrl);
    if (newType === "file" && newFile) fd.append("new_file", newFile);
    if (newType === "ota") fd.append("new_ota", newOta);

    return fd;
  };

  function buildTitle() {
    const label = (t, url, file, ota) => {
      if (t === "text") return "Text";
      if (t === "url") return "URL";
      if (t === "file") return file?.name || "File";
      if (t === "ota") return ota || "OTA";
      return "Source";
    };
    return `Policy compare • ${label(oldType, oldUrl, oldFile, oldOta)} → ${label(
      newType,
      newUrl,
      newFile,
      newOta
    )}`;
  }

  const onAnalyze = async () => {
    setError("");
    setLoading(true);
    setData(null);

    try {
      // ✅ Create stored copies of what we compared (for HistoryDetail)
      // OLD
      let oldStoredText = "";
      if (oldType === "text") oldStoredText = oldText;
      else if (oldType === "file") oldStoredText = await readFileAsText(oldFile);
      else if (oldType === "url") oldStoredText = await fetchUrlTextViaBackend(oldUrl);
      else if (oldType === "ota") oldStoredText = await fetchOtaOldText(oldOta);

      // NEW
      let newStoredText = "";
      if (newType === "text") newStoredText = newText;
      else if (newType === "file") newStoredText = await readFileAsText(newFile);
      else if (newType === "url") newStoredText = await fetchUrlTextViaBackend(newUrl);
      else if (newType === "ota") newStoredText = await fetchOtaNewText(newOta);

      // Run compare
      const res = await compareIngest(buildFormData());
      setData(res);

      const changes = Array.isArray(res?.changes) ? res.changes : [];
      const maxRisk =
        changes.length > 0
          ? Math.max(...changes.map((c) => Number(c?.risk_score || 0)))
          : 0;

      // ✅ sources now ALWAYS include text (when possible)
      const historySources = {
        old: {
          type: oldType,
          text: oldStoredText || undefined,
          url: oldType === "url" ? oldUrl : undefined,
          ota: oldType === "ota" ? oldOta : undefined,
          file_name: oldType === "file" ? (oldFile?.name || null) : undefined,
        },
        new: {
          type: newType,
          text: newStoredText || undefined,
          url: newType === "url" ? newUrl : undefined,
          ota: newType === "ota" ? newOta : undefined,
          file_name: newType === "file" ? (newFile?.name || null) : undefined,
        },
      };

      saveToHistory({
        title: buildTitle(),
        mode: res?.engine?.mode || mode,
        service_id: res?.service_id || null,
        doc_type: res?.doc_type || null,
        source: res?.source || "api",
        max_risk: maxRisk,
        num_changes: res?.engine?.num_changes ?? changes.length ?? 0,
        result: res,
        sources: historySources,
      });

      if (mode === "semantic" && localStorage.getItem("cc_model_loaded") !== "1") {
        localStorage.setItem("cc_model_loaded", "1");
        setFirstSemanticNoteShown(true);
      }
    } catch (e) {
      setError(e?.message || "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="pc-page">
      <header className="pc-header">
        <div>
          <div className="pc-title">Consent Companion</div>
          <div className="pc-subtitle">Compare privacy policies</div>
        </div>

        <div className="pc-controls">
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="semantic">semantic</option>
            <option value="basic">basic</option>
          </select>

          <input
            type="number"
            min={1}
            max={500}
            value={maxChanges}
            onChange={(e) => setMaxChanges(Number(e.target.value))}
          />

          <button onClick={onAnalyze} disabled={!canRun || loading}>
            {loading ? "Analyzing…" : "Analyze"}
          </button>
        </div>
      </header>

      <main className="pc-grid">
        <div className="pc-left">
          <SourcePanel
            title="Old policy"
            sourceType={oldType}
            setSourceType={setOldType}
            textValue={oldText}
            setTextValue={setOldText}
            urlValue={oldUrl}
            setUrlValue={setOldUrl}
            fileValue={oldFile}
            setFileValue={setOldFile}
            otaTargets={otaTargets}
            otaValue={oldOta}
            setOtaValue={setOldOta}
          />

          <SourcePanel
            title="New policy"
            sourceType={newType}
            setSourceType={setNewType}
            textValue={newText}
            setTextValue={setNewText}
            urlValue={newUrl}
            setUrlValue={setNewUrl}
            fileValue={newFile}
            setFileValue={setNewFile}
            otaTargets={otaTargets}
            otaValue={newOta}
            setOtaValue={setNewOta}
          />
        </div>

        <div className="pc-right">
          <ResultPanel data={data} loading={loading} error={error} />
        </div>
      </main>

      <footer className="pc-foot">
        Backend: <code>/compare/ingest</code>
        {mode === "semantic" && !firstSemanticNoteShown && (
          <> • First semantic run may take longer (model loads once).</>
        )}
      </footer>
    </div>
  );
}
