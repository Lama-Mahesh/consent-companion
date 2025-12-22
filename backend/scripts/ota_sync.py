from __future__ import annotations

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple

from backend.policy_loader import (
    load_ota_targets,
    ota_target_raw_url,
    load_from_url,
)
from backend.consent_core import analyze_policy_change_semantic, analyze_policy_change_basic


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8", errors="ignore")).hexdigest()


def safe_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def safe_read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(int(n), hi))


def run_diff(old_text: str, new_text: str, mode: str, max_changes: int) -> Dict[str, Any]:
    if mode == "basic":
        changes = analyze_policy_change_basic(old_text, new_text)
        formatted = []
        for ch in changes[:max_changes]:
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
        return {
            "engine": {"mode": "basic", "model_name": None, "num_changes": len(formatted)},
            "changes": formatted,
        }

    # semantic
    changes_raw = analyze_policy_change_semantic(old_text, new_text, model=None)
    formatted = []
    for ch in changes_raw[:max_changes]:
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
    return {
        "engine": {"mode": "semantic", "model_name": "all-MiniLM-L6-v2", "num_changes": len(formatted)},
        "changes": formatted,
    }


def main() -> None:
    targets_path = os.getenv("OTA_TARGETS_PATH", "sources/ota_targets.json")
    cache_dir = Path(os.getenv("CACHE_DIR", "data/cache"))
    mode = os.getenv("API_MODE", "semantic").strip().lower()
    max_changes = clamp(int(os.getenv("MAX_CHANGES", "50")), 1, 500)

    targets: List[Dict[str, Any]] = load_ota_targets(targets_path)

    for t in targets:
        service_id = t.get("service_id")
        doc_type = t.get("doc_type")
        name = t.get("name") or f"{service_id}:{doc_type}"
        repo = t.get("repo")
        branch = t.get("branch") or "main"
        path = t.get("path")

        if not (service_id and doc_type and repo and path):
            print(f"Skipping invalid target: {t}")
            continue

        # per-target folder
        out_dir = cache_dir / service_id / doc_type
        latest_path = out_dir / "latest.json"
        prev_path = out_dir / "previous.json"
        diff_path = out_dir / "last_diff.json"

        url = ota_target_raw_url(t)

        print(f"\n==> Fetching {name}")
        loaded = load_from_url(url)
        text = loaded.text
        fetched_at = utc_now_iso()
        content_hash = sha256_text(text)

        latest_obj = safe_read_json(latest_path)

        # If no latest exists yet -> initialize
        if not latest_obj:
            latest_snapshot = {
                "service_id": service_id,
                "doc_type": doc_type,
                "name": name,
                "source": {
                    "type": "ota",
                    "repo": repo,
                    "branch": branch,
                    "path": path,
                    "url": url,
                },
                "fetched_at": fetched_at,
                "content_sha256": content_hash,
                "meta": loaded.meta,
                "text": text,
            }
            safe_write_json(latest_path, latest_snapshot)
            print("Initialized latest.json (first run)")
            continue

        # If unchanged -> do nothing
        if latest_obj.get("content_sha256") == content_hash:
            print("No change (hash match) — skipping diff.")
            continue

        # Shift latest -> previous
        safe_write_json(prev_path, latest_obj)

        # Write new latest
        latest_snapshot = {
            "service_id": service_id,
            "doc_type": doc_type,
            "name": name,
            "source": {
                "type": "ota",
                "repo": repo,
                "branch": branch,
                "path": path,
                "url": url,
            },
            "fetched_at": fetched_at,
            "content_sha256": content_hash,
            "meta": loaded.meta,
            "text": text,
        }
        safe_write_json(latest_path, latest_snapshot)

        # Compute diff previous -> latest
        old_text = (latest_obj.get("text") or "").strip()
        new_text = text.strip()

        diff_core = run_diff(old_text, new_text, mode=mode, max_changes=max_changes)

        diff_obj = {
            "service_id": service_id,
            "doc_type": doc_type,
            "name": name,
            "generated_at": utc_now_iso(),
            "provenance": {
                "old": {
                    "fetched_at": latest_obj.get("fetched_at"),
                    "content_sha256": latest_obj.get("content_sha256"),
                    "source": latest_obj.get("source"),
                },
                "new": {
                    "fetched_at": fetched_at,
                    "content_sha256": content_hash,
                    "source": latest_snapshot.get("source"),
                },
            },
            **diff_core,
        }
        safe_write_json(diff_path, diff_obj)

        print("Updated latest.json, previous.json, last_diff.json")


if __name__ == "__main__":
    main()
