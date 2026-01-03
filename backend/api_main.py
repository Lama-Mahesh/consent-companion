# backend/api_main.py
from __future__ import annotations

from typing import Optional, Dict, Any, List, Literal, Tuple
from pathlib import Path
import json
import traceback
import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import consent_core
from .provenance import utc_now_iso, input_provenance
from .policy_loader import (
    load_from_url,
    load_from_file_bytes,
    load_pair,
    load_from_ota_target,
    parse_ota_selector,
)

# ----------------------------
# Types / Models
# ----------------------------

Mode = Literal["basic", "semantic"]


class CompareRequest(BaseModel):
    old_text: str = Field(..., description="Old policy text")
    new_text: str = Field(..., description="New policy text")
    mode: Mode = Field(default="semantic", description="basic or semantic")
    max_changes: Optional[int] = Field(default=50, ge=1, le=500)


class CompareUrlRequest(BaseModel):
    old_url: str
    new_url: str
    mode: Mode = "semantic"
    max_changes: Optional[int] = Field(default=50, ge=1, le=500)


class CompareOtaRequest(BaseModel):
    """
    OTA selector format:
      - "chatgpt:privacy_policy"
    """
    old_ota: str
    new_ota: str
    mode: Mode = "semantic"
    max_changes: Optional[int] = Field(default=50, ge=1, le=500)


# ----------------------------
# App
# ----------------------------

app = FastAPI(
    title="Consent Companion API",
    description="Policy change analysis engine (Consent Companion)",
    version="1.2.1",
)

# CORS – open for dev; tighten later for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/ping")
def ping():
    return {"status": "ok"}


@app.get("/version")
def version():
    return {
        "api": "Consent Companion API",
        "version": "1.2.1",
        "engine_default_model": "all-MiniLM-L6-v2",
        "ota_targets_path": str(_default_targets_path()),
        "cache_dir": str(_cache_base()),
    }


# ----------------------------
# Paths (project layout)
# ----------------------------

def _project_root() -> Path:
    # backend/api_main.py -> project root
    return Path(__file__).resolve().parents[1]


def _default_targets_path() -> Path:
    # backend/api_main.py -> project root -> sources/ota_targets.json
    return _project_root() / "sources" / "ota_targets.json"


def _cache_base() -> Path:
    # matches your GitHub Action env: CACHE_DIR=data/cache
    return _project_root() / "data" / "cache"


# ----------------------------
# Cache endpoints (rolling cache)
# ----------------------------

@app.get("/ota/targets")
def ota_targets():
    """
    Returns the raw list from sources/ota_targets.json for the UI dropdown.
    """
    p = _default_targets_path()
    if not p.exists():
        raise HTTPException(status_code=404, detail={"error": f"ota_targets.json not found at: {p}"})
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("ota_targets.json must be a JSON list")
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": f"Failed to read ota_targets.json: {e}"})


@app.get("/cache/{service_id}/{doc_type}/history")
def cache_history(service_id: str, doc_type: str):
    """
    Reads rolling cache produced by ota_sync:
      data/cache/<service_id>/<doc_type>/{latest,previous,last_diff}.json
    """
    base = _cache_base() / service_id / doc_type
    latest = base / "latest.json"
    previous = base / "previous.json"
    last_diff = base / "last_diff.json"

    def read_if_exists(fp: Path):
        if not fp.exists():
            return None
        return json.loads(fp.read_text(encoding="utf-8"))

    out = {
        "service_id": service_id,
        "doc_type": doc_type,
        "latest": read_if_exists(latest),
        "previous": read_if_exists(previous),
        "last_diff": read_if_exists(last_diff),
    }
    if not out["latest"] and not out["previous"] and not out["last_diff"]:
        raise HTTPException(status_code=404, detail={"error": "No cache found for this target yet."})
    return out

PolicyVersion = Literal["latest", "previous"]

