from __future__ import annotations

from typing import Optional, Dict, Any, List, Literal, Tuple
from pathlib import Path
import json
import traceback
import uuid
import os
import hashlib
import time
import re

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from dotenv import load_dotenv

load_dotenv()  # reads .env from project root

from . import consent_core
from .provenance import utc_now_iso, input_provenance
from .policy_loader import (
    load_from_url,
    load_from_file_bytes,
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
    old_ota: str
    new_ota: str
    mode: Mode = "semantic"
    max_changes: Optional[int] = Field(default=50, ge=1, le=500)


class WatchTarget(BaseModel):
    service_id: str
    doc_type: str
    name: Optional[str] = None


class UpdatesRequest(BaseModel):
    targets: List[WatchTarget] = Field(default_factory=list)
    seen_map: Dict[str, str] = Field(default_factory=dict)


# ----------------------------
# App
# ----------------------------

app = FastAPI(
    title="Consent Companion API",
    description="Policy change analysis engine (Consent Companion)",
    version="1.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Rate limiting (simple, in-memory)
# ----------------------------

RATE_LIMIT_WINDOW_SEC = int(os.getenv("CC_RATE_LIMIT_WINDOW_SEC", "60"))
RATE_LIMIT_MAX_REQ = int(os.getenv("CC_RATE_LIMIT_MAX_REQ", "120"))
_RL_BUCKET: Dict[str, List[float]] = {}


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    try:
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW_SEC
        bucket = _RL_BUCKET.get(ip, [])
        bucket = [t for t in bucket if t >= window_start]

        if len(bucket) >= RATE_LIMIT_MAX_REQ:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": f"Too many requests. Limit={RATE_LIMIT_MAX_REQ}/{RATE_LIMIT_WINDOW_SEC}s",
                    }
                },
            )

        bucket.append(now)
        _RL_BUCKET[ip] = bucket
    except Exception:
        pass

    return await call_next(request)


# ----------------------------
# Validation helpers
# ----------------------------

_SERVICE_RE = re.compile(r"^[a-z0-9_\-]{1,80}$")
_DOCTYPE_RE = re.compile(r"^[a-z0-9_\-]{1,80}$")
_DOMAIN_RE = re.compile(r"^[a-z0-9\-\.]{1,255}$")


def _validate_service_id(v: str) -> str:
    v = (v or "").strip().lower()
    if not _SERVICE_RE.match(v):
        raise HTTPException(status_code=400, detail={"error": "Invalid service_id format"})
    return v


def _validate_doc_type(v: str) -> str:
    v = (v or "").strip().lower()
    if not _DOCTYPE_RE.match(v):
        raise HTTPException(status_code=400, detail={"error": "Invalid doc_type format"})
    return v


def _normalize_domain(domain: str) -> str:
    d = (domain or "").strip().lower()
    if d.startswith("www."):
        d = d[4:]
    return d


def _validate_domain(domain: str) -> str:
    d = _normalize_domain(domain)
    if not d:
        raise HTTPException(status_code=400, detail={"error": "domain is required"})

    allow_local = os.getenv("CC_ALLOW_LOCALHOST", "0").lower() in ("1", "true", "yes")

    # ✅ Allow localhost & IPs ONLY if explicitly enabled
    if allow_local:
        if d in ("localhost", "127.0.0.1", "0.0.0.0"):
            return d
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", d):
            return d

    # ❌ Normal strict validation (production-safe)
    if not _DOMAIN_RE.match(d):
        raise HTTPException(status_code=400, detail={"error": "domain format looks invalid"})

    if not re.search(r"[a-z0-9\-]+\.[a-z]{2,}$", d):
        raise HTTPException(status_code=400, detail={"error": "domain format looks invalid"})

    return d


# ----------------------------
# Small helpers
# ----------------------------

def _sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8", errors="ignore")).hexdigest()



# ----------------------------
# Basic endpoints
# ----------------------------


@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/ping")
def ping():
    return {"status": "ok"}


@app.get("/favicon.ico")
def favicon():
    return JSONResponse(status_code=204, content=None)


