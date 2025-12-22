from __future__ import annotations

from typing import Optional, Dict, Any, List, Literal

import traceback
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# IMPORTANT:
# Run from project root:
#   uvicorn backend.api_main:app --host 127.0.0.1 --port 8000 --reload
#
# Ensure:
#   backend/__init__.py exists

from . import consent_core

from .policy_loader import (
    load_from_url,
    load_from_file_bytes,
    load_from_text,
    load_pair,
    load_from_ota_target,
    parse_ota_selector,
)

# Optional rolling cache endpoint support (keep if you have cache_store.py)
try:
    from .cache_store import get_cache_paths, read_json
    _CACHE_OK = True
except Exception:
    _CACHE_OK = False


# ----------------------------
# Pydantic models
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
    OR
      - {"service_id":"chatgpt","doc_type":"privacy_policy"}  (as string JSON if used in form)
    """
    old_ota: str
    new_ota: str
    mode: Mode = "semantic"
    max_changes: Optional[int] = Field(default=50, ge=1, le=500)


# ----------------------------
# FastAPI app
# ----------------------------

app = FastAPI(
    title="Consent Companion API",
    description="Policy change analysis engine (Consent Companion)",
    version="1.2.0",
)

# CORS – allow any origin (tighten for production)
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
        "version": "1.2.0",
        "engine_default_model": "all-MiniLM-L6-v2",
        "cache_enabled": _CACHE_OK,
    }


@app.get("/cache/{service_id}/{doc_type}/last-diff")
def get_last_diff(service_id: str, doc_type: str):
    if not _CACHE_OK:
        raise HTTPException(status_code=501, detail="cache_store not available in this build.")
    paths = get_cache_paths(service_id, doc_type)
    data = read_json(paths.last_diff)
    if not data:
        raise HTTPException(status_code=404, detail="No cached diff yet. Run sync first.")
    return data


# ----------------------------
# Engine runner
# ----------------------------

def _format_response(
    *,
    mode: str,
    formatted_changes: List[Dict[str, Any]],
    old_meta: Optional[Dict[str, Any]] = None,
    new_meta: Optional[Dict[str, Any]] = None,
    service_id: Optional[str] = None,
    doc_type: Optional[str] = None,
    source: str = "api",
    old_version: Optional[str] = None,
    new_version: Optional[str] = None,
) -> Dict[str, Any]:
    return {
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
            "old_meta": old_meta or {},
            "new_meta": new_meta or {},
        },
        "changes": formatted_changes,
    }


def _run_engine_texts(
    *,
    old_text: str,
    new_text: str,
    mode: str,
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

    if not old_text or not new_text:
        return _format_response(
            mode=mode,
            formatted_changes=[],
            old_meta=old_meta,
            new_meta=new_meta,
            service_id=service_id,
            doc_type=doc_type,
            source=source,
            old_version=old_version,
            new_version=new_version,
        )

    if mode not in ("basic", "semantic"):
        raise HTTPException(status_code=400, detail={"error": "mode must be 'basic' or 'semantic'."})

    max_changes = max(1, min(int(max_changes), 500))

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
            old_meta=old_meta,
            new_meta=new_meta,
            service_id=service_id,
            doc_type=doc_type,
            source=source,
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
        old_meta=old_meta,
        new_meta=new_meta,
        service_id=service_id,
        doc_type=doc_type,
        source=source,
        old_version=old_version,
        new_version=new_version,
    )


# ----------------------------
# Endpoints
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
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "trace": traceback.format_exc()})


@app.post("/compare/ota")
async def compare_ota(req: CompareOtaRequest) -> Dict[str, Any]:
    """
    Compare two OTA targets.
    Example payload:
      {
        "old_ota": "chatgpt:privacy_policy",
        "new_ota": "chatgpt:privacy_policy",
        "mode": "semantic",
        "max_changes": 50
      }
    """
    try:
        old_service_id, old_doc_type = parse_ota_selector(req.old_ota)
        new_service_id, new_doc_type = parse_ota_selector(req.new_ota)

        # Usually service/doc_type will be same, but allow different in case you want it.
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
    Unified ingestion endpoint (best for frontend):
    Provide EXACTLY ONE of (text, url, file, ota) for OLD
    Provide EXACTLY ONE of (text, url, file, ota) for NEW

    OTA format:
      old_ota="chatgpt:privacy_policy"
      new_ota="chatgpt:privacy_policy"
    """
    try:
        # Convert UploadFile -> (bytes, filename) tuples for load_pair
        old_file_tuple: Optional[tuple[bytes, str]] = None
        new_file_tuple: Optional[tuple[bytes, str]] = None

        if old_file is not None:
            old_file_tuple = (await old_file.read(), old_file.filename or "old.txt")
        if new_file is not None:
            new_file_tuple = (await new_file.read(), new_file.filename or "new.txt")

        # If OTA is used, load those directly (so we can keep meta clean)
        if old_ota and new_ota:
            old_service_id, old_doc_type = parse_ota_selector(old_ota)
            new_service_id, new_doc_type = parse_ota_selector(new_ota)

            old_loaded = load_from_ota_target(service_id=old_service_id, doc_type=old_doc_type)
            new_loaded = load_from_ota_target(service_id=new_service_id, doc_type=new_doc_type)

            return _run_engine_texts(
                old_text=old_loaded.text,
                new_text=new_loaded.text,
                mode=mode,
                max_changes=max_changes,
                old_meta=old_loaded.meta,
                new_meta=new_loaded.meta,
                service_id=new_service_id,
                doc_type=new_doc_type,
                source="ota",
            )

        # Otherwise: reuse your existing load_pair (text/url/file)
        old_loaded, new_loaded = load_pair(
            old_text=old_text,
            new_text=new_text,
            old_url=old_url,
            new_url=new_url,
            old_file=old_file_tuple,
            new_file=new_file_tuple,
        )

        return _run_engine_texts(
            old_text=old_loaded.text,
            new_text=new_loaded.text,
            mode=mode,
            max_changes=max_changes,
            old_meta=old_loaded.meta,
            new_meta=new_loaded.meta,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail={"error": str(ve)})
    except (KeyError, FileNotFoundError) as ve:
        raise HTTPException(status_code=400, detail={"error": str(ve)})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "trace": traceback.format_exc()})


# Optional: local debug
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.api_main:app", host="127.0.0.1", port=8000, reload=True)