@app.get("/cache/{service_id}/{doc_type}/policy")
def cache_policy(service_id: str, doc_type: str, version: PolicyVersion = "latest"):
    """
    Return cached policy text for a target.
    version=latest|previous
    """
    base = _cache_base() / service_id / doc_type

    file_map = {
        "latest": base / "latest.json",
        "previous": base / "previous.json",
    }
    fp = file_map[version]

    if not fp.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No {version}.json found for {service_id}/{doc_type}. Run OTA sync first.",
        )

    obj = json.loads(fp.read_text(encoding="utf-8"))

    # Keep response clean + useful for UI
    return {
        "service_id": service_id,
        "doc_type": doc_type,
        "version": version,
        "name": obj.get("name"),
        "fetched_at": obj.get("fetched_at"),
        "content_sha256": obj.get("content_sha256"),
        "source": obj.get("source"),
        "meta": obj.get("meta", {}),
        "text": obj.get("text", ""),
    }


@app.get("/cache/{service_id}/{doc_type}/last-diff")
def cache_last_diff(service_id: str, doc_type: str):
    """
    Convenience endpoint to fetch only last_diff.json.
    """
    fp = _cache_base() / service_id / doc_type / "last_diff.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail={"error": "No cached diff yet. Run sync first."})
    return json.loads(fp.read_text(encoding="utf-8"))


# ----------------------------
# Extension endpoint (minimal, no ML)
# ----------------------------

from urllib.parse import urlparse

def _normalize_domain(domain: str) -> str:
    d = (domain or "").strip().lower()
    if d.startswith("www."):
        d = d[4:]
    return d

def _guess_service_id_from_domain(domain: str) -> str:
    """
    Minimal mapping:
      facebook.com -> facebook
      amazon.com -> amazon
      bbc.co.uk -> bbc   (not perfect, but acceptable for baby-step #2)
    """
    d = _normalize_domain(domain)
    if not d:
        return ""
    parts = d.split(".")
    if len(parts) >= 2:
        return parts[-2]  # "amazon" from "amazon.com"
    return parts[0]

def _impact_from_risk(max_risk: float, num_changes: int) -> str:
    """
    Keep aligned with your React UI heuristics (OtaCache.jsx):
      risk >= 3  => high / important
      risk >= 2  => medium / minor
      else       => none (unless there are changes, then minor)
    """
    if max_risk >= 3:
        return "important"
    if max_risk >= 2:
        return "minor"
    if num_changes > 0:
        return "minor"
    return "none"