@app.get("/version")
def version():
    return {
        "api": "Consent Companion API",
        "version": app.version,
        "engine_default_model": "all-MiniLM-L6-v2",
        "ota_targets_path": str(_default_targets_path()),
        "cache_dir": str(_cache_base()),
        "rate_limit": {"max_req": RATE_LIMIT_MAX_REQ, "window_sec": RATE_LIMIT_WINDOW_SEC},
        "filters": {
            "min_risk_keep": float(os.getenv("CC_MIN_RISK_KEEP", "2.0")),
            "similarity_drop": float(os.getenv("CC_SIMILARITY_DROP", "0.94")),
            "keep_oldless_risk": float(os.getenv("CC_KEEP_OLDLESS_RISK", "3.0")),
        },
        "ui": {
            "popup_max_items": 5,
            "theme_max": 3,
            "theme_items_max": 4,
        },
    }


# ----------------------------
# Paths
# ----------------------------


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_targets_path() -> Path:
    return _project_root() / "sources" / "ota_targets.json"


def _cache_base() -> Path:
    return _project_root() / "data" / "cache"


# ----------------------------
# Cache endpoints
# ----------------------------


@app.get("/ota/targets")
def ota_targets():
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
    service_id = _validate_service_id(service_id)
    doc_type = _validate_doc_type(doc_type)

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
    service_id = _validate_service_id(service_id)
    doc_type = _validate_doc_type(doc_type)

    base = _cache_base() / service_id / doc_type
    fp = (base / "latest.json") if version == "latest" else (base / "previous.json")

    if not fp.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No {version}.json found for {service_id}/{doc_type}. Run OTA sync first.",
        )

    obj = json.loads(fp.read_text(encoding="utf-8"))

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
    service_id = _validate_service_id(service_id)
    doc_type = _validate_doc_type(doc_type)

    fp = _cache_base() / service_id / doc_type / "last_diff.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail={"error": "No cached diff yet. Run sync first."})
    return json.loads(fp.read_text(encoding="utf-8"))


# ----------------------------
# Extension helpers
# ----------------------------


def _guess_service_id_from_domain(domain: str) -> str:
    d = _normalize_domain(domain)
    if not d:
        return ""
    parts = d.split(".")
    return parts[-2] if len(parts) >= 2 else parts[0]


def _impact_from_risk(max_risk: float, num_changes: int) -> str:
    if max_risk >= 3:
        return "important"
    if max_risk >= 2:
        return "minor"
    if num_changes > 0:
        return "minor"
    return "none"


def pick_top_change_index(last_diff: Optional[dict]) -> Optional[int]:
    changes = (last_diff or {}).get("changes") or []
    if not isinstance(changes, list) or not changes:
        return None

    best_i = None
    best_score = -1.0
    for i, ch in enumerate(changes):
        try:
            score = float(ch.get("risk_score", 0) or 0)
        except Exception:
            score = 0.0
        if score > best_score:
            best_score = score
            best_i = i
    return best_i


def _read_last_diff(service_id: str, doc_type: str) -> Optional[dict]:
    fp = _cache_base() / service_id / doc_type / "last_diff.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


def _diff_last_diff_at(diff_obj: Optional[dict]) -> Optional[str]:
    if not diff_obj:
        return None
    return diff_obj.get("generated_at") or diff_obj.get("provenance", {}).get("new", {}).get("fetched_at") or None


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        x = (x or "").strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


# ----------------------------
# Semantic post-filter (prevents "50 waffle changes")
# ----------------------------


