from __future__ import annotations

import re
from pathlib import Path

from lib.profile import (
    load_workspace_profile,
    read_profile,
    resolve_profile_path,
)
from lib.profile import ASSETS_DIRNAME, CONFIG_ROOT_DIRNAME, GLOBAL_DIRNAME
from lib.ticket_schema import load_project_ticket_schema


def load_jira_runtime_profile(repo_root: Path) -> dict[str, str]:
    profile_path = resolve_profile_path(repo_root)
    profile = load_workspace_profile(profile_path)
    out = {
        "base_url": (profile.get("base_url") or "").rstrip("/"),
        "email": profile.get("email") or "",
        "account_id": profile.get("account_id") or "",
        "default_project": profile.get("default_project") or "CP",
        "profile_path": str(profile_path),
    }
    if not out["base_url"]:
        raise RuntimeError(f"Missing confluence_base_url in profile: {profile_path}")
    if not out["email"]:
        raise RuntimeError(f"Missing email in profile: {profile_path}")
    if not out["account_id"]:
        raise RuntimeError(f"Missing account_id in profile: {profile_path}")
    return out


def load_team_defaults(repo_root: Path, project_key: str) -> dict[str, str]:
    schema = load_project_ticket_schema(repo_root, project_key)
    defaults = schema.get("defaults") or {}
    policy = schema.get("policy") or {}
    assignee = defaults.get("assignee") or {}
    return {
        "client_id": str(defaults.get("client_id") or "0000"),
        "assignee_account_id": str(
            assignee.get("account_id") or policy.get("default_assignee_account_id") or ""
        ),
    }


def load_recent_epics(repo_root: Path) -> list[dict[str, object]]:
    path = repo_root / CONFIG_ROOT_DIRNAME / ASSETS_DIRNAME / GLOBAL_DIRNAME / "epic-list.yaml"
    text = read_profile(path)
    lines = text.splitlines()
    in_recent = False
    epics: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for line in lines:
        if not in_recent:
            if re.match(r"^\s*recent_epics:\s*$", line):
                in_recent = True
            continue
        if in_recent and re.match(r"^\S", line):
            break

        m_key = re.match(r"^\s*-\s*key:\s*([A-Z]+-\d+)\s*$", line)
        if m_key:
            if current:
                epics.append(current)
            current = {"key": m_key.group(1), "title": "", "components": []}
            continue
        if current is None:
            continue

        m_title = re.match(r"^\s*title:\s*(.+?)\s*$", line)
        if m_title:
            current["title"] = m_title.group(1).strip().strip('"').strip("'")
            continue

        m_comps = re.match(r"^\s*components:\s*\[(.*)\]\s*$", line)
        if m_comps:
            raw = m_comps.group(1).strip()
            if not raw:
                current["components"] = []
            else:
                current["components"] = [c.strip().strip('"').strip("'") for c in raw.split(",") if c.strip()]

    if current:
        epics.append(current)
    return epics