@app.get("/extension/check")
def extension_check(domain: str):
    """
    Minimal extension endpoint.
    - NO ML
    - Reads your OTA rolling cache only
    - Returns: important | minor | none
    """
    domain_n = _normalize_domain(domain)
    if not domain_n:
        raise HTTPException(status_code=400, detail={"error": "domain is required"})

    # Load OTA targets
    try:
        targets = json.loads(_default_targets_path().read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": f"Failed to load ota_targets.json: {e}"})

    # Map domain -> service_id (baby-step mapping)
    service_guess = _guess_service_id_from_domain(domain_n)

    # Find a matching OTA target (prefer privacy_policy)
    target = None
    for t in targets:
        if t.get("service_id") == service_guess and t.get("doc_type") == "privacy_policy":
            target = t
            break

    # If site not tracked, DO NOT 404 — return "none"
    if not target:
        return {
            "domain": domain_n,
            "status": "none",
            "label": "Not tracked yet",
            "summary": "This site is not in the monitored OTA target list.",
            "last_changed": None,
            "service_id": None,
            "doc_type": None,
            "changes": [],
            "actions": [],
            "detail_url": None,
        }

    service_id = target["service_id"]
    doc_type = target["doc_type"]

    diff_path = _cache_base() / service_id / doc_type / "last_diff.json"

    # If tracked but no diff yet, return none (still not 404)
    if not diff_path.exists():
        return {
            "domain": domain_n,
            "status": "none",
            "label": "No cached diff yet",
            "summary": "Run the OTA sync to generate last_diff.json for this target.",
            "last_changed": None,
            "service_id": service_id,
            "doc_type": doc_type,
            "changes": [],
            "actions": [],
            "detail_url": f"/ota-cache?service_id={service_id}&doc_type={doc_type}",
        }

    try:
        diff_obj = json.loads(diff_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": f"Failed to read last_diff.json: {e}"})

    changes = diff_obj.get("changes") if isinstance(diff_obj.get("changes"), list) else []
    max_risk = 0.0
    if changes:
        try:
            max_risk = max(float(c.get("risk_score", 0.0) or 0.0) for c in changes)
        except Exception:
            max_risk = 0.0

    status = _impact_from_risk(max_risk, len(changes))

    LABELS = {
        "important": "Important policy update",
        "minor": "Minor policy update",
        "none": "No meaningful changes",
    }

    # A short, human-friendly summary from top change
    top = changes[0] if changes else {}
    summary = (top.get("explanation") or top.get("category") or "No differences detected.").strip()

    # keep popup payload small
    def _dedupe_keep_order(items: list[str]) -> list[str]:
        seen = set()
        out = []
        for x in items:
            if not x:
                continue
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    popup_changes_raw = []
    popup_actions_raw = []

    for c in changes[:10]:  # read a bit more, then dedupe down
        exp = (c.get("explanation") or c.get("category") or "").strip()
        act = (c.get("suggested_action") or "").strip()
        if exp:
            popup_changes_raw.append(exp)
        if act:
            popup_actions_raw.append(act)

    popup_changes = _dedupe_keep_order(popup_changes_raw)[:5]
    popup_actions = _dedupe_keep_order(popup_actions_raw)[:5]


    last_changed = (diff_obj.get("generated_at") or diff_obj.get("provenance", {}).get("new", {}).get("fetched_at"))

    return {
        "domain": domain_n,
        "status": status,                     # important | minor | none
        "label": LABELS.get(status, "Status unknown"),
        "summary": summary,
        "last_changed": last_changed,
        "service_id": service_id,
        "doc_type": doc_type,
        "changes": popup_changes,
        "actions": popup_actions,
        "detail_url": f"/ota-cache?service_id={service_id}&doc_type={doc_type}",
    }


# ----------------------------
# Engine runner
# ----------------------------

def _format_response(
    *,
    mode: str,
    formatted_changes: List[Dict[str, Any]],
    old_text: str,
    new_text: str,
    old_meta: Optional[Dict[str, Any]] = None,
    new_meta: Optional[Dict[str, Any]] = None,
    source: str = "api",
    service_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    old_version: Optional[str] = None,
    new_version: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "request_id": str(uuid.uuid4()),
        "generated_at": utc_now_iso(),
        "service_id": service_id,
        "doc_type": doc_type,
        "source": source,
        "old_version": old_version,
        "new_version": new_version,
        "engine": {
            "mode": mode,
            "model_name": "all-MiniLM-L6-v2" if mode == "semantic" else None,
            "num_changes": len(formatted_changes),
        },
        "inputs": {
            "old": input_provenance(old_text, old_meta),
            "new": input_provenance(new_text, new_meta),
        },
        "changes": formatted_changes,
    }


def _run_engine_texts(
    *,
    old_text: str,
    new_text: str,
    mode: Mode,
    max_changes: int,
    old_meta: Optional[Dict[str, Any]] = None,
    new_meta: Optional[Dict[str, Any]] = None,
    service_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    source: str = "api",
    old_version: Optional[str] = None,
    new_version: Optional[str] = None,
) -> Dict[str, Any]:
    old_text = (old_text or "").strip()
    new_text = (new_text or "").strip()

    if mode not in ("basic", "semantic"):
        raise HTTPException(status_code=400, detail={"error": "mode must be 'basic' or 'semantic'."})

    max_changes = max(1, min(int(max_changes), 500))

    # If empty inputs -> still return provenance payload
    if not old_text or not new_text:
        return _format_response(
            mode=mode,
            formatted_changes=[],
            old_text=old_text,
            new_text=new_text,
            old_meta=old_meta,
            new_meta=new_meta,
            source=source,
            service_id=service_id,
            doc_type=doc_type,
            old_version=old_version,
            new_version=new_version,
        )

    if mode == "basic":
        changes = consent_core.analyze_policy_change_basic(old_text, new_text)
        formatted: List[Dict[str, Any]] = []
        for ch in changes:
            formatted.append({
                "category": ch.get("category"),
                "type": "modified",
                "risk_score": ch.get("risk_score", 1.0),
                "line_number": ch.get("line_number"),
                "old": ch.get("old"),
                "new": ch.get("new"),
                "explanation": ch.get("explanation"),
                "suggested_action": ch.get("suggested_action"),
            })
        formatted = formatted[:max_changes]
        return _format_response(
            mode="basic",
            formatted_changes=formatted,
            old_text=old_text,
            new_text=new_text,
            old_meta=old_meta,
            new_meta=new_meta,
            source=source,
            service_id=service_id,
            doc_type=doc_type,
            old_version=old_version,
            new_version=new_version,
        )

    # semantic
    changes_raw = consent_core.analyze_policy_change_semantic(old_text, new_text, model=None)
    formatted: List[Dict[str, Any]] = []
    for ch in changes_raw:
        formatted.append({
            "category": ch.get("category"),
            "type": ch.get("type"),
            "risk_score": ch.get("risk_score", 0.0),
            "similarity": ch.get("similarity"),
            "old_index": ch.get("old_index"),
            "new_index": ch.get("new_index"),
            "old": ch.get("old"),
            "new": ch.get("new"),
            "explanation": ch.get("explanation"),
            "suggested_action": ch.get("suggested_action"),
        })
    formatted = formatted[:max_changes]
    return _format_response(
        mode="semantic",
        formatted_changes=formatted,
        old_text=old_text,
        new_text=new_text,
        old_meta=old_meta,
        new_meta=new_meta,
        source=source,
        service_id=service_id,
        doc_type=doc_type,
        old_version=old_version,
        new_version=new_version,
    )


# ----------------------------
# Endpoints: text / url / file / ota / ingest
# ----------------------------

@app.post("/compare")
async def compare(req: CompareRequest) -> Dict[str, Any]:
    """Compare two raw texts."""
    try:
        return _run_engine_texts(
            old_text=req.old_text,
            new_text=req.new_text,
            mode=req.mode,
            max_changes=req.max_changes or 50,
            source="api",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "trace": traceback.format_exc()})


@app.post("/compare/url")
async def compare_url(req: CompareUrlRequest) -> Dict[str, Any]:
    """Compare two URLs (HTML or text). Extracts readable text via policy_loader."""
    try:
        old_loaded = load_from_url(req.old_url)
        new_loaded = load_from_url(req.new_url)

        return _run_engine_texts(
            old_text=old_loaded.text,
            new_text=new_loaded.text,
            mode=req.mode,
            max_changes=req.max_changes or 50,
            old_meta=old_loaded.meta,
            new_meta=new_loaded.meta,
            source="url",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "trace": traceback.format_exc()})


