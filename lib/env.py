from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(env_path: Path) -> None:
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        k = key.strip()
        v = value.strip().strip("'\"").strip()
        if k:
            os.environ.setdefault(k, v)
    if "EMAIL" in os.environ and "CONFLUENCE_EMAIL" not in os.environ:
        os.environ.setdefault("CONFLUENCE_EMAIL", os.environ["EMAIL"])
