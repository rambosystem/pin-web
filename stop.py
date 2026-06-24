#!/usr/bin/env python3
"""Stop the PIN Ticket Analysis backend server.

Examples:
    python web/stop.py                 # stop server on default 127.0.0.1:8765
    python web/stop.py --port 8765     # stop server on a specific port
    python web/stop.py --host 0.0.0.0  # stop server on a specific bind host
    python web/stop.py --quiet         # exit silently if nothing is running

Primarily intended for shutting down a server that was started with
`python web/run.py --background`. Works cross-platform with stdlib only.
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
DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"


def log(msg: str) -> None:
    print(f"[stop] {msg}", flush=True)


def fail(msg: str) -> int:
    print(f"[stop][error] {msg}", file=sys.stderr, flush=True)
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
                [lsof, "-nP", "-iTCP", "-sTCP:LISTEN", f"-i:{port}"],
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


def stop(host: str, port: int, quiet: bool) -> int:
    if not port_in_use(host, port):
        if not quiet:
            log(f"no server running on {host}:{port}")
        return 0

    pids = find_listening_pids(port)
    if not pids:
        return fail(
            f"port {port} is in use but no PID was detected; manual cleanup required."
        )

    failed: list[int] = []
    for pid in pids:
        log(f"stopping server pid={pid} on {host}:{port}")
        if not kill_pid(pid):
            failed.append(pid)

    for _ in range(30):
        if not port_in_use(host, port):
            log(f"server on {host}:{port} stopped.")
            return 0 if not failed else 1
        time.sleep(0.2)

    return fail(f"port {port} still in use after stop attempt; pids={pids}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stop the backend server.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT}).")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"host (default {DEFAULT_HOST}).")
    parser.add_argument("--quiet", action="store_true", help="suppress 'nothing running' message.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return stop(args.host, args.port, args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
