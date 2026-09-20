# -*- coding: utf-8 -*-
"""Daily AnyRouter check-in: refresh the already-open Edge page at 10:00."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:\AetherPackBot")
PS1 = ROOT / "scripts" / "anyrouter_checkin.ps1"
LOG = ROOT / "data" / "logs" / "anyrouter_checkin.log"
URL = "https://anyrouter.top/console/personal"


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def main() -> int:
    log(f"checkin start {URL}")
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PS1),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
    except Exception as e:
        log(f"FAIL {type(e).__name__}: {e}")
        return 1
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if out:
        log(out.replace("\n", " | "))
    if proc.returncode != 0:
        log(f"FAIL exit={proc.returncode}")
        return proc.returncode
    log("checkin done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
