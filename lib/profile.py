from __future__ import annotations

import os
import re
from pathlib import Path

CONFIG_ROOT_DIRNAME = "config"
ASSETS_DIRNAME = "assets"
GLOBAL_DIRNAME = "global"


def resolve_profile_path(repo_root: Path) -> Path:
    """Resolve the canonical workspace profile path."""
    return repo_root / CONFIG_ROOT_DIRNAME / ASSETS_DIRNAME / GLOBAL_DIRNAME / "profile.yaml"


def profile_value(profile_text: str, key: str) -> str:
    match = re.search(
        rf"^\s*{re.escape(key)}\s*:\s*[\"']?([^\"'#\n]+)[\"']?\s*(?:#|$)",
        profile_text,
        re.MULTILINE,
    )
    return match.group(1).strip().strip('"').strip("'") if match else ""


def read_profile(profile_path: Path) -> str:
    if not profile_path.is_file():
        raise RuntimeError(f"Profile not found: {profile_path}")
    return profile_path.read_text(encoding="utf-8")


def load_atlassian_profile(profile_path: Path) -> dict[str, str]:
    text = read_profile(profile_path)
    base_url = profile_value(text, "confluence_base_url").rstrip("/")
    space_id = profile_value(text, "confluence_space_id")
    parent_id = profile_value(text, "confluence_parent_id")
    account_id = profile_value(text, "account_id")
    email = profile_value(text, "email") or os.environ.get("CONFLUENCE_EMAIL", "")
    return {
        "base_url": base_url,
        "space_id": space_id,
        "parent_id": parent_id,
        "account_id": account_id,
        "email": email,
    }


def load_workspace_profile(profile_path: Path) -> dict[str, str]:
    """Load Atlassian profile plus workspace-level defaults used by Jira scripts."""
    text = read_profile(profile_path)
    base = load_atlassian_profile(profile_path)
    default_project = profile_value(text, "default_project")
    return {
        **base,
        "default_project": default_project,
    }
