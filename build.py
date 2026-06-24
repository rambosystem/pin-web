#!/usr/bin/env python3
"""Build the PIN Ticket Analysis web frontend.

Examples:
    python web/build.py                # build only (auto-install if node_modules missing)
    python web/build.py --install      # force `npm install` first
    python web/build.py --clean        # remove dist/ before building
    python web/build.py --deps         # also install backend pip requirements

The script wraps the npm/Vite build documented in web/README.md so it can be
run from anywhere without remembering the exact directory.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent
FRONTEND_DIR = WEB_DIR / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
REQUIREMENTS = WEB_DIR / "requirements.txt"


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def fail(msg: str) -> int:
    print(f"[build][error] {msg}", file=sys.stderr, flush=True)
    return 1


def resolve_npm() -> str | None:
    for name in ("npm.cmd", "npm"):
        path = shutil.which(name)
        if path:
            return path
    return None


def run(cmd: list[str], cwd: Path) -> int:
    log(f"$ {' '.join(cmd)}  (cwd={cwd})")
    result = subprocess.run(cmd, cwd=str(cwd))
    return result.returncode


def install_backend_deps() -> int:
    if not REQUIREMENTS.is_file():
        return fail(f"requirements not found: {REQUIREMENTS}")
    log(f"Installing backend deps from {REQUIREMENTS}")
    return run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS)], REPO_ROOT)


def install_frontend(npm: str) -> int:
    log("Running npm install")
    return run([npm, "install"], FRONTEND_DIR)


def build_frontend(npm: str) -> int:
    log("Running npm run build")
    return run([npm, "run", "build"], FRONTEND_DIR)


def clean_dist() -> None:
    if DIST_DIR.exists():
        log(f"Removing {DIST_DIR}")
        shutil.rmtree(DIST_DIR, ignore_errors=True)


def summarize_dist() -> None:
    if not DIST_DIR.is_dir():
        return
    log(f"Build output: {DIST_DIR}")
    for entry in sorted(DIST_DIR.rglob("*")):
        if entry.is_file():
            size_kb = entry.stat().st_size / 1024
            rel = entry.relative_to(DIST_DIR)
            print(f"  {rel}  ({size_kb:,.1f} KB)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the web frontend.")
    parser.add_argument("--install", action="store_true", help="Force `npm install` before building.")
    parser.add_argument("--clean", action="store_true", help="Remove dist/ before building.")
    parser.add_argument("--deps", action="store_true", help="Also install backend pip requirements.")
    parser.add_argument("--no-build", action="store_true", help="Skip the build step (useful with --install/--deps).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not FRONTEND_DIR.is_dir():
        return fail(f"frontend folder not found: {FRONTEND_DIR}")

    if args.deps:
        rc = install_backend_deps()
        if rc != 0:
            return rc

    npm = resolve_npm()
    if not npm:
        return fail("npm not found in PATH. Install Node.js 18+ and retry.")

    needs_install = args.install or not (FRONTEND_DIR / "node_modules").is_dir()
    if needs_install:
        rc = install_frontend(npm)
        if rc != 0:
            return rc

    if args.clean:
        clean_dist()

    if args.no_build:
        log("Skipping build (--no-build).")
        return 0

    rc = build_frontend(npm)
    if rc != 0:
        return rc

    summarize_dist()
    log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
