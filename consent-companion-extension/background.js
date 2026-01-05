// background.js 

const DEFAULT_API_BASE = "http://localhost:8000";

// Alarm config
const ALARM_NAME = "cc_watchlist_poll";
const ALARM_PERIOD_MIN = 30;

// Badge mapping
const STATUS_TO_BADGE = {
  none: { text: "✓" },
  minor: { text: "•" },
  important: { text: "!" },
  unknown: { text: "?" }
};

// -------------------------
// Small in-memory throttle/cache
// -------------------------
const DOMAIN_COOLDOWN_MS = 20 * 1000; // don’t re-hit backend too frequently per domain
const _domainLastFetch = new Map();   // domain -> timestamp (ms)

// OnUpdated debounce per tab
const TAB_DEBOUNCE_MS = 800;
const _tabTimers = new Map(); // tabId -> timer

// Track notification->detail link so click opens the page
const _notifToUrl = new Map(); // notifId -> absolute url

// -------------------------
// Helpers
// -------------------------

function normalizeDomain(hostname) {
  const h = String(hostname || "").toLowerCase().trim();
  if (!h) return "";
  return h.startsWith("www.") ? h.slice(4) : h;
}

function isWebUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

function domainFromUrl(url) {
  try {
    const u = new URL(url);
    return normalizeDomain(u.hostname);
  } catch {
    return "";
  }
}

async function getApiBase() {
  const { cc_api_base } = await chrome.storage.sync.get(["cc_api_base"]);
  return cc_api_base || DEFAULT_API_BASE;
}

function tabKey(tabId) {
  return `cc_tab_${tabId}`;
}

async function storeTabResult(tabId, result) {
  await chrome.storage.session.set({ [tabKey(tabId)]: result });
}

function shouldSkipDomain(domain) {
  if (!domain) return true;
  if (domain.includes("chrome-extension")) return true;
  return false;
}

function shouldSkipUrl(url) {
  if (!url) return true;
  // skip non-web URLs
  if (!isWebUrl(url)) return true;

  // additional chrome/edge/internal safety (in case URL parsing fails)
  const low = String(url).toLowerCase();
  if (low.startsWith("chrome://") || low.startsWith("edge://") || low.startsWith("about:")) return true;
  if (low.startsWith("file://")) return true;

  return false;
}

async function setBadgeForTab(tabId, status) {
  const s = STATUS_TO_BADGE[status] ? status : "unknown";
  await chrome.action.setBadgeText({ tabId, text: STATUS_TO_BADGE[s].text });

  if (s === "none") {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#1f9d55" });
  } else if (s === "minor") {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#b7791f" });
  } else if (s === "important") {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#e53e3e" });
  } else {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#718096" });
  }
}

function nowIso() {
  return new Date().toISOString();
}

function cooldownOk(domain) {
  const last = _domainLastFetch.get(domain);
  const now = Date.now();
  if (!last) return true;
  return (now - last) >= DOMAIN_COOLDOWN_MS;
}

function markFetched(domain) {
  _domainLastFetch.set(domain, Date.now());
}

/**
 * GET /extension/check?domain=example.com
 */
async function fetchSiteStatus(domain) {
  const apiBase = await getApiBase();
  const url = `${apiBase.replace(/\/$/, "")}/extension/check?domain=${encodeURIComponent(domain)}`;

  let res;
  try {
    res = await fetch(url, { method: "GET" });
  } catch (e) {
    throw new Error("Backend unreachable");
  }

  if (res.status === 404) {
    throw new Error("Backend misconfigured: /extension/check not found");
  }
  if (!res.ok) {
    throw new Error(`Backend error (${res.status})`);
  }
  return await res.json();
}

async function handleDomainForTab(domain, tabId, opts = {}) {
  if (!domain || !tabId) return;
  if (shouldSkipDomain(domain)) return;

  const force = Boolean(opts.force);

  // throttle
  if (!force && !cooldownOk(domain)) {
    // still restore existing badge from session if possible
    const data = await chrome.storage.session.get([tabKey(tabId)]);
    const result = data[tabKey(tabId)];
    if (result?.ok && result?.status) {
      await setBadgeForTab(tabId, result.status);
    }
    return;
  }

  try {
    markFetched(domain);

    const result = await fetchSiteStatus(domain);

    await storeTabResult(tabId, {
      ok: true,
      domain,
      fetched_at: nowIso(),
      ...result
    });

    await setBadgeForTab(tabId, result.status || "unknown");
  } catch (e) {
    await storeTabResult(tabId, {
      ok: false,
      domain,
      fetched_at: nowIso(),
      error: e?.message || "Failed to check policy status"
    });

    await setBadgeForTab(tabId, "unknown");
  }
}

