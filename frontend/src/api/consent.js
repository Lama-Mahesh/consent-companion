// src/api/consent.js
// Central API layer for Consent Companion UI

import { apiGet, apiPostForm, apiPostJson } from "./client";

/**
 * Unified ingest endpoint
 * Supports text / URL / file / OTA targets
 * POST /compare/ingest (multipart/form-data)
 */
export function compareIngest(formData) {
  return apiPostForm("/compare/ingest", formData);
}

/**
 * Load OTA targets (service + doc type)
 * Used to populate dropdowns and feed
 * GET /ota/targets
 */
export function fetchOtaTargets() {
  return apiGet("/ota/targets");
}

/**
 * Load rolling cache history for a specific target
 * Includes latest policy + last diff
 * GET /cache/{service_id}/{doc_type}/history
 */
export function fetchCacheHistory(serviceId, docType) {
  return apiGet(
    `/cache/${encodeURIComponent(serviceId)}/${encodeURIComponent(docType)}/history`
  );
}

/**
 * Fetch cached policy text
 * version = "latest" | "previous"
 * GET /cache/{service_id}/{doc_type}/policy
 */
export function fetchCachePolicy(serviceId, docType, version = "latest") {
  const v = version === "previous" ? "previous" : "latest";
  return apiGet(
    `/cache/${encodeURIComponent(serviceId)}/${encodeURIComponent(docType)}/policy?version=${v}`
  );
}

/**
 * Optional legacy compare helpers
 * Only keep if still used elsewhere in the UI
 */
export function compareText({ old_text, new_text, mode = "semantic", max_changes = 50 }) {
  return apiPostJson("/compare", { old_text, new_text, mode, max_changes });
}

export function compareUrl({ old_url, new_url, mode = "semantic", max_changes = 50 }) {
  return apiPostJson("/compare/url", { old_url, new_url, mode, max_changes });
}
