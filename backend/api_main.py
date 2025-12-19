from __future__ import annotations

from typing import Optional, Dict, Any, List, Literal

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import traceback

# IMPORTANT:
# - Run from project root:
#     uvicorn backend.api_main:app --reload
# - This file assumes backend/ is a Python package (backend/__init__.py exists)

from . import consent_core
from .policy_loader import load_from_url, load_from_file_bytes, load_from_text, load_pair, LoadedPolicy


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


# For /compare/ingest we accept either:
# - old_text OR old_url OR old_file
# - new_text OR new_url OR new_file
#
# We implement this as a multipart/form-data endpoint so files work naturally.
# (Text + URL also work via form fields.)


# ----------------------------
# FastAPI app
# ----------------------------

app = FastAPI(
    title="Consent Companion API",
    description="Policy change analysis engine (Consent Companion)",
    version="1.1.0",
)

# CORS – allow any origin (tighten later for production)
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
        "version": "1.1.0",
        "engine_default_model": "all-MiniLM-L6-v2",
    }


# ----------------------------
# Engine runner
# ----------------------------

def _format_response(
    *,
    mode: str,
    formatted_changes: List[Dict[str, Any]],
    old_meta: Optional[Dict[str, Any]] = None,
    new_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "service_id": None,
        "doc_type": None,
        "source": "api",
        "old_version": None,
        "new_version": None,
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
) -> Dict[str, Any]:
    old_text = (old_text or "").strip()
    new_text = (new_text or "").strip()

    if not old_text or not new_text:
        return _format_response(
            mode=mode,
            formatted_changes=[],
            old_meta=old_meta,
            new_meta=new_meta,
        )

    if mode not in ("basic", "semantic"):
        raise HTTPException(status_code=400, detail={"error": "mode must be 'basic' or 'semantic'."})

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
        )

    # semantic
    changes_raw = consent_core.analyze_policy_change_semantic(old_text, new_text, model=None)
    formatted = []
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
    )


# ----------------------------
# Endpoints
# ----------------------------

@app.post("/compare")
async def compare(req: CompareRequest) -> Dict[str, Any]:
    """
    Compare two raw texts.
    """
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
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "trace": traceback.format_exc()},
        )


@app.post("/compare/url")
async def compare_url(req: CompareUrlRequest) -> Dict[str, Any]:
    """
    Compare two URLs (HTML or text). Extracts readable text via policy_loader.
    """
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
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "trace": traceback.format_exc()},
        )


@app.post("/compare/file")
async def compare_file(
    old_file: UploadFile = File(...),
    new_file: UploadFile = File(...),
    mode: Mode = Form("semantic"),
    max_changes: int = Form(50),
) -> Dict[str, Any]:
    """
    Compare two uploaded files (txt/html/md supported).
    """
    try:
        old_bytes = await old_file.read()
        new_bytes = await new_file.read()

        old_loaded = load_from_file_bytes(old_bytes, old_file.filename or "old.txt")
        new_loaded = load_from_file_bytes(new_bytes, new_file.filename or "new.txt")

        return _run_engine_texts(
            old_text=old_loaded.text,
            new_text=new_loaded.text,
            mode=mode,
            max_changes=max(1, min(int(max_changes), 500)),
            old_meta=old_loaded.meta,
            new_meta=new_loaded.meta,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "trace": traceback.format_exc()},
        )


@app.post("/compare/ingest")
async def compare_ingest(
    # old side (choose exactly one)
    old_text: Optional[str] = Form(None),
    old_url: Optional[str] = Form(None),
    old_file: Optional[UploadFile] = File(None),

    # new side (choose exactly one)
    new_text: Optional[str] = Form(None),
    new_url: Optional[str] = Form(None),
    new_file: Optional[UploadFile] = File(None),

    mode: Mode = Form("semantic"),
    max_changes: int = Form(50),
) -> Dict[str, Any]:
    """
    Unified ingestion endpoint:
    - Provide EXACTLY ONE of (text, url, file) for OLD
    - Provide EXACTLY ONE of (text, url, file) for NEW

    This is the best endpoint for your frontend (single call).
    """
    try:
        # Convert UploadFile -> (bytes, filename) tuples for loader
        old_file_tuple: Optional[tuple[bytes, str]] = None
        new_file_tuple: Optional[tuple[bytes, str]] = None

        if old_file is not None:
            old_file_tuple = (await old_file.read(), old_file.filename or "old.txt")
        if new_file is not None:
            new_file_tuple = (await new_file.read(), new_file.filename or "new.txt")

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
            max_changes=max(1, min(int(max_changes), 500)),
            old_meta=old_loaded.meta,
            new_meta=new_loaded.meta,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail={"error": str(ve)})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "trace": traceback.format_exc()},
        )


# Optional: local debug
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.api_main:app", host="127.0.0.1", port=8000, reload=True)
