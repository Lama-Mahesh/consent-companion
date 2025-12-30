export function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadJson(filename, obj) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
  downloadBlob(filename, blob);
}

function csvEscape(v) {
  const s = (v ?? "").toString();
  const needs = /[",\n\r]/.test(s);
  const escaped = s.replace(/"/g, '""');
  return needs ? `"${escaped}"` : escaped;
}

export function downloadChangesCsv(filename, result) {
  const changes = Array.isArray(result?.changes) ? result.changes : [];
  const header = [
    "index",
    "category",
    "type",
    "risk_score",
    "similarity",
    "old_index",
    "new_index",
    "explanation",
    "suggested_action",
    "old",
    "new",
  ];

  const rows = changes.map((ch, i) => ([
    i + 1,
    ch.category ?? "",
    ch.type ?? "",
    ch.risk_score ?? "",
    ch.similarity ?? "",
    ch.old_index ?? "",
    ch.new_index ?? "",
    ch.explanation ?? "",
    ch.suggested_action ?? "",
    ch.old ?? "",
    ch.new ?? "",
  ]));

  const csv = [
    header.map(csvEscape).join(","),
    ...rows.map((r) => r.map(csvEscape).join(",")),
  ].join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  downloadBlob(filename, blob);
}

function htmlEscape(s) {
  return (s ?? "").toString()
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function riskLabel(score) {
  const n = Number(score ?? 0);
  if (n >= 3) return "High";
  if (n >= 2) return "Medium";
  if (n >= 1) return "Low";
  return "Info";
}

export function downloadHtmlReport(filename, result, opts = {}) {
  const title = opts.title || "Consent Companion — Policy Diff Report";
  const createdAt = result?.generated_at || new Date().toISOString();
  const mode = result?.engine?.mode || "";
  const source = result?.source || "";
  const service = result?.service_id || "";
  const docType = result?.doc_type || "";
  const reqId = result?.request_id || "";
  const changes = Array.isArray(result?.changes) ? result.changes : [];

  const rows = changes.map((ch, idx) => {
    const risk = Number(ch.risk_score ?? 0);
    const label = riskLabel(risk);

    return `
      <div class="card">
        <div class="card-head">
          <div>
            <div class="cat">${htmlEscape(ch.category || "Uncategorized")}</div>
            <div class="meta">
              <span class="pill ${label.toLowerCase()}">${label} • ${risk.toFixed(1)}</span>
              <span class="pill">${htmlEscape(ch.type || "")}</span>
              ${typeof ch.similarity === "number" ? `<span class="pill">Sim • ${ch.similarity.toFixed(2)}</span>` : ""}
            </div>
          </div>
          <div class="idx">#${idx + 1}</div>
        </div>

        <div class="explain">${htmlEscape(ch.explanation || "")}</div>
        <div class="action"><b>Suggested action:</b> ${htmlEscape(ch.suggested_action || "")}</div>

        <div class="diff">
          <div>
            <div class="label">Old</div>
            <pre>${htmlEscape(ch.old || "")}</pre>
          </div>
          <div>
            <div class="label">New</div>
            <pre>${htmlEscape(ch.new || "")}</pre>
          </div>
        </div>
      </div>
    `;
  }).join("\n");

  const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>${htmlEscape(title)}</title>
  <style>
    :root { --bg:#0b0f17; --card:#111827; --muted:#9ca3af; --text:#e5e7eb; --border:#1f2937; }
    body { margin:0; font-family: ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial; background:var(--bg); color:var(--text); }
    .wrap { max-width: 1040px; margin: 0 auto; padding: 28px 16px 60px; }
    .top { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom: 18px; }
    h1 { font-size: 22px; margin:0 0 6px; }
    .sub { color: var(--muted); font-size: 13px; line-height: 1.4; }
    .grid { display:grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
    .kv { border:1px solid var(--border); border-radius: 12px; padding: 10px 12px; background: rgba(255,255,255,0.02); }
    .k { color: var(--muted); font-size: 12px; }
    .v { font-size: 13px; margin-top: 2px; word-break: break-word; }
    .card { border:1px solid var(--border); border-radius: 14px; padding: 14px; margin-top: 12px; background: var(--card); }
    .card-head { display:flex; justify-content:space-between; gap: 10px; }
    .cat { font-size: 15px; font-weight: 650; margin-bottom: 6px; }
    .meta { display:flex; flex-wrap:wrap; gap: 6px; }
    .pill { font-size: 12px; border:1px solid var(--border); padding: 3px 8px; border-radius: 999px; color: var(--text); background: rgba(255,255,255,0.02); }
    .pill.high { border-color: rgba(239,68,68,0.4); }
    .pill.medium { border-color: rgba(245,158,11,0.4); }
    .pill.low { border-color: rgba(34,197,94,0.35); }
    .idx { color: var(--muted); font-size: 12px; align-self:flex-start; }
    .explain { margin-top: 10px; color: var(--text); font-size: 13px; }
    .action { margin-top: 8px; color: var(--text); font-size: 13px; }
    .diff { display:grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
    .label { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
    pre { margin:0; padding: 10px; border-radius: 10px; background: rgba(255,255,255,0.03); border: 1px solid var(--border); overflow:auto; white-space: pre-wrap; word-break: break-word; font-size: 12px; line-height: 1.35; }
    .footer { margin-top: 18px; color: var(--muted); font-size: 12px; }
    @media (max-width: 860px) { .diff { grid-template-columns: 1fr; } .top { flex-direction: column; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1>${htmlEscape(title)}</h1>
        <div class="sub">
          Generated ${htmlEscape(createdAt)} • ${htmlEscape(mode)} • ${htmlEscape(source)}
        </div>
      </div>
      <div class="sub">${htmlEscape(service)}${service && docType ? " • " : ""}${htmlEscape(docType)}</div>
    </div>

    <div class="grid">
      <div class="kv"><div class="k">Request ID</div><div class="v">${htmlEscape(reqId)}</div></div>
      <div class="kv"><div class="k">Total Changes</div><div class="v">${changes.length}</div></div>
    </div>

    ${rows || `<div class="card"><div class="explain">No differences detected.</div></div>`}

    <div class="footer">Consent Companion • Exported HTML report (shareable, no print required)</div>
  </div>
</body>
</html>`;

  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  downloadBlob(filename, blob);
}
