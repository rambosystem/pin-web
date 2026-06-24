"""Jira Cloud Forms (ProForma) REST API helpers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from lib.http import request_json

FORMS_API_BASE = "https://api.atlassian.com/jira/forms/cloud"
FORMS_INSECURE_SSL = "JIRA_FORMS_INSECURE_SSL"
DEFAULT_INTAKE_FORM_NAME = "Feature Request Intake Form"


def forms_headers(auth: str) -> dict[str, str]:
    return {
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
        "X-ExperimentalApi": "opt-in",
    }


def get_cloud_id(site_base_url: str, auth: str) -> str:
    """Resolve Atlassian cloud ID from the Jira site URL."""
    url = f"{site_base_url.rstrip('/')}/_edge/tenant_info"
    data = request_json(
        url,
        headers=forms_headers(auth),
        insecure_env_var=FORMS_INSECURE_SSL,
    )
    cloud_id = data.get("cloudId") if isinstance(data, dict) else None
    if not cloud_id:
        raise RuntimeError("Could not resolve cloudId from tenant_info.")
    return str(cloud_id)


def list_issue_forms(cloud_id: str, issue_key: str, auth: str) -> list[dict[str, Any]]:
    url = f"{FORMS_API_BASE}/{cloud_id}/issue/{issue_key}/form"
    data = request_json(
        url,
        headers=forms_headers(auth),
        insecure_env_var=FORMS_INSECURE_SSL,
    )
    if not isinstance(data, list):
        return []
    return data


def get_issue_form(cloud_id: str, issue_key: str, form_id: str, auth: str) -> dict[str, Any]:
    url = f"{FORMS_API_BASE}/{cloud_id}/issue/{issue_key}/form/{form_id}"
    data = request_json(
        url,
        headers=forms_headers(auth),
        insecure_env_var=FORMS_INSECURE_SSL,
    )
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected form response for {issue_key} form {form_id}.")
    return data


def _forms_write_headers(auth: str) -> dict[str, str]:
    headers = forms_headers(auth)
    headers["Content-Type"] = "application/json"
    return headers


def save_issue_form_answers(
    cloud_id: str, issue_key: str, form_id: str, answers: dict[str, Any], auth: str
) -> dict[str, Any]:
    """PUT form answers (save without submitting). ``answers`` is keyed by qid."""
    url = f"{FORMS_API_BASE}/{cloud_id}/issue/{issue_key}/form/{form_id}"
    data = request_json(
        url,
        method="PUT",
        headers=_forms_write_headers(auth),
        data={"answers": answers},
        insecure_env_var=FORMS_INSECURE_SSL,
    )
    return data if isinstance(data, dict) else {}


def submit_issue_form(cloud_id: str, issue_key: str, form_id: str, auth: str) -> dict[str, Any]:
    """Submit a form (validates visible required answers server-side)."""
    url = f"{FORMS_API_BASE}/{cloud_id}/issue/{issue_key}/form/{form_id}/action/submit"
    data = request_json(
        url,
        method="PUT",
        headers=_forms_write_headers(auth),
        data={},
        insecure_env_var=FORMS_INSECURE_SSL,
    )
    return data if isinstance(data, dict) else {}


def find_form_summary(forms: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for form in forms:
        if (form.get("name") or "").strip() == name:
            return form
    return None


def get_issue_form_by_name(
    site_base_url: str,
    auth: str,
    issue_key: str,
    form_name: str = DEFAULT_INTAKE_FORM_NAME,
    *,
    cloud_id: str | None = None,
) -> dict[str, Any] | None:
    """Return full form payload (design + state.answers) or None if not found."""
    cid = cloud_id or get_cloud_id(site_base_url, auth)
    summaries = list_issue_forms(cid, issue_key, auth)
    summary = find_form_summary(summaries, form_name)
    if not summary:
        return None
    form_id = summary.get("id")
    if not form_id:
        return None
    return get_issue_form(cid, issue_key, str(form_id), auth)


def adf_to_plain_text(node: Any) -> str:
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_plain_text(item) for item in node)
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type")
    if node_type == "text":
        return node.get("text") or ""
    if node_type == "hardBreak":
        return "\n"

    parts: list[str] = []
    for child in node.get("content") or []:
        parts.append(adf_to_plain_text(child))

    text = "".join(parts)
    if node_type in ("paragraph", "heading"):
        return text + "\n"
    if node_type == "listItem":
        return text
    if node_type == "bulletList":
        items = node.get("content") or []
        lines = []
        for item in items:
            line = adf_to_plain_text(item).strip()
            if line:
                lines.append(f"- {line}")
        return "\n".join(lines) + ("\n" if lines else "")
    return text


def _choice_label_by_id(choices: list[dict[str, Any]], choice_id: str) -> str | None:
    for choice in choices:
        if str(choice.get("id")) == choice_id:
            return choice.get("label")
        for child in choice.get("children") or []:
            found = _choice_label_by_id([child], choice_id)
            if found:
                parent = choice.get("label") or ""
                return f"{parent} > {found}" if parent else found
    return None


def _resolve_cascading_choice(choices: list[dict[str, Any]], raw: str) -> str:
    """Resolve values like '14441:14468' (parent:child)."""
    parts = str(raw).split(":")
    labels: list[str] = []
    pool = choices
    for part in parts:
        label = _choice_label_by_id(pool, part)
        if not label:
            labels.append(part)
            continue
        if " > " in label:
            labels.append(label)
            pool = []
        else:
            labels.append(label)
            for choice in pool:
                if str(choice.get("id")) == part:
                    pool = choice.get("children") or []
                    break
    return " > ".join(labels) if labels else raw


def _format_answer(question: dict[str, Any], answer: dict[str, Any]) -> str:
    if not answer:
        return ""

    text = (answer.get("text") or "").strip()
    if text:
        return text

    adf = answer.get("adf")
    if adf:
        return adf_to_plain_text(adf).strip()

    choices = question.get("choices") or []
    selected = answer.get("choices") or []
    if selected:
        labels: list[str] = []
        q_type = question.get("type") or ""
        for raw in selected:
            raw_s = str(raw)
            if q_type == "cc":
                labels.append(_resolve_cascading_choice(choices, raw_s))
            else:
                label = _choice_label_by_id(choices, raw_s)
                labels.append(label or raw_s)
        return ", ".join(labels)

    users = answer.get("users") or []
    if users:
        return ", ".join(str(u) for u in users)

    files = answer.get("files") or []
    if files:
        return f"{len(files)} attachment(s)"

    return ""


def form_answers_as_dict(form_detail: dict[str, Any]) -> dict[str, str]:
    """Map question label -> plain-text answer."""
    design = form_detail.get("design") or {}
    questions = design.get("questions") or {}
    answers = (form_detail.get("state") or {}).get("answers") or {}

    result: dict[str, str] = {}
    for qid, answer in answers.items():
        question = questions.get(str(qid)) or questions.get(qid)
        if not question:
            continue
        label = (question.get("label") or f"Q{qid}").strip()
        formatted = _format_answer(question, answer)
        if formatted:
            result[label] = formatted
    return result


def format_form_for_llm(form_detail: dict[str, Any]) -> str:
    """All answered fields (debug / export)."""
    design = form_detail.get("design") or {}
    form_name = (design.get("settings") or {}).get("name") or "Form"
    fields = form_answers_as_dict(form_detail)
    if not fields:
        return ""

    lines = [f"=== {form_name} ==="]
    for label, value in fields.items():
        lines.append(f"{label}:\n{value}")
    return "\n\n".join(lines)


# Intake form labels (Jira) -> sections for LLM / report (ordered).
INTAKE_REQUIREMENT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Define the problem", "问题"),
    ("Supporting Context / Customer Insights", "背景与客户洞察"),
    ("Define the possible solution", "需求详情"),
    ("Business Outcome", "业务目标"),
)

INTAKE_CONTEXT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Client(s)", "客户"),
    ("Retailer/Platform", "平台"),
    ("Prooduct Feature", "产品模块"),
    ("Urgency", "紧急度"),
)

# Metadata / workflow fields — excluded from LLM requirement payload.
INTAKE_EXCLUDED_LABELS = frozenset(
    {
        "Intake Type",
        "Customer Commitments?",
        "What commitments were made?",
        "Are there any business constraints around delivery timelines?",
        "Requested completion date ",
        "Requested completion date",
        "Attachments",
        "Watchers",
    }
)


def normalize_form_text(text: str) -> str:
    """Normalize whitespace and common punctuation for stable LLM input."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_clean_intake_requirements(form_detail: dict[str, Any]) -> str:
    """
    Extract requirement-focused plain text for LLM (no intake metadata noise).
    """
    fields = form_answers_as_dict(form_detail)
    if not fields:
        return ""

    sections: list[str] = []

    for form_label, section_title in INTAKE_REQUIREMENT_SECTIONS:
        value = normalize_form_text(fields.get(form_label, ""))
        if value:
            sections.append(f"【{section_title}】\n{value}")

    context_parts: list[str] = []
    for form_label, short_label in INTAKE_CONTEXT_SECTIONS:
        value = normalize_form_text(fields.get(form_label, ""))
        if value:
            context_parts.append(f"{short_label}: {value}")
    if context_parts:
        sections.append("【上下文】\n" + "; ".join(context_parts))

    return "\n\n".join(sections)


