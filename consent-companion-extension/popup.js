// popup.js

const DEFAULT_WEB_UI = "http://localhost:5173"; // Vite default
const DEFAULT_BACKEND = "http://localhost:8000"; // display/help only

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

async function requestBackgroundCheck(tabId) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "CC_CHECK_NOW", tabId }, () => resolve(true));
  });
}

async function isReachable(baseUrl) {
  const base = normalizeBase(baseUrl);
  if (!base) return false;
  try {
    const res = await fetch(base, { method: "GET" });
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

// Watch helpers (talk to background)
async function getWatchStatus(service_id, doc_type) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: "CC_WATCH_STATUS", service_id, doc_type }, (resp) => {
      resolve(resp || { ok: false, watched: false });
    });
  });
}

async function addWatch(service_id, doc_type, name, last_diff_at) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      { type: "CC_WATCH_ADD", service_id, doc_type, name, last_diff_at },
      (resp) => resolve(resp || { ok: false })
    );
  });
}

async function removeWatch(service_id, doc_type) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(
      { type: "CC_WATCH_REMOVE", service_id, doc_type },
      (resp) => resolve(resp || { ok: false })
    );
  });
}

function buildThemeChangesList(themeSummary) {
  const out = [];
  if (!themeSummary || !Array.isArray(themeSummary.top_themes)) return out;

  themeSummary.top_themes.slice(0, 3).forEach((th) => {
    const name = th?.theme || "Theme";
    const count = Number(th?.count || 0);
    out.push(`${name}: ${count} change(s)`);

    const items = Array.isArray(th?.top_items) ? th.top_items : [];
    items.slice(0, 3).forEach((it) => {
      const exp = (it?.explanation || it?.category || "").trim();
      if (exp) out.push(`• ${exp}`);
    });
  });

  return out;
}

(async function init() {
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

  const watchBtn = document.getElementById("cc-watch");

  domainEl.textContent = "—";
  statusEl.textContent = "Checking…";
  summaryEl.textContent = "";
  changesSec.style.display = "none";
  actionsSec.style.display = "none";
  clearList(changesEl);
  clearList(actionsEl);
  hideError(errEl);

  if (watchBtn) {
    watchBtn.style.display = "none";
    watchBtn.disabled = true;
    watchBtn.textContent = "Watch";
  }

  const tab = await getActiveTab();
  if (!tab?.id) {
    statusEl.textContent = "No active tab";
    return;
  }

  let data = await chrome.storage.session.get([tabKey(tab.id)]);
  let result = data[tabKey(tab.id)];

  if (!result) {
    await requestBackgroundCheck(tab.id);
    data = await chrome.storage.session.get([tabKey(tab.id)]);
    result = data[tabKey(tab.id)];
  }

  if (!result) {
    statusEl.textContent = "Checking…";
    summaryEl.textContent = "Try re-opening the popup in a moment.";
    return;
  }

  domainEl.textContent = result.domain || "—";

  if (!result.ok) {
    statusEl.textContent = "Couldn’t check policy";
    summaryEl.textContent = "";
    showError(errEl, result.error || "Unknown error");

    openBtn.disabled = true;
    openBtn.title = "No details available until backend check succeeds";

    if (watchBtn) watchBtn.style.display = "none";
    return;
  }

  statusEl.textContent = prettyStatus(result.status);
  summaryEl.textContent = result.summary ? String(result.summary) : "";

  // ✅ Prefer theme_summary if present, fallback to old changes list
  const themeList = buildThemeChangesList(result.theme_summary);
  const changesToShow = themeList.length ? themeList : (Array.isArray(result.changes) ? result.changes : []);

  if (Array.isArray(changesToShow) && changesToShow.length) {
    changesSec.style.display = "block";
    renderList(changesEl, changesToShow);
  }

  if (Array.isArray(result.actions) && result.actions.length) {
    actionsSec.style.display = "block";
    renderList(actionsEl, result.actions);
  }

  // Open details
  const { webUi } = await getSettings();
  const webUiBase = normalizeBase(webUi);

  openBtn.disabled = false;
  openBtn.title = "";

  openBtn.addEventListener("click", async () => {
    hideError(errEl);

    const sid = result.service_id || "";
    const dt = result.doc_type || "";
    const ch = Number.isInteger(result.top_change_index) ? result.top_change_index : null;

    const path =
      result.detail_url ||
      `/ota-cache?service_id=${encodeURIComponent(sid)}&doc_type=${encodeURIComponent(dt)}${
        ch != null ? `&change=${encodeURIComponent(String(ch))}` : ""
      }`;

    if (/^https?:\/\//i.test(path)) {
      await chrome.tabs.create({ url: path });
      return;
    }

    const url = webUiBase + path;

    const ok = await isReachable(webUiBase);
    if (!ok) {
      showError(errEl, `Details UI is not reachable at ${webUiBase}. Start your React UI or change cc_web_ui.`);
      return;
    }

    await chrome.tabs.create({ url });
  });

  // Watch button
  const sid = result.service_id || "";
  const dt = result.doc_type || "";
  const name = result.service_id || result.domain || "Site";

  if (watchBtn && sid && dt) {
    watchBtn.style.display = "inline-block";
    watchBtn.disabled = false;

    const refreshWatchLabel = async () => {
      const s = await getWatchStatus(sid, dt);
      watchBtn.dataset.watched = s?.watched ? "1" : "0";
      watchBtn.textContent = s?.watched ? "Unwatch" : "Watch this site";
    };

    await refreshWatchLabel();

    watchBtn.addEventListener("click", async () => {
      hideError(errEl);
      watchBtn.disabled = true;

      try {
        const watched = watchBtn.dataset.watched === "1";
        if (!watched) {
          const resp = await addWatch(sid, dt, name, result.last_diff_at || result.last_changed || null);
          if (!resp?.ok) throw new Error(resp?.error || "Failed to add watch");
        } else {
          const resp = await removeWatch(sid, dt);
          if (!resp?.ok) throw new Error(resp?.error || "Failed to remove watch");
        }

        await refreshWatchLabel();
      } catch (e) {
        showError(errEl, e?.message || "Watch action failed");
      } finally {
        watchBtn.disabled = false;
      }
    });
  }

  // Settings placeholder
  settingsBtn.addEventListener("click", () => {
    showError(
      errEl,
      `Settings not wired yet. Current defaults: Web UI ${normalizeBase(DEFAULT_WEB_UI)} | Backend ${normalizeBase(DEFAULT_BACKEND)}`
    );
  });
})();
