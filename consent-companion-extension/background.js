const DEFAULT_API_BASE = "http://localhost:8000";
// Change later to your deployed backend, e.g. https://api.yourdomain.com

const STATUS_TO_BADGE = {
  none: { text: "✓" },        // green
  minor: { text: "•" },       // amber (less scary than "!")
  important: { text: "!" },   // red
  unknown: { text: "?" }      // gray
};

function normalizeDomain(hostname) {
  const h = String(hostname || "").toLowerCase().trim();
  if (!h) return "";
  return h.startsWith("www.") ? h.slice(4) : h;
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



/**
 * Call your backend:
 * GET /extension/check?domain=example.com
 */
async function fetchSiteStatus(domain) {
  const apiBase = await getApiBase();
  const url = `${apiBase.replace(/\/$/, "")}/extension/check?domain=${encodeURIComponent(domain)}`;
  console.log("[ConsentCompanion] calling:", url);

  const res = await fetch(url, { method: "GET" });

  if (res.status === 404) {
    throw new Error(
      "Backend misconfigured: /extension/check not found (check API base URL / router prefix)"
    );
  }

  if (!res.ok) {
    throw new Error(`Backend error (${res.status})`);
  }

  return await res.json();

}

async function setBadgeForTab(tabId, status) {
  const s = STATUS_TO_BADGE[status] ? status : "unknown";

  await chrome.action.setBadgeText({ tabId, text: STATUS_TO_BADGE[s].text });

  if (s === "none") {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#1f9d55" }); // green
  } else if (s === "minor") {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#b7791f" }); // amber
  } else if (s === "important") {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#e53e3e" }); // red
  } else {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#718096" }); // gray
  }
}

function tabKey(tabId) {
  return `cc_tab_${tabId}`;
}

async function storeTabResult(tabId, result) {
  await chrome.storage.session.set({ [tabKey(tabId)]: result });
}

function shouldSkipDomain(domain) {
  if (!domain) return true;
  // skip internal / odd cases
  if (domain.includes("chrome-extension")) return true;
  return false;
}

async function handleDomainForTab(domain, tabId) {
  if (!domain || !tabId) return;
  if (shouldSkipDomain(domain)) return;

  try {
    const result = await fetchSiteStatus(domain);

    await storeTabResult(tabId, {
      ok: true,
      domain,
      fetched_at: new Date().toISOString(),
      ...result
    });

    await setBadgeForTab(tabId, result.status || "unknown");
  } catch (e) {
    await storeTabResult(tabId, {
      ok: false,
      domain,
      fetched_at: new Date().toISOString(),
      error: e?.message || "Failed to check policy status"
    });

    await setBadgeForTab(tabId, "unknown");
  }
}

async function handleTabById(tabId) {
  const tab = await chrome.tabs.get(tabId);
  if (!tab?.url) return;

  const domain = domainFromUrl(tab.url);
  if (!domain) return;

  await handleDomainForTab(domain, tabId);
}

/** ✅ NEW: check on tab change (no content script needed) */
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  // fast badge: show stored result if exists
  const data = await chrome.storage.session.get([tabKey(tabId)]);
  const result = data[tabKey(tabId)];
  if (result?.ok && result?.status) {
    await setBadgeForTab(tabId, result.status);
  } else {
    await setBadgeForTab(tabId, "unknown");
  }

  // also refresh in background (keeps it current)
  handleTabById(tabId);
});

/** ✅ NEW: check on page load complete */
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "complete") {
    handleTabById(tabId);
  }
});

/**
 * Keep your existing content-script flow for compatibility
 * (so nothing breaks if content.js stays).
 */
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // from content.js
  if (msg?.type === "CC_PAGE_HOST") {
    const tabId = sender?.tab?.id;
    const domain = normalizeDomain(msg?.hostname);
    handleDomainForTab(domain, tabId);
    sendResponse?.({ ok: true });
    return true;
  }

  // ✅ NEW: allow popup to force refresh
  if (msg?.type === "CC_CHECK_NOW") {
    const tabId = msg?.tabId;
    handleTabById(tabId).then(() => sendResponse?.({ ok: true }));
    return true; // async response
  }
});
