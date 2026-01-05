// src/store/historyStore.js

const KEY = "cc_history_v1";
const MAX_ITEMS = 30;

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function save(arr) {
  try {
    localStorage.setItem(KEY, JSON.stringify(arr));
  } catch {
    // ignore write failures (quota, private mode, etc.)
  }
}

// ✅ Backwards-compat export (History.jsx expects this)
export function loadHistory() {
  return load();
}

// public (newer names)
export function listHistory() {
  return load();
}

export function getHistoryItem(id) {
  return load().find((x) => String(x.id) === String(id));
}

export function clearHistory() {
  save([]);
}

// "canonical" delete
export function deleteHistoryItem(id) {
  const next = load().filter((x) => String(x.id) !== String(id));
  save(next);
  return next;
}

// ✅ Backwards-compat alias (History.jsx expects this name)
export function removeHistoryItem(id) {
  return deleteHistoryItem(id);
}

// ✅ Update a history entry (used for pin/unpin etc.)
export function updateHistoryItem(id, patch = {}) {
  const arr = load();
  const next = arr.map((x) => {
    if (String(x.id) !== String(id)) return x;
    return { ...x, ...patch };
  });
  save(next);
  return next;
}

/**
 * Save a history snapshot of a diff run.
 *
 * IMPORTANT: `result` returned by the API does NOT include full input texts.
 * If you want "View old/new policy" in HistoryDetail to work for text/url-based
 * compares, pass a `sources` object.
 *
 * sources = {
 *   old: { type: "text"|"url"|"ota"|"file", text?: string, url?: string, ota?: string, file_name?: string },
 *   new: { ... }
 * }
 */
export function saveToHistory({
  title,
  mode,
  service_id,
  doc_type,
  source,
  max_risk,
  num_changes,
  result,
  sources,
}) {
  const nowIso = new Date().toISOString();

  const entry = {
    id: String(Date.now()),
    created_at: nowIso,
    title: title || "Untitled",
    mode: mode || "semantic",

    service_id: service_id || result?.service_id || null,
    doc_type: doc_type || result?.doc_type || null,
    source: source || result?.source || "api",

    max_risk: max_risk ?? null,
    num_changes:
      typeof num_changes === "number"
        ? num_changes
        : (result?.engine?.num_changes ?? 0),

    // optional: keep minimal info to reopen policies inside HistoryDetail
    sources: sources || null,

    // raw API response snapshot
    result: result || null,
  };

  const arr = load();
  const next = [entry, ...arr].slice(0, MAX_ITEMS);
  save(next);

  return entry;
}