async function handleTabById(tabId, opts = {}) {
  let tab;
  try {
    tab = await chrome.tabs.get(tabId);
  } catch {
    return;
  }
  const url = tab?.url;
  if (!url || shouldSkipUrl(url)) return;

  const domain = domainFromUrl(url);
  if (!domain) return;

  await handleDomainForTab(domain, tabId, opts);
}

// -------------------------
// Watchlist storage helpers
// -------------------------

async function getWatchlist() {
  const { cc_watchlist } = await chrome.storage.sync.get(["cc_watchlist"]);
  return Array.isArray(cc_watchlist) ? cc_watchlist : [];
}

async function setWatchlist(list) {
  await chrome.storage.sync.set({ cc_watchlist: list });
}

async function getSeenMap() {
  const { cc_seen_map } = await chrome.storage.local.get(["cc_seen_map"]);
  return cc_seen_map && typeof cc_seen_map === "object" ? cc_seen_map : {};
}

async function setSeenMap(map) {
  await chrome.storage.local.set({ cc_seen_map: map });
}

// -------------------------
// Proactive updates polling
// POST /extension/updates
// -------------------------

async function fetchWatchlistUpdates(targets, seenMap) {
  const apiBase = await getApiBase();
  const url = `${apiBase.replace(/\/$/, "")}/extension/updates`;

  let res;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targets, seen_map: seenMap })
    });
  } catch {
    throw new Error("Backend unreachable");
  }

  if (res.status === 404) {
    throw new Error("Backend misconfigured: /extension/updates not found");
  }
  if (!res.ok) {
    throw new Error(`Backend error (${res.status})`);
  }
  return await res.json();
}

function makeNotificationId(sid, dt, ts) {
  return `cc_${sid}_${dt}_${ts}`.replace(/[^\w\-]/g, "_");
}

function absolutizeDetailUrl(apiBase, detailUrl) {
  if (!detailUrl) return null;
  // if backend already returns absolute URL, keep it
  if (/^https?:\/\//i.test(detailUrl)) return detailUrl;
  // otherwise prefix api base (same server hosting /ota-cache)
  return `${apiBase.replace(/\/$/, "")}${detailUrl.startsWith("/") ? "" : "/"}${detailUrl}`;
}

async function notifyUpdate(hit) {
  const title = hit.status === "important" ? "Important policy update" : "Policy update";
  const serviceName = hit.name || hit.service_id || "Unknown service";
  const docType = hit.doc_type || "policy";
  const summary = hit.summary || "Policy changed.";
  const message = `${serviceName} (${docType})\n${summary}`;

  const notifId = makeNotificationId(hit.service_id || "svc", hit.doc_type || "doc", Date.now());

  // store click URL
  try {
    const apiBase = await getApiBase();
    const abs = absolutizeDetailUrl(apiBase, hit.detail_url);
    if (abs) _notifToUrl.set(notifId, abs);
  } catch {
    // ignore
  }

  await chrome.notifications.create(notifId, {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message,
    priority: hit.status === "important" ? 2 : 1
  });
}

async function pollWatchlistOnce() {
  const targets = await getWatchlist();
  if (!targets.length) return;

  const seenMap = await getSeenMap();

  let payload;
  try {
    payload = await fetchWatchlistUpdates(targets, seenMap);
  } catch {
    // silently fail (don’t annoy user)
    return;
  }

  const updates = Array.isArray(payload?.updates) ? payload.updates : [];
  if (!updates.length) return;

  const newSeen = { ...seenMap };

  for (const hit of updates) {
    await notifyUpdate(hit);

    const key = `${hit.service_id}:${hit.doc_type}`;
    if (hit.last_diff_at) newSeen[key] = hit.last_diff_at;
    else if (hit.last_changed) newSeen[key] = hit.last_changed;
    else newSeen[key] = nowIso();
  }

  await setSeenMap(newSeen);
}

// -------------------------
// Alarm lifecycle
// -------------------------

async function ensureAlarm() {
  const alarms = await chrome.alarms.getAll();
  const exists = alarms.some((a) => a.name === ALARM_NAME);

  // To be safe, recreate alarm if period differs
  if (exists) {
    const alarm = alarms.find((a) => a.name === ALARM_NAME);
    const period = alarm?.periodInMinutes;
    if (period !== ALARM_PERIOD_MIN) {
      chrome.alarms.clear(ALARM_NAME);
      chrome.alarms.create(ALARM_NAME, { periodInMinutes: ALARM_PERIOD_MIN });
    }
    return;
  }

  chrome.alarms.create(ALARM_NAME, { periodInMinutes: ALARM_PERIOD_MIN });
}

chrome.runtime.onInstalled.addListener(() => {
  ensureAlarm();
});

chrome.runtime.onStartup.addListener(() => {
  ensureAlarm();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    pollWatchlistOnce();
  }
});

