#!/usr/bin/env python3
"""Start (or restart) the PIN Ticket Analysis backend server.

Examples:
    python web/run.py                  # restart on default port 8765
    python web/run.py --no-kill        # do not stop existing instance
    python web/run.py --build          # build frontend first, then start
    python web/run.py --port 8765      # override port
    python web/run.py --background     # spawn server detached and return

By default the script:
  1. Detects whether the target port is already in use and terminates the
     owning process (cross-platform, stdlib only).
  2. Optionally builds the frontend (`python web/build.py`).
  3. Launches `python web/server.py` in the foreground (Ctrl+C stops it).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent
SERVER_SCRIPT = WEB_DIR / "server.py"
BUILD_SCRIPT = WEB_DIR / "build.py"
FRONTEND_DIST = WEB_DIR / "frontend" / "dist"
DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"


def log(msg: str) -> None:
    print(f"[run] {msg}", flush=True)


def fail(msg: str) -> int:
    print(f"[run][error] {msg}", file=sys.stderr, flush=True)
    return 1


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def find_listening_pids(port: int) -> list[int]:
    """Return PIDs listening on the given TCP port (Windows + POSIX)."""
    pids: set[int] = set()
    if os.name == "nt":
        try:
            output = subprocess.check_output(
                ["netstat", "-ano", "-p", "TCP"], text=True, errors="ignore"
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return []
        pattern = re.compile(rf"^\s*TCP\s+\S+:{port}\s+\S+\s+LISTENING\s+(\d+)\s*$")
        for line in output.splitlines():
            m = pattern.match(line)
            if m:
                pids.add(int(m.group(1)))
        return sorted(pids)

    lsof = shutil.which("lsof")
    if lsof:
        try:
            output = subprocess.check_output(
                [lsof, "-nP", "-iTCP", f"-sTCP:LISTEN", f"-i:{port}"],
                text=True,
                errors="ignore",
            )
        except subprocess.CalledProcessError:
            output = ""
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                pids.add(int(parts[1]))
    return sorted(pids)


def kill_pid(pid: int) -> bool:
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
        os.kill(pid, signal.SIGKILL)
        return True
    except (PermissionError, ProcessLookupError, OSError) as exc:
        log(f"failed to kill pid {pid}: {exc}")
        return False


def stop_existing(host: str, port: int) -> None:
    if not port_in_use(host, port):
        return
    pids = find_listening_pids(port)
    if not pids:
        log(f"port {port} appears busy but no PID detected; continuing anyway.")
        return
    for pid in pids:
        log(f"stopping existing server pid={pid} on {host}:{port}")
        kill_pid(pid)
    for _ in range(30):
        if not port_in_use(host, port):
            return
        time.sleep(0.2)
    log(f"warning: port {port} still in use after stop attempt.")


def maybe_build() -> int:
    if not BUILD_SCRIPT.is_file():
        return fail(f"build.py not found at {BUILD_SCRIPT}")
    log("Building frontend before start")
    result = subprocess.run([sys.executable, str(BUILD_SCRIPT)], cwd=str(REPO_ROOT))
    return result.returncode


def warn_if_no_dist() -> None:
    if not FRONTEND_DIST.is_dir():
        log(f"warning: {FRONTEND_DIST} not found. Run `python web/build.py` for the UI to load.")


def start_server(port: int, host: str, background: bool) -> int:
    if not SERVER_SCRIPT.is_file():
        return fail(f"server script not found: {SERVER_SCRIPT}")

    env = os.environ.copy()
    env.setdefault("PIN_WEB_HOST", host)
    env.setdefault("PIN_WEB_PORT", str(port))

    cmd = [sys.executable, str(SERVER_SCRIPT)]
    log(f"starting backend: {' '.join(cmd)}  (http://{host}:{port})")

    if background:
        kwargs: dict = {"cwd": str(REPO_ROOT), "env": env}
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            )
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
            kwargs["stdin"] = subprocess.DEVNULL
        else:
            kwargs["start_new_session"] = True
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
            kwargs["stdin"] = subprocess.DEVNULL
        proc = subprocess.Popen(cmd, **kwargs)
        for _ in range(50):
            if port_in_use(host, port):
                log(f"server is up (pid={proc.pid}) at http://{host}:{port}")
                return 0
            if proc.poll() is not None:
                return fail(f"server exited with code {proc.returncode} before binding the port")
            time.sleep(0.2)
        log(f"warning: server (pid={proc.pid}) did not bind {host}:{port} within 10s")
        return 0

    try:
        return subprocess.call(cmd, cwd=str(REPO_ROOT), env=env)
    except KeyboardInterrupt:
        log("interrupted; shutting down")
        return 130


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start or restart the backend server.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT}).")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"host (default {DEFAULT_HOST}).")
    parser.add_argument("--no-kill", action="store_true", help="Do not stop existing instance on the port.")
    parser.add_argument("--build", action="store_true", help="Run `python web/build.py` before starting.")
    parser.add_argument("--background", action="store_true", help="Detach the server process and return.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.build:
        rc = maybe_build()
        if rc != 0:
            return rc

    if not args.no_kill:
        stop_existing(args.host, args.port)
    elif port_in_use(args.host, args.port):
        return fail(f"port {args.port} already in use (use without --no-kill to auto-stop).")

    warn_if_no_dist()
    return start_server(args.port, args.host, args.background)


if __name__ == "__main__":
    raise SystemExit(main())
