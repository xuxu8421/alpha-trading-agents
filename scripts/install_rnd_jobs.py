#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
from pathlib import Path


PROJECT_ROOT = Path.home() / "XSZ_PROJECTS" / "desktop-projects" / "quant-projects" / "alpha-trading-agents"
LOG_DIR = Path.home() / ".tradingagents" / "rnd"
WRAPPER_DIR = LOG_DIR / "jobs"
PLIST_DIR = Path.home() / "Library" / "LaunchAgents"

JOBS = {
    "auction": {
        "label": "com.xusizhang.alpha-rnd.auction",
        "mode": "auction",
        "hour": 9,
        "minute": 26,
        "weekdays": True,
    },
    "auction-evaluate": {
        "label": "com.xusizhang.alpha-rnd.auction-evaluate",
        "mode": "auction-evaluate",
        "hour": 15,
        "minute": 10,
        "weekdays": True,
    },
    "data-audit": {
        "label": "com.xusizhang.alpha-rnd.data-audit",
        "mode": "data-audit",
        "hour": 9,
        "minute": 27,
        "weekdays": True,
    },
    "market-pulse": {
        "label": "com.xusizhang.alpha-rnd.market-pulse",
        "mode": "market-pulse",
        "times": [(9, 35), (11, 35), (15, 20)],
        "weekdays": True,
    },
    "candidates": {
        "label": "com.xusizhang.alpha-rnd.candidates",
        "mode": "candidates",
        "hour": 15,
        "minute": 25,
        "weekdays": True,
    },
    "industry-intelligence": {
        "label": "com.xusizhang.alpha-rnd.industry-intelligence",
        "mode": "industry-intelligence",
        "hour": 19,
        "minute": 15,
        "weekdays": False,
    },
}


def wrapper_script(mode: str) -> str:
    return f"""#!/bin/zsh
set -eu
IMAGE="/Volumes/KINGSTON/XSZ_PROJECTS.sparsebundle"
MOUNT_POINT="$HOME/.xsz-mounts/XSZ_PROJECTS"
STABLE_LINK="$HOME/XSZ_PROJECTS"
PROJECT="$STABLE_LINK/desktop-projects/quant-projects/alpha-trading-agents"
LOG_DIR="$HOME/.tradingagents/rnd"
mkdir -p "$LOG_DIR" "$MOUNT_POINT"

if [[ ! -f "$PROJECT/tradingagents/rnd/runner.py" ]]; then
  if [[ ! -e "$IMAGE" ]]; then
    print -u2 "project image unavailable: $IMAGE"
    exit 75
  fi
  hdiutil attach "$IMAGE" -mountpoint "$MOUNT_POINT" -nobrowse || true
  ln -sfn "$MOUNT_POINT" "$STABLE_LINK"
fi

if [[ ! -f "$PROJECT/tradingagents/rnd/runner.py" ]]; then
  print -u2 "project unavailable: $PROJECT"
  exit 75
fi

cd "$PROJECT"
"$PROJECT/.venv/bin/python" -m tradingagents.rnd.runner --mode {mode}
if [[ "{mode}" != "data-audit" ]]; then
  "$PROJECT/.venv/bin/python" -m tradingagents.rnd.runner --mode data-audit
fi
"""


def calendar_interval(job: dict) -> list[dict] | dict:
    times = job.get("times") or [(job["hour"], job["minute"])]
    rows = [{"Hour": hour, "Minute": minute} for hour, minute in times]
    if not job["weekdays"]:
        return rows[0] if len(rows) == 1 else rows
    return [{**row, "Weekday": weekday} for row in rows for weekday in range(1, 6)]


def plist_payload(job: dict, wrapper_path: Path) -> dict:
    label = job["label"]
    return {
        "Label": label,
        "ProgramArguments": ["/bin/zsh", str(wrapper_path)],
        "WorkingDirectory": str(Path.home()),
        "StartCalendarInterval": calendar_interval(job),
        "StandardOutPath": str(LOG_DIR / f"{label}.log"),
        "StandardErrorPath": str(LOG_DIR / f"{label}.error.log"),
    }


def install(selected: list[str]) -> None:
    PLIST_DIR.mkdir(parents=True, exist_ok=True)
    WRAPPER_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    for name in selected:
        job = JOBS[name]
        label = job["label"]
        wrapper_path = WRAPPER_DIR / f"{name}.zsh"
        plist_path = PLIST_DIR / f"{label}.plist"
        wrapper_path.write_text(wrapper_script(job["mode"]), encoding="utf-8")
        wrapper_path.chmod(0o755)
        with plist_path.open("wb") as handle:
            plistlib.dump(plist_payload(job, wrapper_path), handle, fmt=plistlib.FMT_XML, sort_keys=False)
        subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False, capture_output=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], check=True)
        subprocess.run(["launchctl", "enable", f"{domain}/{label}"], check=True)
        print(f"Installed {label}")


def uninstall(selected: list[str]) -> None:
    domain = f"gui/{os.getuid()}"
    for name in selected:
        label = JOBS[name]["label"]
        plist_path = PLIST_DIR / f"{label}.plist"
        subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False, capture_output=True)
        if plist_path.exists():
            plist_path.unlink()
        wrapper_path = WRAPPER_DIR / f"{name}.zsh"
        if wrapper_path.exists():
            wrapper_path.unlink()
        print(f"Removed {label}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Alpha R&D scheduled jobs")
    parser.add_argument("action", choices=["install", "uninstall"], nargs="?", default="install")
    parser.add_argument("--job", choices=sorted(JOBS), action="append", help="Install/uninstall one job; repeatable.")
    args = parser.parse_args()
    selected = args.job or list(JOBS)
    if args.action == "install":
        install(selected)
    else:
        uninstall(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
