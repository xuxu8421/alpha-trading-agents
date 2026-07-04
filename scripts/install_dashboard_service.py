#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
from pathlib import Path


LABEL = "com.xusizhang.alpha-rnd-dashboard"
PROJECT_ROOT = Path.home() / "XSZ_PROJECTS" / "desktop-projects" / "quant-projects" / "alpha-trading-agents"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = Path.home() / ".tradingagents" / "rnd"
WRAPPER_PATH = LOG_DIR / "run-dashboard-service.zsh"


def wrapper_script(port: int) -> str:
    return f"""#!/bin/zsh
set -eu
IMAGE=\"/Volumes/KINGSTON/XSZ_PROJECTS.sparsebundle\"
MOUNT_POINT=\"$HOME/.xsz-mounts/XSZ_PROJECTS\"
STABLE_LINK=\"$HOME/XSZ_PROJECTS\"
PROJECT=\"$STABLE_LINK/desktop-projects/quant-projects/alpha-trading-agents\"

if [[ ! -f \"$PROJECT/scripts/serve_rnd_dashboard.py\" ]]; then
  mkdir -p \"$MOUNT_POINT\"
  if [[ ! -e \"$IMAGE\" ]]; then
    print -u2 \"project image unavailable: $IMAGE\"
    exit 75
  fi
  hdiutil attach \"$IMAGE\" -mountpoint \"$MOUNT_POINT\" -nobrowse
  ln -sfn \"$MOUNT_POINT\" \"$STABLE_LINK\"
fi

cd \"$PROJECT\"
exec \"$PROJECT/.venv/bin/python\" \"$PROJECT/scripts/serve_rnd_dashboard.py\" --port {port}
"""


def plist_payload(port: int) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            "/bin/zsh",
            str(WRAPPER_PATH),
        ],
        "WorkingDirectory": str(Path.home()),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 5,
        "StandardOutPath": str(LOG_DIR / "dashboard-server.log"),
        "StandardErrorPath": str(LOG_DIR / "dashboard-server.error.log"),
    }


def install(port: int) -> None:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    WRAPPER_PATH.write_text(wrapper_script(port), encoding="utf-8")
    WRAPPER_PATH.chmod(0o755)
    with PLIST_PATH.open("wb") as handle:
        plistlib.dump(plist_payload(port), handle, fmt=plistlib.FMT_XML, sort_keys=False)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(PLIST_PATH)], check=False, capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(PLIST_PATH)], check=True)
    subprocess.run(["launchctl", "enable", f"{domain}/{LABEL}"], check=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], check=True)
    print(f"Installed {LABEL}: http://127.0.0.1:{port}/alpha_rnd_dashboard.html")


def uninstall() -> None:
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(PLIST_PATH)], check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    print(f"Removed {LABEL}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the persistent Alpha R&D dashboard service")
    parser.add_argument("action", choices=["install", "uninstall"], nargs="?", default="install")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.action == "install":
        install(args.port)
    else:
        uninstall()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