def _post_filter_semantic(formatted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Second-layer filtering (even if upstream produces noisy alignments). Tunable via env vars."""
    sim_drop = float(os.getenv("CC_SIMILARITY_DROP", "0.94"))
    min_risk = float(os.getenv("CC_MIN_RISK_KEEP", "2.0"))
    keep_oldless_risk = float(os.getenv("CC_KEEP_OLDLESS_RISK", "3.0"))

    # 1) drop near-duplicates by similarity
    tmp: List[Dict[str, Any]] = []
    for c in formatted:
        sim = c.get("similarity")
        if sim is not None:
            try:
                if float(sim) >= sim_drop:
                    continue
            except Exception:
                pass
        tmp.append(c)

    # 2) keep only material items
    tmp = [c for c in tmp if float(c.get("risk_score", 0.0) or 0.0) >= min_risk]

    # 3) drop "added + old empty" unless risk is very high
    out: List[Dict[str, Any]] = []
    for c in tmp:
        t = (c.get("type") or "").strip().lower()
        old_txt = (c.get("old") or "").strip()
        r = float(c.get("risk_score", 0.0) or 0.0)
        if t == "added" and not old_txt and r < keep_oldless_risk:
            continue
        out.append(c)

    # 4) dedupe by meaning
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for c in out:
        cat = (c.get("category") or "").strip().lower()
        exp = (c.get("explanation") or "").strip().lower()
        act = (c.get("suggested_action") or "").strip().lower()
        key = (cat, exp, act)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    deduped.sort(key=lambda x: float(x.get("risk_score", 0.0) or 0.0), reverse=True)
    return deduped


# ----------------------------
# Theme summarisation (UI clarity)
# ----------------------------


def _theme_title(theme: str) -> str:
    return {
        "data_sharing": "Data sharing & third parties",
        "tracking": "Tracking, ads & profiling",
        "retention": "Data retention & storage",
        "collection": "Data collection",
        "rights": "User rights & controls",
        "purpose": "Purpose & legal basis",
        "security": "Security & safety",
        "billing": "Billing & payments",
        "other": "Other",
    }.get(theme, theme)


def _theme_from_change(c: Dict[str, Any]) -> str:
    theme = (c.get("theme") or "").strip()
    if theme:
        return theme

    # fallback if theme wasn't provided by engine
    cat = (c.get("category") or "").lower()
    if "sharing" in cat or "third" in cat or "advertis" in cat:
        return "data_sharing"
    if "tracking" in cat or "profil" in cat or "location" in cat:
        return "tracking"
    if "retention" in cat or "storage" in cat:
        return "retention"
    if "rights" in cat or "controls" in cat:
        return "rights"
    if "collection" in cat:
        return "collection"
    if "purpose" in cat or "legal basis" in cat:
        return "purpose"
    if "security" in cat:
        return "security"
    if "billing" in cat or "financial" in cat:
        return "billing"
    return "other"


def summarise_changes_to_themes(
    changes: List[Dict[str, Any]],
    *,
    max_themes: int = 3,
    max_items_per_theme: int = 4,
) -> List[Dict[str, Any]]:
    """Return a compact theme summary, stable + deterministic."""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for c in changes:
        t = _theme_from_change(c)
        buckets.setdefault(t, []).append(c)

    scored: List[Tuple[str, float, int]] = []
    for t, items in buckets.items():
        # score = max risk + small boost for count
        try:
            max_r = max(float(i.get("risk_score", 0.0) or 0.0) for i in items)
        except Exception:
            max_r = 0.0
        score = max_r + 0.15 * min(10, len(items))
        scored.append((t, score, len(items)))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[: max(0, int(max_themes))]

    out: List[Dict[str, Any]] = []
    for theme, score, count in top:
        items = sorted(
            buckets.get(theme, []),
            key=lambda x: float(x.get("risk_score", 0.0) or 0.0),
            reverse=True,
        )
        items = items[: max(1, int(max_items_per_theme))]

        out.append(
            {
                "theme": theme,
                "title": _theme_title(theme),
                "score": score,
                "count": count,
                "items": [
                    {
                        "type": i.get("type"),
                        "category": i.get("category"),
                        "risk_score": i.get("risk_score"),
                        "risk_label": i.get("risk_label"),
                        "confidence": i.get("confidence"),
                        "explanation": i.get("explanation"),
                        "suggested_action": i.get("suggested_action"),
                        "old": i.get("old"),
                        "new": i.get("new"),
                    }
                    for i in items
                ],
            }
        )

    return out


def _popup_lists_from_themes(themes: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """Create backward-compatible popup lists (max 5 each)."""
    if not themes:
        return [], []

    changes_lines: List[str] = []
    actions_lines: List[str] = []

    titles = [t.get("title") for t in themes if t.get("title")]
    if titles:
        changes_lines.append("Top themes: " + ", ".join(titles[:3]))

    for t in themes:
        title = t.get("title") or "Theme"
        items = t.get("items") or []
        if not isinstance(items, list) or not items:
            continue
        # add 1 strongest item per theme to keep list short
        it0 = items[0] if items else {}
        exp = (it0.get("explanation") or it0.get("category") or "").strip()
        if exp:
            changes_lines.append(f"{title}: {exp}")

    # actions: pick best unique actions from all theme items
    acts: List[str] = []
    for t in themes:
        for it in (t.get("items") or []):
            a = (it.get("suggested_action") or "").strip()
            if a:
                acts.append(a)

    actions_lines = _dedupe_keep_order(acts)[:5]
    return _dedupe_keep_order(changes_lines)[:5], actions_lines


# ----------------------------
# Extension endpoints
# ----------------------------


@app.get("/extension/check")
def extension_check(domain: str):
    domain_n = _validate_domain(domain)

    try:
        targets = json.loads(_default_targets_path().read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": f"Failed to load ota_targets.json: {e}"})

    service_guess = _guess_service_id_from_domain(domain_n)

    target = None
    for t in targets:
        if t.get("service_id") == service_guess and t.get("doc_type") == "privacy_policy":
            target = t
            break

    if not target:
        return {
            "domain": domain_n,
            "status": "none",
            "label": "Not tracked yet",
            "summary": "This site is not in the monitored OTA target list.",
            "last_changed": None,
            "last_diff_at": None,
            "service_id": None,
            "doc_type": None,
            "top_change_index": None,
            "themes": [],
            "changes": [],
            "actions": [],
            "detail_url": None,
        }

    service_id = _validate_service_id(target["service_id"])
    doc_type = _validate_doc_type(target["doc_type"])

    diff_obj = _read_last_diff(service_id, doc_type)
    if not diff_obj:
        return {
            "domain": domain_n,
            "status": "none",
            "label": "No cached diff yet",
            "summary": "Run the OTA sync to generate last_diff.json for this target.",
            "last_changed": None,
            "last_diff_at": None,
            "service_id": service_id,
            "doc_type": doc_type,
            "top_change_index": None,
            "themes": [],
            "changes": [],
            "actions": [],
            "detail_url": f"/ota-cache?service_id={service_id}&doc_type={doc_type}",
        }

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

    top_change_index = pick_top_change_index(diff_obj)
    top = {}
    if top_change_index is not None and 0 <= top_change_index < len(changes):
        top = changes[top_change_index]
    elif changes:
        top = changes[0]

    last_diff_at = _diff_last_diff_at(diff_obj)

    # Theme summary for clearer UI
    themes = summarise_changes_to_themes(changes, max_themes=3, max_items_per_theme=4)
    popup_changes, popup_actions = _popup_lists_from_themes(themes)

    if themes:
        theme_names = [t.get("title") for t in themes if t.get("title")]
        summary = f"{len(theme_names)} major themes changed: " + ", ".join(theme_names[:3])
    else:
        summary = (top.get("explanation") or top.get("category") or "No differences detected.").strip()

    detail_url = f"/ota-cache?service_id={service_id}&doc_type={doc_type}"
    if top_change_index is not None:
        detail_url += f"&change={top_change_index}"

    return {
        "domain": domain_n,
        "status": status,
        "label": LABELS.get(status, "Status unknown"),
        "summary": summary,
        "last_changed": last_diff_at,
        "last_diff_at": last_diff_at,
        "service_id": service_id,
        "doc_type": doc_type,
        "top_change_index": top_change_index,
        "themes": themes,
        "changes": popup_changes,
        "actions": popup_actions,
        "detail_url": detail_url,
    }


@app.post("/extension/updates")
def extension_updates(req: UpdatesRequest) -> Dict[str, Any]:
    updates: List[Dict[str, Any]] = []

    for t in req.targets:
        sid = _validate_service_id(t.service_id)
        dt = _validate_doc_type(t.doc_type)
        key = f"{sid}:{dt}"

        diff_obj = _read_last_diff(sid, dt)
        last_diff_at = _diff_last_diff_at(diff_obj)
        if not last_diff_at:
            continue

        baseline = (req.seen_map.get(key) or "").strip()
        if baseline and last_diff_at <= baseline:
            continue

        changes = diff_obj.get("changes") if isinstance(diff_obj.get("changes"), list) else []
        top_i = pick_top_change_index(diff_obj)

        top = {}
        if top_i is not None and 0 <= top_i < len(changes):
            top = changes[top_i]
        elif changes:
            top = changes[0]

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

        themes = summarise_changes_to_themes(changes, max_themes=3, max_items_per_theme=3)
        if themes:
            theme_names = [x.get("title") for x in themes if x.get("title")]
            summary = f"{len(theme_names)} major themes changed: " + ", ".join(theme_names[:3])
        else:
            summary = (top.get("explanation") or top.get("category") or "Policy changed.").strip()

        detail_url = f"/ota-cache?service_id={sid}&doc_type={dt}"
        if top_i is not None:
            detail_url += f"&change={top_i}"

        updates.append(
            {
                "service_id": sid,
                "doc_type": dt,
                "name": t.name,
                "status": status,
                "label": LABELS.get(status, "Status unknown"),
                "summary": summary,
                "last_changed": last_diff_at,
                "last_diff_at": last_diff_at,
                "top_change_index": top_i,
                "themes": themes,
                "detail_url": detail_url,
            }
        )

    return {"count": len(updates), "updates": updates, "generated_at": utc_now_iso()}


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
            formatted.append(
                {
                    "category": ch.get("category"),
                    "theme": ch.get("theme"),
                    "type": ch.get("type") or "modified",
                    "risk_score": ch.get("risk_score", 1.0),
                    "risk_label": ch.get("risk_label"),
                    "confidence": ch.get("confidence"),
                    "line_number": ch.get("line_number"),
                    "old": ch.get("old"),
                    "new": ch.get("new"),
                    "explanation": ch.get("explanation"),
                    "suggested_action": ch.get("suggested_action"),
                }
            )
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
        formatted.append(
            {
                "category": ch.get("category"),
                "theme": ch.get("theme"),
                "type": ch.get("type"),
                "risk_score": ch.get("risk_score", 0.0),
                "risk_label": ch.get("risk_label"),
                "confidence": ch.get("confidence"),
                "similarity": ch.get("similarity"),
                "old_index": ch.get("old_index"),
                "new_index": ch.get("new_index"),
                "old": ch.get("old"),
                "new": ch.get("new"),
                "explanation": ch.get("explanation"),
                "suggested_action": ch.get("suggested_action"),
            }
        )

    formatted = _post_filter_semantic(formatted)
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
# Lightweight loaders (frontend/history helper)
# ----------------------------

@app.get("/load/url")
def load_url(url: str) -> Dict[str, Any]:
    """
    Fetch a URL and return extracted readable text + metadata.
    Used by the frontend HistoryDetail page to open policies for URL-based history items.
    """
    u = (url or "").strip()
    if not u:
        raise HTTPException(status_code=400, detail={"error": "url is required"})

    try:
        loaded = load_from_url(u)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"error": f"Failed to load url: {e}"})

    text = loaded.text or ""
    return {
        "url": u,
        "fetched_at": utc_now_iso(),
        "content_sha256": _sha256_text(text),
        "meta": loaded.meta or {},
        "text": text,
    }

# Compare endpoints
# ----------------------------


@app.post("/compare")
async def compare(req: CompareRequest) -> Dict[str, Any]:
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
    old_text: Optional[str] = Form(None),
    old_url: Optional[str] = Form(None),
    old_ota: Optional[str] = Form(None),
    old_file: Optional[UploadFile] = File(None),
    new_text: Optional[str] = Form(None),
    new_url: Optional[str] = Form(None),
    new_ota: Optional[str] = Form(None),
    new_file: Optional[UploadFile] = File(None),
    mode: Mode = Form("semantic"),
    max_changes: int = Form(50),
) -> Dict[str, Any]:
    try:
        def nonempty_str(s: Optional[str]) -> bool:
            return bool(s and s.strip())

        def chosen_count(text, url, ota, file_obj) -> int:
            return int(nonempty_str(text)) + int(nonempty_str(url)) + int(nonempty_str(ota)) + int(file_obj is not None)

        old_count = chosen_count(old_text, old_url, old_ota, old_file)
        new_count = chosen_count(new_text, new_url, new_ota, new_file)

        if old_count != 1:
            raise HTTPException(
                status_code=400,
                detail={"error": "OLD: provide exactly ONE of old_text, old_url, old_ota, old_file."},
            )
        if new_count != 1:
            raise HTTPException(
                status_code=400,
                detail={"error": "NEW: provide exactly ONE of new_text, new_url, new_ota, new_file."},
            )

        old_loaded_text: str
        new_loaded_text: str
        old_meta: Dict[str, Any] = {}
        new_meta: Dict[str, Any] = {}
        out_source = "api"
        out_service_id: Optional[str] = None
        out_doc_type: Optional[str] = None

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
            old_loaded_text = old_text or ""
            old_meta = {"source_type": "text"}

        if nonempty_str(new_ota):
            sid, dtype = parse_ota_selector(new_ota)
            lp = load_from_ota_target(service_id=sid, doc_type=dtype)
            new_loaded_text, new_meta = lp.text, lp.meta
            out_source = "ota"
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
            new_loaded_text = new_text or ""
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.api_main:app", host="127.0.0.1", port=8000, reload=True)
