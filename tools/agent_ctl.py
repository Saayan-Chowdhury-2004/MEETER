"""Meeting Agent control switch — used by start_agent.bat / stop_agent.bat.

Commands:
    python tools/agent_ctl.py status           list agent processes
    python tools/agent_ctl.py stop             kill all agent processes
    python tools/agent_ctl.py start            start MEETING mode (OCR capped to 2 threads)
    python tools/agent_ctl.py start --full     start FULL mode (OCR may use all CPU threads)

Resource handling:
- MEETING mode caps OCR/BLAS thread pools via env vars set before Python starts
  (light profile for running beside long meetings).
- FULL mode leaves those vars empty so Paddle/OpenBLAS use every core.
- stop terminates the agent processes; the cap and RAM are released with them,
  because they exist only inside the agent process.

This module deliberately avoids printing or depending on console encoding
(Windows cp1252-safe output).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
MARKER = "app.main"          # identifies agent processes by command line
CONFIG = "config/observe-live.yaml"
API = "http://127.0.0.1:8765"

MEETING_THREADS = 2          # light profile
FULL_THREADS = None          # None = uncapped (library defaults = all cores)


def find_agent_pids() -> list:
    """PIDs of running agent processes (excludes this helper itself)."""
    me = os.getpid()
    my_script = os.path.abspath(__file__)
    pids = []
    for proc in _iter_processes():
        try:
            pid, name, cmd = proc
            if pid == me:
                continue
            if "python" not in (name or "").lower():
                continue
            if MARKER in (cmd or "") and my_script.lower() not in (cmd or "").lower():
                pids.append(pid)
        except Exception:  # noqa: BLE001
            continue
    return pids


def _iter_processes():
    try:
        import psutil

        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            yield p.info["pid"], p.info["name"], " ".join(p.info["cmdline"] or [])
    except ImportError:
        # fallback without psutil: WMIC is gone on Win11, use PowerShell
        out = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
                "| Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress",
            ],
            capture_output=True, text=True, timeout=30,
        )
        import json

        data = json.loads(out.stdout or "{}")
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not item:
                continue
            yield item.get("ProcessId"), "python.exe", item.get("CommandLine") or ""


def stop() -> int:
    pids = find_agent_pids()
    if not pids:
        print("Agent is not running.")
        return 0
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/f", "/pid", str(pid)],
                           capture_output=True, timeout=15)
            print(f"  stopped PID {pid}")
        except Exception as exc:  # noqa: BLE001
            print(f"  could not stop PID {pid}: {exc}")
    time.sleep(1)
    remaining = find_agent_pids()
    if remaining:
        print(f"[WARN] still running: {remaining}")
        return 1
    print("Agent is OFF - CPU threads and memory released.")
    return 0


def start(full: bool = False) -> int:
    existing = find_agent_pids()
    if existing:
        print(f"Agent already running (PID {existing[0]}). Nothing to start.")
        return 0
    if not VENV_PY.exists():
        print("[ERROR] .venv not found. Run setup first.")
        return 1

    # resource profile: the launcher communicates the mode to the agent via
    # MEETING_AGENT_OCR_THREADS ('N' = cap, '0' = explicitly uncapped).
    if full:
        threads = 0
        mode_name = "FULL mode (OCR uncapped: all CPU threads)"
    else:
        threads = MEETING_THREADS
        mode_name = f"MEETING mode (OCR capped to {threads} CPU threads)"
    env = os.environ.copy()
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "PADDLE_NUM_THREADS"):
        env.pop(var, None)          # never inherit stale caps
    env["MEETING_AGENT_OCR_THREADS"] = str(threads)
    print(f"Starting Meeting Agent - {mode_name}")

    log_path = ROOT / "data" / "agent-start.log"
    log_path.parent.mkdir(exist_ok=True)
    logf = log_path.open("ab")
    proc = subprocess.Popen(
        [str(VENV_PY), "-m", "app.main", "--config", CONFIG],
        cwd=str(ROOT), env=env,
        stdout=logf, stderr=logf,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        close_fds=True,
    )
    print(f"  agent launching (PID {proc.pid}), log: {log_path.name}")

    # wait for the local API
    for _ in range(15):
        time.sleep(2)
        if _api_up():
            print(f"Agent is ON  -  dashboard: {API}")
            return 0
    print(f"[WARN] API not answering after 30s - check {log_path}")
    return 1


def _api_up() -> bool:
    try:
        from urllib.request import urlopen

        with urlopen(f"{API}/health", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def status() -> int:
    pids = find_agent_pids()
    if not pids:
        print("Agent is OFF.")
        return 0
    print(f"Agent is ON  (PID {', '.join(map(str, pids))})")
    if _api_up():
        print(f"Dashboard:   {API}")
    else:
        print("API:         starting or unavailable")
    return 0


def main() -> int:
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if cmd == "stop":
        return stop()
    if cmd == "start":
        return start(full="--full" in sys.argv)
    if cmd == "status":
        return status()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