@app.post("/compare/file")
async def compare_file(
    old_file: UploadFile = File(...),
    new_file: UploadFile = File(...),
    mode: Mode = Form("semantic"),
    max_changes: int = Form(50),
) -> Dict[str, Any]:
    """Compare two uploaded files (txt/html/md supported)."""
    try:
        old_bytes = await old_file.read()
        new_bytes = await new_file.read()

        old_loaded = load_from_file_bytes(old_bytes, old_file.filename or "old.txt")
        new_loaded = load_from_file_bytes(new_bytes, new_file.filename or "new.txt")

        return _run_engine_texts(
            old_text=old_loaded.text,
            new_text=new_loaded.text,
            mode=mode,
            max_changes=max_changes,
            old_meta=old_loaded.meta,
            new_meta=new_loaded.meta,
            source="file",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "trace": traceback.format_exc()})


@app.post("/compare/ota")
async def compare_ota(req: CompareOtaRequest) -> Dict[str, Any]:
    """
    Compare two OTA targets (as selectors like "chatgpt:privacy_policy").
    """
    try:
        old_service_id, old_doc_type = parse_ota_selector(req.old_ota)
        new_service_id, new_doc_type = parse_ota_selector(req.new_ota)

        old_loaded = load_from_ota_target(service_id=old_service_id, doc_type=old_doc_type)
        new_loaded = load_from_ota_target(service_id=new_service_id, doc_type=new_doc_type)

        return _run_engine_texts(
            old_text=old_loaded.text,
            new_text=new_loaded.text,
            mode=req.mode,
            max_changes=req.max_changes or 50,
            old_meta=old_loaded.meta,
            new_meta=new_loaded.meta,
            service_id=new_service_id,
            doc_type=new_doc_type,
            source="ota",
        )
    except (ValueError, KeyError, FileNotFoundError) as ve:
        raise HTTPException(status_code=400, detail={"error": str(ve)})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "trace": traceback.format_exc()})