def build_clean_intake_fields(form_detail: dict[str, Any]) -> dict[str, str]:
    """Structured clean fields (Chinese keys) for storage/debug."""
    fields = form_answers_as_dict(form_detail)
    out: dict[str, str] = {}
    for form_label, section_title in INTAKE_REQUIREMENT_SECTIONS + INTAKE_CONTEXT_SECTIONS:
        value = normalize_form_text(fields.get(form_label, ""))
        if value:
            out[section_title] = value
    return out


def get_intake_form_text(
    site_base_url: str,
    auth: str,
    issue_key: str,
    form_name: str = DEFAULT_INTAKE_FORM_NAME,
) -> str:
    """Fetch intake form and return full plain text; empty if unavailable."""
    try:
        form = get_issue_form_by_name(site_base_url, auth, issue_key, form_name)
    except Exception:
        return ""
    if not form:
        return ""
    return format_form_for_llm(form)


def get_clean_intake_requirements_text(
    site_base_url: str,
    auth: str,
    issue_key: str,
    form_name: str = DEFAULT_INTAKE_FORM_NAME,
) -> str:
    """Fetch intake form and return cleaned requirement text for LLM."""
    try:
        form = get_issue_form_by_name(site_base_url, auth, issue_key, form_name)
    except Exception:
        return ""
    if not form:
        return ""
    return build_clean_intake_requirements(form)


