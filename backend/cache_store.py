# backend/cache_store.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class CachePaths:
    root: Path

    @property
    def latest(self) -> Path:
        return self.root / "latest"

    @property
    def previous(self) -> Path:
        return self.root / "previous"

    @property
    def diffs(self) -> Path:
        return self.root / "diffs"

    def ensure(self) -> None:
        self.latest.mkdir(parents=True, exist_ok=True)
        self.previous.mkdir(parents=True, exist_ok=True)
        self.diffs.mkdir(parents=True, exist_ok=True)


def _safe_key(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in s).strip("_")


def make_cache_key(service: str, doc: str) -> str:
    return f"{_safe_key(service)}__{_safe_key(doc)}"


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def rotate_and_store_snapshot(cache: CachePaths, key: str, snapshot: Dict[str, Any]) -> None:
    """
    Move latest -> previous, write new latest.
    """
    cache.ensure()
    latest_path = cache.latest / f"{key}.json"
    prev_path = cache.previous / f"{key}.json"

    if latest_path.exists():
        prev_path.write_text(latest_path.read_text(encoding="utf-8"), encoding="utf-8")

    snapshot = dict(snapshot)
    snapshot["_cached_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(latest_path, snapshot)


def store_diff(cache: CachePaths, key: str, diff_payload: Dict[str, Any]) -> None:
    cache.ensure()
    diff_path = cache.diffs / f"{key}.json"
    diff_payload = dict(diff_payload)
    diff_payload["_cached_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(diff_path, diff_payload)


def load_latest(cache: CachePaths, key: str) -> Optional[Dict[str, Any]]:
    return _read_json(cache.latest / f"{key}.json")


def load_previous(cache: CachePaths, key: str) -> Optional[Dict[str, Any]]:
    return _read_json(cache.previous / f"{key}.json")


def load_last_diff(cache: CachePaths, key: str) -> Optional[Dict[str, Any]]:
    return _read_json(cache.diffs / f"{key}.json")
