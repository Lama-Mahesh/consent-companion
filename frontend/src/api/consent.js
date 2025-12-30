// src/api/consent.js
import { apiGet, apiPostForm } from "./client";

/**
 * Unified ingest endpoint (text/url/file/ota)
 * POST /compare/ingest (multipart/form-data)
 */
export async function compareIngest(formData) {
  return apiPostForm("/compare/ingest", formData);
}

/**
 * Load OTA targets for dropdown
 * GET /ota/targets
 */
export async function fetchOtaTargets() {
  return apiGet("/ota/targets");
}

/**
 * Load rolling cache history for a target
 * GET /cache/{service_id}/{doc_type}/history
 */
export async function fetchCacheHistory(serviceId, docType) {
  return apiGet(`/cache/${encodeURIComponent(serviceId)}/${encodeURIComponent(docType)}/history`);
}


// Optional helpers (nice to have)
export function compareText({ old_text, new_text, mode = "semantic", max_changes = 50 }) {
  return apiPostJson("/compare", { old_text, new_text, mode, max_changes });
}

export function compareUrl({ old_url, new_url, mode = "semantic", max_changes = 50 }) {
  return apiPostJson("/compare/url", { old_url, new_url, mode, max_changes });
}
