import React, { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ResultPanel from "../components/ResultPanel";
import { getHistoryItem } from "../store/historyStore";
import { downloadJson } from "../utils/download";
import "./HistoryDetail.css";

export default function HistoryDetail() {
  const nav = useNavigate();
  const { id } = useParams();

  const item = useMemo(() => getHistoryItem(id), [id]);

  if (!item) {
    return (
      <div style={{ padding: 24, textAlign: "left" }}>
        <button onClick={() => nav("/history")}>← Back</button>
        <h2>Not found</h2>
        <p>This history item doesn’t exist on this browser (deleted or cleared).</p>
      </div>
    );
  }

  const result = item.result;

  return (
    <div className="hd-page">
      <header className="hd-header">
        <div>
          <button className="hd-back" onClick={() => nav("/history")}>
            ← Back
          </button>

          <div className="hd-title">{item.title}</div>

          <div className="hd-sub">
            {new Date(item.created_at).toLocaleString()} • {item.mode} •{" "}
            {item.service_id || item.source}
            {item.doc_type ? ` • ${item.doc_type}` : ""}
            {" • "}
            {item.num_changes} changes
          </div>

          <div className="hd-sub" style={{ marginTop: 6 }}>
            <strong>Request:</strong> {result?.request_id} &nbsp; • &nbsp;
            <strong>Generated:</strong> {result?.generated_at} &nbsp; • &nbsp;
            <strong>Max risk:</strong> {item.max_risk ?? 0}
          </div>
        </div>

        {/* <div className="hd-actions">
          <button
            className="hd-btn"
            onClick={() => downloadJson(`consent-companion-${item.id}.json`, result)}
          >
            Download JSON
          </button>
        </div> */}
      </header>

      <div className="hd-body">
        <ResultPanel data={result} loading={false} error={""} showMeta={false} />
      </div>
    </div>
  );
}
