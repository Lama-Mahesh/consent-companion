const KEY = "cc_history_v1";
const MAX_ITEMS = 50;

function safeParse(s, fallback) {
  try {
    return JSON.parse(s);
  } catch {
    return fallback;
  }
}

export function loadHistory() {
  const v = safeParse(localStorage.getItem(KEY) || "[]", []);
  return Array.isArray(v) ? v : [];
}


export function getHistoryItem(id) {
  return loadHistory().find((x) => x.id === id) || null;
}

export function clearHistory() {
  localStorage.removeItem(KEY);
}

export function removeHistoryItem(id) {
  const next = loadHistory().filter((x) => x.id !== id);
  localStorage.setItem(KEY, JSON.stringify(next));
  return next;
}

export function updateHistoryItem(id, patch) {
  const all = loadHistory();
  const next = all.map((x) => (x.id === id ? { ...x, ...patch } : x));
  localStorage.setItem(KEY, JSON.stringify(next));
  return next;
}

function stripLargeFields(result) {
  // ✅ safe deep clone fallback
  const clean = JSON.parse(JSON.stringify(result || {}));

  const MAX_SNIPPET = 1200;

  if (Array.isArray(clean?.changes)) {
    clean.changes = clean.changes.map((ch) => {
      const oldStr = (ch?.old ?? "").toString();
      const newStr = (ch?.new ?? "").toString();
      return {
        ...ch,
        old: oldStr.length > MAX_SNIPPET ? oldStr.slice(0, MAX_SNIPPET) + "…" : ch.old,
        new: newStr.length > MAX_SNIPPET ? newStr.slice(0, MAX_SNIPPET) + "…" : ch.new,
      };
    });
  }

  return clean;
}


export function saveToHistory(result, meta = {}) {
  const all = loadHistory();

  const liteResult = stripLargeFields(result);

  // derive max risk for filtering
  const maxRisk = Array.isArray(liteResult?.changes)
    ? Math.max(0, ...liteResult.changes.map((c) => Number(c.risk_score ?? 0)))
    : 0;

  const entry = {
    id: liteResult?.request_id || crypto.randomUUID(),
    created_at: liteResult?.generated_at || new Date().toISOString(),
    pinned: false,

    title: meta.title || "Policy Compare Result",
    source: liteResult?.source || meta.source || "api",
    mode: liteResult?.engine?.mode || meta.mode || "semantic",
    service_id: liteResult?.service_id ?? meta.service_id ?? null,
    doc_type: liteResult?.doc_type ?? meta.doc_type ?? null,
    num_changes: liteResult?.engine?.num_changes ?? (liteResult?.changes?.length || 0),
    max_risk: maxRisk,

    // ✅ store lite result
    result: liteResult,
  };

  // newest first, but pinned will be sorted in UI later
  const next = [entry, ...all].slice(0, MAX_ITEMS);
  localStorage.setItem(KEY, JSON.stringify(next));
  return entry;
}
