// popup.js (drop-in replacement)

const DEFAULT_WEB_UI = "http://localhost:5173"; // Vite default
const DEFAULT_BACKEND = "http://localhost:8000"; // only used for display/help (not required)

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab || null;
}

function tabKey(tabId) {
  return `cc_tab_${tabId}`;
}

function normalizeBase(url) {
  return String(url || "").trim().replace(/\/$/, "");
}

function prettyStatus(status) {
  if (status === "none") return "No important changes detected ✅";
  if (status === "minor") return "Policy updated (minor) 🟡";
  if (status === "important") return "Important policy update 🔴";
  return "Status unknown";
}

async function getSettings() {
  const data = await chrome.storage.sync.get(["cc_web_ui"]);
  return { webUi: data.cc_web_ui || DEFAULT_WEB_UI };
}

function clearList(el) {
  if (el) el.innerHTML = "";
}

function renderList(el, items) {
  clearList(el);

  const arr = Array.isArray(items) ? items : [];
  arr.slice(0, 5).forEach((x) => {
    const li = document.createElement("li");
    li.textContent = String(x);
    el.appendChild(li);
  });
}

/**
 * Ask background worker to fetch /extension/check for the active tab.
 * This preserves your architecture: popup never calls backend directly.
 */
async function requestBackgroundCheck(tabId) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "CC_CHECK_NOW", tabId }, () => resolve(true));
  });
}

/**
 * Optional: check if a base URL is reachable.
 * We keep this VERY lightweight: a normal GET to the base.
 * If it fails, we show an error and don’t open a dead page.
 */
async function isReachable(baseUrl) {
  const base = normalizeBase(baseUrl);
  if (!base) return false;

  try {
    const res = await fetch(base, { method: "GET" });
    // Any response means host is reachable (even 404 is fine)
    return !!res;
  } catch {
    return false;
  }
}

function showError(errEl, msg) {
  if (!errEl) return;
  errEl.style.display = "block";
  errEl.textContent = msg || "Unknown error";
}

function hideError(errEl) {
  if (!errEl) return;
  errEl.style.display = "none";
  errEl.textContent = "";
}

(async function init() {
  // --- DOM refs ---
  const domainEl = document.getElementById("cc-domain");
  const statusEl = document.getElementById("cc-status");
  const summaryEl = document.getElementById("cc-summary");

  const changesSec = document.getElementById("cc-changes-section");
  const actionsSec = document.getElementById("cc-actions-section");
  const changesEl = document.getElementById("cc-changes");
  const actionsEl = document.getElementById("cc-actions");

  const errEl = document.getElementById("cc-error");

  const openBtn = document.getElementById("cc-open-details");
  const settingsBtn = document.getElementById("cc-settings");

  // --- initial UI reset ---
  domainEl.textContent = "—";
  statusEl.textContent = "Checking…";
  summaryEl.textContent = "";
  changesSec.style.display = "none";
  actionsSec.style.display = "none";
  clearList(changesEl);
  clearList(actionsEl);
  hideError(errEl);

  // --- active tab ---
  const tab = await getActiveTab();
  if (!tab?.id) {
    statusEl.textContent = "No active tab";
    return;
  }

  // --- attempt cached result first ---
  let data = await chrome.storage.session.get([tabKey(tab.id)]);
  let result = data[tabKey(tab.id)];

  // --- if not present, force refresh once ---
  if (!result) {
    await requestBackgroundCheck(tab.id);
    data = await chrome.storage.session.get([tabKey(tab.id)]);
    result = data[tabKey(tab.id)];
  }

  // --- still not present: show gentle message ---
  if (!result) {
    statusEl.textContent = "Checking…";
    summaryEl.textContent = "Try re-opening the popup in a moment.";
    return;
  }

  // --- render domain ---
  domainEl.textContent = result.domain || "—";

  // --- handle backend/worker errors ---
  if (!result.ok) {
    statusEl.textContent = "Couldn’t check policy";
    summaryEl.textContent = "";

    // Make 404 misconfiguration obvious (matches our background.js change)
    const msg = result.error || "Unknown error";
    showError(errEl, msg);

    // Disable open details because data is unreliable
    openBtn.disabled = true;
    openBtn.title = "No details available until backend check succeeds";
    return;
  }

  // --- render status + summary ---
  statusEl.textContent = prettyStatus(result.status);
  summaryEl.textContent = result.summary ? String(result.summary) : "";

  // --- render changes/actions ---
  if (Array.isArray(result.changes) && result.changes.length) {
    changesSec.style.display = "block";
    renderList(changesEl, result.changes);
  }

  if (Array.isArray(result.actions) && result.actions.length) {
    actionsSec.style.display = "block";
    renderList(actionsEl, result.actions);
  }

  // --- Open details ---
  const { webUi } = await getSettings();
  const webUiBase = normalizeBase(webUi);

  openBtn.disabled = false;
  openBtn.title = "";

  openBtn.addEventListener("click", async () => {
    hideError(errEl);

    // Build path from backend result
    const path =
      result.detail_url ||
      `/ota-cache?service_id=${encodeURIComponent(result.service_id || "")}&doc_type=${encodeURIComponent(
        result.doc_type || ""
      )}`;

    // If path is absolute (http...), open as-is
    if (/^https?:\/\//i.test(path)) {
      await chrome.tabs.create({ url: path });
      return;
    }

    // Otherwise, it’s a route on your React UI
    const url = webUiBase + path;

    // Prevent opening dead page (common during dev)
    const ok = await isReachable(webUiBase);
    if (!ok) {
      showError(
        errEl,
        `Details UI is not reachable at ${webUiBase}. Start your React UI (likely Vite) or change cc_web_ui.`
      );
      return;
    }

    await chrome.tabs.create({ url });
  });

  // --- Settings placeholder (safe) ---
  settingsBtn.addEventListener("click", () => {
    showError(
      errEl,
      `Settings not wired yet. Current defaults: Web UI ${normalizeBase(DEFAULT_WEB_UI)} | Backend ${normalizeBase(
        DEFAULT_BACKEND
      )}`
    );
  });
})();
