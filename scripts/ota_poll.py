# scripts/ota_poll.py
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.ota_github import poll_once


def main() -> None:
    ap = argparse.ArgumentParser(description="ConsentCompanion OTA online-first poller (GitHub API)")
    ap.add_argument("--keep", type=int, default=2, help="Keep last N versions per policy")
    ap.add_argument("--no-reports", action="store_true", help="Disable auto report generation")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    res = poll_once(
        project_root=project_root,
        keep_last_n=args.keep,
        generate_reports=(not args.no_reports),
    )
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
