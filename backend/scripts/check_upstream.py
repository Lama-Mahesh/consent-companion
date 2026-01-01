from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# We reuse your existing URL builder so you don't duplicate logic
from backend.policy_loader import load_ota_targets, ota_target_raw_url


@dataclass
class Fingerprint:
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_length: Optional[str] = None
    status_code: Optional[int] = None

    def stable_key(self) -> str:
        """
        A stable fingerprint string derived from headers.
        If some headers are missing, that's okay.
        """
        parts = [
            f"etag={self.etag or ''}",
            f"lm={self.last_modified or ''}",
            f"len={self.content_length or ''}",
            f"status={self.status_code or ''}",
        ]
        return "|".join(parts)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()


def safe_read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def safe_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _http_fingerprint(url: str, timeout: float = 20.0) -> Tuple[Fingerprint, bool]:
    """
    Returns (fingerprint, ok).
    ok=False only when both HEAD and fallback GET fail.
    """
    headers = {
        "User-Agent": "ConsentCompanion/1.0 (upstream check)",
        "Accept": "text/plain,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # 1) HEAD first (fast)
    try:
        r = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        fp = Fingerprint(
            etag=r.headers.get("ETag") or r.headers.get("etag"),
            last_modified=r.headers.get("Last-Modified") or r.headers.get("last-modified"),
            content_length=r.headers.get("Content-Length") or r.headers.get("content-length"),
            status_code=r.status_code,
        )
        # Some hosts return weak/no useful HEAD headers, but still valid.
        return fp, True
    except Exception:
        pass

    # 2) Fallback GET but do NOT download full body (stream)
    try:
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True, stream=True)
        fp = Fingerprint(
            etag=r.headers.get("ETag") or r.headers.get("etag"),
            last_modified=r.headers.get("Last-Modified") or r.headers.get("last-modified"),
            content_length=r.headers.get("Content-Length") or r.headers.get("content-length"),
            status_code=r.status_code,
        )
        # We are not reading body, close quickly
        r.close()
        return fp, True
    except Exception:
        return Fingerprint(status_code=None), False


def set_github_output(key: str, value: str) -> None:
    """
    GitHub Actions outputs are written to the file in $GITHUB_OUTPUT.
    """
    out_path = os.getenv("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(f"{key}={value}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fast upstream check for OTA targets.")
    ap.add_argument("--targets", required=True, help="Path to sources/ota_targets.json")
    ap.add_argument("--state", required=True, help="Path to state JSON file (written/updated)")
    ap.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds")
    args = ap.parse_args()

    targets_path = args.targets
    state_path = Path(args.state)

    targets: List[Dict[str, Any]] = load_ota_targets(targets_path)

    prev_state = safe_read_json(state_path) or {}
    prev_map: Dict[str, str] = prev_state.get("fingerprints", {}) if isinstance(prev_state, dict) else {}

    new_map: Dict[str, str] = {}
    changed_keys: List[str] = []
    failures: List[str] = []

    for t in targets:
        service_id = t.get("service_id")
        doc_type = t.get("doc_type")
        if not service_id or not doc_type:
            continue

        key = f"{service_id}:{doc_type}"
        url = ota_target_raw_url(t)

        fp, ok = _http_fingerprint(url, timeout=args.timeout)
        if not ok:
            failures.append(key)
            # If we cannot check, do NOT mark changed.
            # We keep old fingerprint if exists.
            if key in prev_map:
                new_map[key] = prev_map[key]
            continue

        fp_hash = sha256(fp.stable_key())
        new_map[key] = fp_hash

        if prev_map.get(key) != fp_hash:
            changed_keys.append(key)

    changed = "true" if len(changed_keys) > 0 else "false"

    # write updated state for next run
    new_state = {
        "version": 1,
        "fingerprints": new_map,
        "changed_keys": changed_keys,
        "failures": failures,
    }
    safe_write_json(state_path, new_state)

    # GitHub outputs
    set_github_output("changed", changed)
    set_github_output("changed_keys", ",".join(changed_keys))

    # Console logs (useful for Actions UI)
    print(f"[check_upstream] changed={changed}")
    print(f"[check_upstream] changed_keys={changed_keys}")
    if failures:
        print(f"[check_upstream] failures={failures}")


if __name__ == "__main__":
    main()
