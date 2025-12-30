import React, { useEffect, useState } from "react";
import { fetchCacheHistory } from "../api/consent";

export default function DiffHistory({ selector }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selector) return;
    const [serviceId, docType] = selector.split(":");
    (async () => {
      try {
        setErr("");
        setLoading(true);
        const res = await fetchCacheHistory(serviceId, docType);
        setData(res);
      } catch (e) {
        setData(null);
        setErr(e.message || "No history");
      } finally {
        setLoading(false);
      }
    })();
  }, [selector]);

  if (!selector) return null;

  return (
    <div className="cc-card">
      <div className="cc-card-title">History (rolling cache)</div>

      {loading ? <div className="cc-muted">Loading…</div> : null}
      {err ? <div className="cc-error">{err}</div> : null}

      {data?.latest ? (
        <div className="cc-grid2">
          <div>
            <div className="cc-k">Latest fetched</div>
            <div className="cc-v">{data.latest.fetched_at || "-"}</div>
            <div className="cc-k">Latest hash</div>
            <div className="cc-v mono">{data.latest.content_sha256?.slice(0, 16)}…</div>
          </div>
          <div>
            <div className="cc-k">Previous fetched</div>
            <div className="cc-v">{data.previous?.fetched_at || "-"}</div>
            <div className="cc-k">Previous hash</div>
            <div className="cc-v mono">{data.previous?.content_sha256?.slice(0, 16) || "-"}…</div>
          </div>
        </div>
      ) : null}

      {data?.last_diff ? (
        <div className="cc-muted" style={{ marginTop: 10 }}>
          Last diff: {data.last_diff.generated_at || "-"} • Changes:{" "}
          {data.last_diff.engine?.num_changes ?? "-"}
        </div>
      ) : (
        <div className="cc-muted" style={{ marginTop: 10 }}>
          No last_diff.json yet (run nightly sync once).
        </div>
      )}
    </div>
  );
}
