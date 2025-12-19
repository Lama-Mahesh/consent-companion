# backend/ota_github.py
from __future__ import annotations

import os
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


@dataclass
class OTATarget:
    service_id: str
    doc_type: str
    repo: str               # "OWNER/REPO"
    path: str               # file path inside repo
    branch: str = "main"


class OTAStore:
    """
    Disk usage stays small because we only store:
      - last N versions (by SHA)
      - a tiny state file recording last seen SHA
    """
    def __init__(
        self,
        project_root: Path,
        targets_path: Path,
        state_path: Path,
        cache_dir: Path,
        reports_dir: Path,
        keep_last_n: int = 2,
    ):
        self.project_root = project_root
        self.targets_path = targets_path
        self.state_path = state_path
        self.cache_dir = cache_dir
        self.reports_dir = reports_dir
        self.keep_last_n = keep_last_n

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def load_targets(self) -> List[OTATarget]:
        raw = json.loads(self.targets_path.read_text(encoding="utf-8"))
        targets: List[OTATarget] = []
        for r in raw:
            targets.append(
                OTATarget(
                    service_id=r["service_id"],
                    doc_type=r["doc_type"],
                    repo=r["repo"],
                    path=r["path"],
                    branch=r.get("branch", "main"),
                )
            )
        return targets

    from typing import Any, Dict

    def load_state(self) -> Dict[str, Any]:
        default: Dict[str, Any] = {"items": {}}

        if not self.state_path.exists():
            return default

        raw = self.state_path.read_text(encoding="utf-8").strip()
        if raw == "":
            return default

        try:
            data: Any = json.loads(raw)
        except json.JSONDecodeError:
            return default

        if not isinstance(data, dict):
            return default

        items = data.get("items")
        if not isinstance(items, dict):
            data["items"] = {}

        return data

    def save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def key(self, t: OTATarget) -> str:
        return f"{t.repo}::{t.path}"

    def policy_dir(self, t: OTATarget) -> Path:
        return self.cache_dir / t.service_id / t.doc_type

    def save_version(self, t: OTATarget, sha: str, text: str) -> Path:
        d = self.policy_dir(t)
        d.mkdir(parents=True, exist_ok=True)
        fp = d / f"{sha}.txt"
        fp.write_text(text, encoding="utf-8")
        return fp

    def list_versions(self, t: OTATarget) -> List[Path]:
        d = self.policy_dir(t)
        if not d.exists():
            return []
        return sorted(d.glob("*.txt"), key=lambda p: p.stat().st_mtime)

    def prune_old(self, t: OTATarget) -> None:
        versions = self.list_versions(t)
        if len(versions) <= self.keep_last_n:
            return
        to_delete = versions[:-self.keep_last_n]
        for p in to_delete:
            try:
                p.unlink()
            except OSError:
                pass


class GitHubClient:
    def __init__(self, token: Optional[str] = None, sleep_on_rate_limit: bool = True):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.sleep_on_rate_limit = sleep_on_rate_limit
        self.base = "https://api.github.com"

    def _headers(self) -> Dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ConsentCompanion/1.0"
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        r = requests.get(url, headers=self._headers(), params=params, timeout=30)
        # Simple rate limit handling
        if r.status_code == 403 and self.sleep_on_rate_limit:
            remaining = r.headers.get("X-RateLimit-Remaining")
            reset = r.headers.get("X-RateLimit-Reset")
            if remaining == "0" and reset:
                wait_s = max(0, int(reset) - int(time.time())) + 2
                time.sleep(wait_s)
                r = requests.get(url, headers=self._headers(), params=params, timeout=30)
        r.raise_for_status()
        return r

    def get_file_meta(self, repo: str, path: str, ref: str) -> Dict[str, Any]:
        # GitHub Contents API
        url = f"{self.base}/repos/{repo}/contents/{path}"
        return self._get(url, params={"ref": ref}).json()

    def download_text(self, download_url: str) -> str:
        r = self._get(download_url)
        # GitHub raw sometimes returns bytes; enforce text
        return r.text
    def get_repo(self, repo: str) -> Dict[str, Any]:
        url = f"{self.base}/repos/{repo}"
        return self._get(url).json()



def poll_once(
    project_root: Path,
    keep_last_n: int = 2,
    generate_reports: bool = True,
) -> Dict[str, Any]:
    """
    Poll all targets:
      - checks current SHA for each tracked file
      - downloads only if SHA changed
      - optionally generates a change report JSON
    """
    targets_path = project_root / "sources" / "ota_targets.json"
    state_path = project_root / "sources" / "ota_state.json"
    cache_dir = project_root / "data" / "ota_cache"
    reports_dir = project_root / "outputs" / "ota_reports"

    store = OTAStore(
        project_root=project_root,
        targets_path=targets_path,
        state_path=state_path,
        cache_dir=cache_dir,
        reports_dir=reports_dir,
        keep_last_n=keep_last_n,
    )
    gh = GitHubClient()

    targets = store.load_targets()
    state = store.load_state()

    results: Dict[str, Any] = {"checked": 0, "changed": 0, "items": []}

    for t in targets:
        results["checked"] += 1
        k = store.key(t)
        prev_sha = state["items"].get(k, {}).get("sha")

        # print("Polling:", t.repo, t.branch, t.path)  # <-- add this line here

        try:
            meta = gh.get_file_meta(t.repo, t.path, t.branch)
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            results["items"].append({
                "target": k,
                "status": "error",
                "reason": f"github {status}",
                "repo": t.repo,
                "branch": t.branch,
                "path": t.path,
            })
            continue

        sha = meta.get("sha")
        download_url = meta.get("download_url")

        if not sha or not download_url:
            results["items"].append({"target": k, "status": "error", "reason": "missing sha/download_url"})
            continue

        if prev_sha == sha:
            results["items"].append({"target": k, "status": "unchanged", "sha": sha})
            continue

        # Download new version
        text = gh.download_text(download_url)
        new_fp = store.save_version(t, sha, text)

        # Load previous (if exists) for report generation
        prev_text = None
        if prev_sha:
            prev_fp = store.policy_dir(t) / f"{prev_sha}.txt"
            if prev_fp.exists():
                prev_text = prev_fp.read_text(encoding="utf-8", errors="ignore")

        # Update state
        state["items"][k] = {
            "sha": sha,
            "download_url": download_url,
            "repo": t.repo,
            "path": t.path,
            "branch": t.branch,
            "service_id": t.service_id,
            "doc_type": t.doc_type,
            "last_seen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        store.save_state(state)
        store.prune_old(t)

        results["changed"] += 1
        item = {"target": k, "status": "changed", "old_sha": prev_sha, "new_sha": sha, "saved_to": str(new_fp)}

        # Optional: generate a report JSON using your engine
        if generate_reports and prev_text:
            try:
                from backend import consent_core  # run from project root
                changes = consent_core.analyze_policy_change_semantic(prev_text, text, model=None)
                report = {
                    "service_id": t.service_id,
                    "doc_type": t.doc_type,
                    "source": "OpenTermsArchive via GitHub API",
                    "repo": t.repo,
                    "path": t.path,
                    "old_sha": prev_sha,
                    "new_sha": sha,
                    "num_changes": len(changes),
                    "changes": changes,
                }
                out = store.reports_dir / f"{t.service_id}__{t.doc_type}__{sha}.json"
                out.write_text(json.dumps(report, indent=2), encoding="utf-8")
                item["report"] = str(out)
            except Exception as e:
                item["report_error"] = str(e)

        results["items"].append(item)

    return results
