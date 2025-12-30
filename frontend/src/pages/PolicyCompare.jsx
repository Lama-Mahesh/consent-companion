import React, { useEffect, useMemo, useState } from "react";
import { compareIngest, fetchOtaTargets } from "../api/consent";
import SourcePanel from "../components/SourcePanel";
import ResultPanel from "../components/ResultPanel";
import { saveToHistory } from "../store/historyStore";
import "./PolicyCompare.css";

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
    return ok(oldType, oldText, oldUrl, oldFile) && ok(newType, newText, newUrl, newFile);
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

  const onAnalyze = async () => {
    setError("");
    setLoading(true);
    setData(null);

    try {
      const res = await compareIngest(buildFormData());
      // console.log("COMPARE_RESULT:", res); 
      setData(res);
      saveToHistory(res, {
        title: "Policy Compare Result",
        source: res?.source,
        mode: res?.engine?.mode,
        service_id: res?.service_id,
        doc_type: res?.doc_type,
      });
      if (mode === "semantic" && localStorage.getItem("cc_model_loaded") !== "1") {
        localStorage.setItem("cc_model_loaded", "1");
        setFirstSemanticNoteShown(true);
    }

      // console.log("HISTORY_AFTER_SAVE:", localStorage.getItem("cc_history_v1"));

    } catch (e) {
      // console.error("SAVE_HISTORY_FAILED:", e);
      setError(e.message || "Unknown error");
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
