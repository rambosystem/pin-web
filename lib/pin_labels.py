"""PIN analysis auto-labels for the Defenders team.

Standard / spec: config/policy/CP/analysis-labels.yaml

Controlled-vocabulary VALUES are resolved from the existing authoritative sources
(not duplicated here), matching the workspace rule of keeping one source of truth:
  - module : config/assets/project/CP/components.yaml -> "Defenders components"
  - nature : config/policy/CP/ticket-schema.json -> Story.field_options["Story Type"]

The YAML asset is parsed line-based (no PyYAML), matching the house style used by
scripts/common/ticket_config.load_recent_epics.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

MODULE_FALLBACK = "Other"

# Chinese display names for the nature dimension (presentation only; keys come
# from the CP Story Type field). Kept in sync with analysis-labels.yaml.
NATURE_ZH = {
    "New Feature": "新功能",
    "Improvement": "优化增强",
    "API Integration & Enablement": "集成接口",
}

_COMPONENTS_REL = ("config", "assets", "project", "CP", "components.yaml")
_SCHEMA_REL = ("config", "policy", "CP", "ticket-schema.json")


def load_defenders_modules(repo_root: Path) -> list[str]:
    """Parse the 'Defenders components' block from components.yaml."""
    path = repo_root.joinpath(*_COMPONENTS_REL)
    if not path.is_file():
        return []
    modules: list[str] = []
    in_block = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not in_block:
            if re.match(r"^\s*Defenders components:\s*$", line):
                in_block = True
            continue
        # A new top-level (non-indented) key ends the block.
        if re.match(r"^\S", line):
            break
        m = re.match(r"^\s*-\s*name:\s*(.+?)\s*$", line)
        if m:
            name = m.group(1).strip().strip('"').strip("'")
            if name:
                modules.append(name)
    return modules


def load_natures(repo_root: Path) -> list[str]:
    """Read Story Type options from the CP ticket schema so PIN 'nature' labels
    stay aligned with the CP Story Type field."""
    fallback = list(NATURE_ZH.keys())
    path = repo_root.joinpath(*_SCHEMA_REL)
    if not path.is_file():
        return fallback
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        opts = (
            schema.get("issue_types", {})
            .get("Story", {})
            .get("field_options", {})
            .get("Story Type", [])
        )
        values = [str(v).strip() for v in opts if str(v).strip()]
        return values or fallback
    except (json.JSONDecodeError, OSError):
        return fallback


def load_label_vocab(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return (modules, natures) controlled vocabularies."""
    return load_defenders_modules(repo_root), load_natures(repo_root)


def build_labels_prompt_block(modules: list[str], natures: list[str]) -> str:
    """Instruction appended to the analysis system prompt so the model emits a
    controlled-vocabulary ``labels`` object. Returns '' when the module vocab
    could not be loaded (degrade gracefully to no labels)."""
    if not modules:
        return ""
    nature_parts = "、".join(
        f"{n}（{NATURE_ZH[n]}）" if n in NATURE_ZH else n for n in natures
    )
    return (
        "另外，请在同一个 JSON 中追加一个 \"labels\" 对象，对该 PIN 打标供 Defenders 团队 triage，"
        '形如 {"module":"...","nature":"..."}。'
        "module（单选，必填）：该需求归属的 Defenders 产品模块，只能取以下之一——"
        + "、".join(modules)
        + f"；不属于以上任何模块或无法判断时填\"{MODULE_FALLBACK}\"。"
        "nature（单选，必填）：需求性质，对齐 CP Story Type，只能取——"
        + nature_parts
        + "。"
    )


def _canon(value: str, allowed: list[str]) -> str:
    """Case/space-insensitive match of value to a canonical allowed value, '' if none."""
    v = re.sub(r"\s+", " ", (value or "").strip())
    if not v:
        return ""
    norm = v.casefold()
    for a in allowed:
        if re.sub(r"\s+", " ", a).casefold() == norm:
            return a
    return ""


def normalize_labels(raw: object, modules: list[str], natures: list[str]) -> dict[str, str]:
    """Validate the model's labels object against the controlled vocab.
    Unknown module -> fallback; unknown nature -> empty string."""
    d = raw if isinstance(raw, dict) else {}
    module = _canon(str(d.get("module") or ""), modules) or MODULE_FALLBACK
    nature = _canon(str(d.get("nature") or ""), natures)
    return {"module": module, "nature": nature}