def build_generic_clean_fields(form_detail: dict[str, Any]) -> dict[str, str]:
    """Generic cleaned label -> value for any form, excluding intake metadata."""
    fields = form_answers_as_dict(form_detail)
    out: dict[str, str] = {}
    for label, value in fields.items():
        if not value:
            continue
        if label in INTAKE_EXCLUDED_LABELS:
            continue
        out[label] = normalize_form_text(value)
    return out


def build_clean_text_from_fields(fields: dict[str, str]) -> str:
    if not fields:
        return ""
    return "\n\n".join(f"【{label}】\n{value}" for label, value in fields.items() if value)


def list_submitted_forms_clean(
    site_base_url: str,
    auth: str,
    issue_key: str,
    *,
    cloud_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return cleaned summaries for every submitted ProForma form on an issue.

    Each item: {form_id, form_name, submitted, lock, updated, fields, clean_text}
    Intake Form uses Chinese section keys; other forms use original labels.
    """
    cid = cloud_id or get_cloud_id(site_base_url, auth)
    try:
        summaries = list_issue_forms(cid, issue_key, auth)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for s in summaries:
        if not s.get("submitted"):
            continue
        form_id = str(s.get("id") or "")
        name = (s.get("name") or "").strip()
        if not form_id:
            continue
        try:
            full = get_issue_form(cid, issue_key, form_id, auth)
        except Exception:
            continue
        if name == DEFAULT_INTAKE_FORM_NAME:
            fields = build_clean_intake_fields(full)
            clean_text = build_clean_intake_requirements(full)
        else:
            fields = build_generic_clean_fields(full)
            clean_text = build_clean_text_from_fields(fields)
        if not fields:
            continue
        out.append(
            {
                "form_id": form_id,
                "form_name": name,
                "submitted": True,
                "lock": bool(s.get("lock")),
                "updated": s.get("updated") or "",
                "fields": fields,
                "clean_text": clean_text,
            }
        )
    return out