@app.post("/compare/ingest")
async def compare_ingest(
    # OLD side (choose exactly one: text/url/file/ota)
    old_text: Optional[str] = Form(None),
    old_url: Optional[str] = Form(None),
    old_ota: Optional[str] = Form(None),
    old_file: Optional[UploadFile] = File(None),

    # NEW side (choose exactly one: text/url/file/ota)
    new_text: Optional[str] = Form(None),
    new_url: Optional[str] = Form(None),
    new_ota: Optional[str] = Form(None),
    new_file: Optional[UploadFile] = File(None),

    mode: Mode = Form("semantic"),
    max_changes: int = Form(50),
) -> Dict[str, Any]:
    """
    Unified ingestion endpoint (best for frontend).

    Provide EXACTLY ONE of (text, url, file, ota) for OLD
    Provide EXACTLY ONE of (text, url, file, ota) for NEW

    OTA selector example:
      old_ota="chatgpt:privacy_policy"
      new_ota="chatgpt:privacy_policy"
    """
    try:
        # Count sources per side
        def nonempty_str(s: Optional[str]) -> bool:
            return bool(s and s.strip())

        def chosen_count(text, url, ota, file_obj) -> int:
            return int(nonempty_str(text)) + int(nonempty_str(url)) + int(nonempty_str(ota)) + int(file_obj is not None)

        old_count = chosen_count(old_text, old_url, old_ota, old_file)
        new_count = chosen_count(new_text, new_url, new_ota, new_file)

        if old_count != 1:
            raise HTTPException(status_code=400, detail={"error": "OLD: provide exactly ONE of old_text, old_url, old_ota, old_file."})
        if new_count != 1:
            raise HTTPException(status_code=400, detail={"error": "NEW: provide exactly ONE of new_text, new_url, new_ota, new_file."})

        # If OTA is used on either side, load it directly so meta/source stays correct
        old_loaded_text: str
        new_loaded_text: str
        old_meta: Dict[str, Any] = {}
        new_meta: Dict[str, Any] = {}
        out_source = "api"
        out_service_id: Optional[str] = None
        out_doc_type: Optional[str] = None

        # OLD side
        if nonempty_str(old_ota):
            sid, dtype = parse_ota_selector(old_ota)
            lp = load_from_ota_target(service_id=sid, doc_type=dtype)
            old_loaded_text, old_meta = lp.text, lp.meta
            out_source = "ota"
            out_service_id, out_doc_type = sid, dtype
        elif nonempty_str(old_url):
            lp = load_from_url(old_url)
            old_loaded_text, old_meta = lp.text, lp.meta
            out_source = "url"
        elif old_file is not None:
            b = await old_file.read()
            lp = load_from_file_bytes(b, old_file.filename or "old.txt")
            old_loaded_text, old_meta = lp.text, lp.meta
            out_source = "file"
        else:
            old_loaded_text = (old_text or "")
            old_meta = {"source_type": "text"}

        # NEW side
        if nonempty_str(new_ota):
            sid, dtype = parse_ota_selector(new_ota)
            lp = load_from_ota_target(service_id=sid, doc_type=dtype)
            new_loaded_text, new_meta = lp.text, lp.meta
            out_source = "ota"
            # prefer NEW side identifiers for response
            out_service_id, out_doc_type = sid, dtype
        elif nonempty_str(new_url):
            lp = load_from_url(new_url)
            new_loaded_text, new_meta = lp.text, lp.meta
            out_source = "url" if out_source == "api" else out_source
        elif new_file is not None:
            b = await new_file.read()
            lp = load_from_file_bytes(b, new_file.filename or "new.txt")
            new_loaded_text, new_meta = lp.text, lp.meta
            out_source = "file" if out_source == "api" else out_source
        else:
            new_loaded_text = (new_text or "")
            new_meta = {"source_type": "text"}

        return _run_engine_texts(
            old_text=old_loaded_text,
            new_text=new_loaded_text,
            mode=mode,
            max_changes=max_changes,
            old_meta=old_meta,
            new_meta=new_meta,
            source=out_source,
            service_id=out_service_id,
            doc_type=out_doc_type,
        )

    except HTTPException:
        raise
    except (ValueError, KeyError, FileNotFoundError) as ve:
        raise HTTPException(status_code=400, detail={"error": str(ve)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "trace": traceback.format_exc()})


# Optional: local debug
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.api_main:app", host="127.0.0.1", port=8000, reload=True)
