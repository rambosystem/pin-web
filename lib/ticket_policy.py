from __future__ import annotations

import re
from pathlib import Path

from lib.profile import CONFIG_ROOT_DIRNAME


def _strip_quotes(value: str) -> str:
    v = value.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v


def _parse_simple_yaml_map(text: str) -> dict:
    """
    Parse a restricted YAML mapping (dict-only, scalar leaf values).
    Supports the current config/policy/field-mappings.yaml structure without third-party deps.
    """
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        match = re.match(r"^(\s*)([^:\n]+):(?:\s*(.*))?$", line)
        if not match:
            continue

        indent = len(match.group(1))
        key = match.group(2).strip()
        raw_value = (match.group(3) or "").strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if raw_value == "":
            node: dict = {}
            parent[key] = node
            stack.append((indent, node))
        elif raw_value == "{}":
            parent[key] = {}
        else:
            parent[key] = _strip_quotes(raw_value)

    return root


def load_issue_field_mapping(repo_root: Path, project_key: str, issue_type: str) -> dict[str, str]:
    path = repo_root / CONFIG_ROOT_DIRNAME / "policy" / "field-mappings.yaml"
    if not path.is_file():
        raise RuntimeError(f"Policy field mapping not found: {path}")

    raw = _parse_simple_yaml_map(path.read_text(encoding="utf-8"))
    issue_key = issue_type.strip()

    defaults = (((raw.get("defaults") or {}).get(issue_key) or {}).get("fields")) or {}
    projects = raw.get("projects") or {}
    project_node = projects.get(project_key.upper()) or {}
    project_override = ((project_node.get(issue_key) or {}).get("fields")) or {}

    merged = {**defaults, **project_override}
    if not merged:
        raise RuntimeError(
            f"No field mapping for issue type '{issue_type}' in config/policy/field-mappings.yaml"
        )
    return {str(k): str(v) for k, v in merged.items()}
