# backend/provenance.py
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Dict, Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


def input_provenance(text: str, meta: Dict[str, Any] | None = None) -> Dict[str, Any]:
    t = (text or "")
    return {
        "length_chars": len(t),
        "content_sha256": sha256_text(t),
        "meta": meta or {},
    }
