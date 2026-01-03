(function () {
  try {
    const hostname = window.location.hostname || "";
    chrome.runtime.sendMessage({
      type: "CC_PAGE_HOST",
      hostname
    });
  } catch (e) {
    // silent
  }
})();