// -------------------------
// Notifications: click opens detail page
// -------------------------
chrome.notifications.onClicked.addListener(async (notificationId) => {
  const url = _notifToUrl.get(notificationId);
  if (url) {
    chrome.tabs.create({ url });
    _notifToUrl.delete(notificationId);
  }
});

chrome.notifications.onClosed.addListener((notificationId) => {
  _notifToUrl.delete(notificationId);
});

// -------------------------
// Existing reactive behaviour
// -------------------------

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const data = await chrome.storage.session.get([tabKey(tabId)]);
  const result = data[tabKey(tabId)];
  if (result?.ok && result?.status) {
    await setBadgeForTab(tabId, result.status);
  } else {
    await setBadgeForTab(tabId, "unknown");
  }
  handleTabById(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  // only when page finished loading
  if (changeInfo.status !== "complete") return;
  const url = tab?.url;

  // debounced to avoid double-hit on redirects
  if (_tabTimers.has(tabId)) clearTimeout(_tabTimers.get(tabId));
  const timer = setTimeout(() => {
    _tabTimers.delete(tabId);
    if (!url || shouldSkipUrl(url)) return;
    handleTabById(tabId);
  }, TAB_DEBOUNCE_MS);

  _tabTimers.set(tabId, timer);
});

// -------------------------
// Messages from popup/content
// -------------------------

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "CC_PAGE_HOST") {
    const tabId = sender?.tab?.id;
    const domain = normalizeDomain(msg?.hostname);
    handleDomainForTab(domain, tabId);
    sendResponse?.({ ok: true });
    return true;
  }

  if (msg?.type === "CC_CHECK_NOW") {
    const tabId = msg?.tabId;
    handleTabById(tabId, { force: true }).then(() => sendResponse?.({ ok: true }));
    return true;
  }

  // Watchlist operations (popup)
  if (msg?.type === "CC_WATCH_ADD") {
    (async () => {
      const { service_id, doc_type, name } = msg || {};
      if (!service_id || !doc_type) return sendResponse?.({ ok: false, error: "missing target" });

      const list = await getWatchlist();
      const key = `${service_id}:${doc_type}`;
      const exists = list.some((x) => `${x.service_id}:${x.doc_type}` === key);
      if (!exists) {
        list.push({ service_id, doc_type, name: name || service_id });
        await setWatchlist(list);
      }

      // Set baseline immediately so you only notify on NEW future diffs
      const seen = await getSeenMap();
      if (!seen[key]) {
        const baseline = msg?.last_diff_at || nowIso();
        seen[key] = baseline;
        await setSeenMap(seen);
      }

      sendResponse?.({ ok: true, watched: true });
    })();
    return true;
  }

  if (msg?.type === "CC_WATCH_REMOVE") {
    (async () => {
      const { service_id, doc_type } = msg || {};
      if (!service_id || !doc_type) return sendResponse?.({ ok: false, error: "missing target" });

      const key = `${service_id}:${doc_type}`;
      const list = await getWatchlist();
      const next = list.filter((x) => `${x.service_id}:${x.doc_type}` !== key);
      await setWatchlist(next);

      // optional: keep seen_map entry; it prevents re-notify if re-added later
      sendResponse?.({ ok: true, watched: false });
    })();
    return true;
  }

  if (msg?.type === "CC_WATCH_STATUS") {
    (async () => {
      const { service_id, doc_type } = msg || {};
      if (!service_id || !doc_type) return sendResponse?.({ ok: false, error: "missing target" });

      const key = `${service_id}:${doc_type}`;
      const list = await getWatchlist();
      const watched = list.some((x) => `${x.service_id}:${x.doc_type}` === key);

      sendResponse?.({ ok: true, watched });
    })();
    return true;
  }
});
