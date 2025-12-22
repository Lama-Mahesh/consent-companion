from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List

from policy_loader import load_from_url
from cache_store import rotate_if_changed, get_cache_paths, write_json
import consent_core


ROOT = Path(__file__).resolve().parent
TARGETS_PATH = ROOT / "targets.json"


def _load_targets() -> List[Dict[str, Any]]:
    data = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    return data.get("targets", [])


def run_sync(mode: str = "semantic", max_changes: int = 200) -> Dict[str, Any]:
    results = {
        "mode": mode,
        "max_changes": max_changes,
        "targets_processed": 0,
        "targets_changed": 0,
        "targets": [],
    }

    targets = _load_targets()

    for t in targets:
        service_id = t["service_id"]
        doc_type = t["doc_type"]
        source = t["source"]

        if source.get("type") != "url":
            # future: OTA support can plug in here
            raise ValueError(f"Unsupported source type: {source.get('type')}")

        url = source["url"]
        loaded = load_from_url(url)

        rot = rotate_if_changed(service_id, doc_type, loaded.text)

        # If we don't have previous yet, we cannot diff
        paths = get_cache_paths(service_id, doc_type)
        prev_text = paths.previous.read_text(encoding="utf-8", errors="ignore") if paths.previous.exists() else None
        latest_text = paths.latest.read_text(encoding="utf-8", errors="ignore") if paths.latest.exists() else None

        diff_written = False
        num_changes = 0

        if prev_text and latest_text:
            if mode == "basic":
                raw = consent_core.analyze_policy_change_basic(prev_text, latest_text)
                changes = [
                    {
                        "category": ch.get("category"),
                        "type": "modified",
                        "risk_score": ch.get("risk_score", 1.0),
                        "old": ch.get("old"),
                        "new": ch.get("new"),
                        "explanation": ch.get("explanation"),
                        "suggested_action": ch.get("suggested_action"),
                    }
                    for ch in raw
                ]
                engine = {"mode": "basic", "model_name": None}
            else:
                raw = consent_core.analyze_policy_change_semantic(prev_text, latest_text, model=None)
                changes = [
                    {
                        "category": ch.get("category"),
                        "type": ch.get("type"),
                        "risk_score": ch.get("risk_score", 0.0),
                        "similarity": ch.get("similarity"),
                        "old": ch.get("old"),
                        "new": ch.get("new"),
                        "explanation": ch.get("explanation"),
                        "suggested_action": ch.get("suggested_action"),
                    }
                    for ch in raw
                ]
                engine = {"mode": "semantic", "model_name": "all-MiniLM-L6-v2"}

            changes = changes[:max_changes]
            num_changes = len(changes)

            payload = {
                "service_id": service_id,
                "doc_type": doc_type,
                "source": {"type": "url", "url": url, "final_url": loaded.meta.get("final_url")},
                "engine": {**engine, "num_changes": num_changes},
                "changes": changes,
            }

            write_json(paths.last_diff, payload)
            diff_written = True

        results["targets_processed"] += 1
        if rot["changed"]:
            results["targets_changed"] += 1

        results["targets"].append({
            "service_id": service_id,
            "doc_type": doc_type,
            "url": url,
            "changed": rot["changed"],
            "has_previous": rot["has_previous"],
            "diff_written": diff_written,
            "num_changes": num_changes,
        })

    return results


if __name__ == "__main__":
    out = run_sync()
    print(json.dumps(out, indent=2))
