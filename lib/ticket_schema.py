from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.profile import CONFIG_ROOT_DIRNAME


def _schema_path(repo_root: Path, project_key: str) -> Path:
    return repo_root / CONFIG_ROOT_DIRNAME / "policy" / project_key.upper() / "ticket-schema.json"


def load_project_ticket_schema(repo_root: Path, project_key: str) -> dict[str, Any]:
    path = _schema_path(repo_root, project_key)
    if not path.is_file():
        raise RuntimeError(f"Ticket schema not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid ticket schema JSON: {path}: {exc}") from exc


def load_issue_schema(repo_root: Path, project_key: str, issue_type: str) -> dict[str, Any]:
    schema = load_project_ticket_schema(repo_root, project_key)
    issue_types = schema.get("issue_types") or {}
    issue_schema = issue_types.get(issue_type)
    if not isinstance(issue_schema, dict):
        raise RuntimeError(
            f"Issue type '{issue_type}' not defined in ticket schema: {_schema_path(repo_root, project_key)}"
        )
    return issue_schema
