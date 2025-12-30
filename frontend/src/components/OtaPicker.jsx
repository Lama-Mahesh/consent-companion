import React, { useEffect, useMemo, useState } from "react";
import { fetchOtaTargets } from "../api/consent";

export default function OtaPicker({ value, onChange }) {
  const [targets, setTargets] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setLoading(true);
        const t = await fetchOtaTargets();
        setTargets(Array.isArray(t) ? t : []);
      } catch (e) {
        setErr(e.message || "Failed to load OTA targets");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const options = useMemo(() => {
    return targets
      .map((t) => ({
        key: `${t.service_id}:${t.doc_type}`,
        label: t.name || `${t.service_id} (${t.doc_type})`,
        service_id: t.service_id,
        doc_type: t.doc_type,
      }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [targets]);

  return (
    <div className="cc-field">
      <label className="cc-label">OTA target</label>
      {loading ? (
        <div className="cc-muted">Loading OTA targets…</div>
      ) : err ? (
        <div className="cc-error">{err}</div>
      ) : (
        <select
          className="cc-select"
          value={value || ""}
          onChange={(e) => onChange?.(e.target.value)}
        >
          <option value="">Select a service…</option>
          {options.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
