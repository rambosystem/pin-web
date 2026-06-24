"""
FastAPI backend for the PIN Ticket Analysis Web UI.

Directly calls Jira REST + ProForma Forms API; no subprocess calls, no tmp/*.json
reads or writes. Runs at http://127.0.0.1:8765 and serves the built frontend
from web/frontend/dist when present.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.atlassian import basic_auth, jira_api_v3_url  # noqa: E402
from lib.env import load_dotenv  # noqa: E402
from lib.http import request_json, ssl_context  # noqa: E402
from lib.jira_forms import (  # noqa: E402
    DEFAULT_INTAKE_FORM_NAME,
    build_clean_intake_fields,
    build_clean_intake_requirements,
    form_answers_as_dict,
    get_cloud_id,
    get_issue_form,
    get_issue_form_by_name,
    list_issue_forms,
    list_submitted_forms_clean,
    save_issue_form_answers,
    submit_issue_form,
)
from lib.pin_labels import (  # noqa: E402
    build_labels_prompt_block,
    load_label_vocab,
    normalize_labels,
)
from lib.profile import load_atlassian_profile, resolve_profile_path  # noqa: E402

DIST_DIR = SCRIPT_DIR / "frontend" / "dist"
CACHE_DIR = SCRIPT_DIR / "cache"
PIN_CACHE_FILE = CACHE_DIR / "pin_cache.json"

DEFAULT_LLM_MODEL = "deepseek-v4-pro"
DEFAULT_ANALYSIS_MODEL = "deepseek-v4-pro"
DEFAULT_TRANSLATE_MODEL = "deepseek-v4-flash"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/"

DEFAULT_STATUSES = ("Backlog", "Ready for Technical Review", "Accepted for Development")

ANALYSIS_KEYS = ("form_request", "problem", "background", "impact", "expectation")


def _coerce_field_text(val: Any) -> str:
    """Normalize one analysis field to a markdown string.

    The model occasionally returns a field as a JSON array (e.g. when asked to
    output a list) or other non-string types instead of a string. Coerce arrays
    into markdown bullets and everything else via str(), so the parse never
    assumes .strip() on a str.
    """
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        parts = [str(x).strip() for x in val if str(x).strip()]
        return "\n".join(f"- {p}" for p in parts)
    if val is None:
        return ""
    return str(val).strip()

ANALYZE_SYSTEM_PROMPT = (
    "你是资深产品需求评审专家，为 PIN（Product Incoming Need）工单做结构化分析，供产品/技术评审快速决策。"
    "输入包含 Jira issue 的 summary/description，以及（若有）已清洗的 Feature Request Intake Form 需求正文。"
    "有表单时，以表单【问题】【需求详情】【业务目标】作为诉求与口径的主依据；但 description 中独有的具体事实（客户名、数量、频率、复现场景、链接、数据）仍须照常采纳，不得因表单优先而丢弃。无表单时基于 summary/description 分析。"
    "请只输出 JSON："
    '{"form_request":"...","problem":"...","background":"...","impact":"...","expectation":"..."}。'
    "全部字段一律用中文输出，无论输入是英文、中文还是中英混杂、含大量产品行话；但产品名、模块名、专有缩写（如 OOB、SaaS、SOV、ASIN、ROI 等）保留原文英文、不要直译。核心要求："
    "(1) 做提炼、归因和判断，而非复述原文——拒绝空泛套话；归因须有原文/表单依据，个别工单依据确实不足时直接点明缺口（如「缺少 X，暂无法判断根因」），不要用看似具体实则无据的结论填充——「不空泛」不等于可编造；"
    "(2) 区分「原文/表单事实」与「你的推断」：凡原文未明确写出、由你归因或推理得出的结论（尤其根因、影响判断、动机）须在该句紧随处标「（推断）」；能直接引到原文的内容不加标注，不得无依据杜撰；"
    "(3) 你只能读到文本（summary/description/表单正文）；原文中的图片、截图、附件、表格图片你都看不到。仅当某字段的关键信息明显只存在于这些看不到的内容、且现有文本不足以判断时，该字段填\"暂无描述（关键信息在图片/附件中）\"，不要据标题臆测；文本已足够的字段照常正常分析；"
    "(4) 用 Markdown 提升可读性、但按需克制：遇到明显并列的内容（如多个待澄清点、「不做/做」的对比、并列的影响项）用「- 」列表分行；单一结论用一两句话即可，不要逢句分点。仅对少数关键词 **加粗**，不要逢词加粗。每个字段简洁聚焦，避免长段落；"
    "(5) 确实缺乏依据的字段填\"暂无描述\"，不要硬凑；若 summary/description 与表单合计几乎无有效信息，不要靠「（推断）」凑满字段，并在 expectation 的待澄清点中指出原始信息不足、需补充背景后再评审。"
    "各字段含义："
    "form_request——忠实概括用户在 Intake Form 中提交的原始诉求（要什么、为什么），2-5 句；有表单时不得仅复述 description。"
    "problem——要解决的真正产品问题，采用与 impact 相同的分组格式：分「表象」「根因」「影响」三组，每组先写一行粗体标题（**表象** / **根因** / **影响**），标题单独成行、其后空一行再用「- 」列出要点，组与组之间也必须空一行——务必保证每个粗体标题前都有空行，否则标题会被并进上一条要点。根因多属推断，按规则标「（推断）」。每条一句话、精简。"
    "background——上下文：涉及哪些客户/角色/场景、触发条件、为何现在提、相关已有功能或历史；原文有客户名/数量/频率等具体信息就如实写出，没有则不必强求、不要编造。"
    "impact——业务影响，分「不做的代价」与「做了的收益」两组呈现。每组先写一行粗体标题（**不做的代价** / **做了的收益**），标题单独成行、其后空一行再用「- 」列出该组要点；两组之间也必须空一行——务必保证每个粗体标题前都有空行，否则标题会被并进上一条要点。每条要点只讲一个核心点、一句话、精简，每组 1-2 条。落到留存/收入/效率/竞品等维度；只有原文/表单确有数据时才引用具体数字，否则给出定性判断，不要堆砌「可能…」空话、更不得编造数字。本字段属前瞻判断、整体即推断，不必逐条标「（推断）」。"
    "expectation——采用与 impact 相同的分组格式：分「期望结果」「可验收标准」「待澄清点」三组（确无内容的组可省略），每组先写一行粗体标题（**期望结果** / **可验收标准** / **待澄清点**），标题单独成行、其后空一行再用「- 」列出要点，组与组之间也必须空一行——务必保证每个粗体标题前都有空行，否则标题会被并进上一条要点。每条一句话、精简，待澄清点逐条列出。"
)

# Controlled-vocabulary auto-labels (Defenders team). Vocab resolves from
# config assets at import time; see scripts/common/pin_labels.py and
# config/policy/CP/analysis-labels.yaml. Empty modules -> labels disabled.
_LABEL_MODULES, _LABEL_NATURES = load_label_vocab(SCRIPT_DIR)
ANALYZE_SYSTEM_PROMPT_FULL = ANALYZE_SYSTEM_PROMPT + build_labels_prompt_block(
    _LABEL_MODULES, _LABEL_NATURES
)

AI_DRAFT_SYSTEM_PROMPT = (
    "You are an assistant who drafts concise, professional Jira comments for "
    "a PIN (Product Incoming Need) ticket. Use the provided ticket context and "
    "the user's instruction to write a single comment body. "
    "Reply in English by default. Only switch to Chinese when the user's "
    "instruction is written in Chinese or explicitly asks for a Chinese reply. "
    "Output plain text only — no markdown headings, no code fences, no JSON. "
    "Keep it focused and actionable; avoid restating context the reader already "
    "sees in the ticket."
)

ASSESSMENT_EXPLAIN_SYSTEM_PROMPT = (
    "You are a Technical Program Manager writing the 'Add a short explanation' "
    "field of a PIN (Product Incoming Need) ticket's Technical Assessment Form. "
    "This text is read by the PIN Reporter — write it as a brief, direct reply "
    "to them (1-3 sentences) explaining the assessment of their request: what "
    "the conclusion is and, briefly, why or what happens next. "
    "Ground it in the substance of the PIN discussion provided, but write the "
    "reply itself — NEVER describe or critique the discussion. Do not write "
    "meta-statements such as 'the comment only notes…', 'no technical details "
    "were provided', or any remark about what information is or isn't present; "
    "simply state the assessment to the reporter. Do not invent specifics that "
    "are not supported. Professional and concise; match the language the "
    "discussion predominantly uses. Output plain text only: no markdown, no "
    "headings, no preamble, no surrounding quotes."
)

load_dotenv(SCRIPT_DIR / ".env")

app = FastAPI(title="PIN Ticket Analysis", version="0.1.0")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_PROFILE_CACHE: dict[str, str] | None = None
_CLOUD_ID_CACHE: str | None = None

# Unified per-PIN cache, persisted to PIN_CACHE_FILE.
# Structure: { "PIN-xxx": { "analysis": {"result": {...}, "ts": float},
#                            "form": {"result": {...}, "ts": float},
#                            "translations": {"description": "...", "problem": "...", ...} } }
_PIN_CACHE: dict[str, dict[str, Any]] = {}
_ANALYSIS_CACHE_TTL = 3600 * 24 * 7  # 7 days
_FORM_CACHE_TTL = 3600 * 24 * 1     # 1 day


def _load_pin_cache() -> None:
    global _PIN_CACHE
    if not PIN_CACHE_FILE.exists():
        # Migrate legacy flat translate_cache if it exists
        legacy = CACHE_DIR / "translate_cache.json"
        if legacy.exists():
            try:
                flat: dict[str, str] = json.loads(legacy.read_text(encoding="utf-8"))
                for k, v in flat.items():
                    parts = k.split(":")  # "PIN-xxx:field:lang"
                    if len(parts) == 3:
                        pin_key, field, _lang = parts
                        _PIN_CACHE.setdefault(pin_key, {}).setdefault("translations", {})[field] = v
                _save_pin_cache()
            except Exception:
                pass
        return
    try:
        raw = json.loads(PIN_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            _PIN_CACHE = raw
    except Exception:
        pass


def _save_pin_cache() -> None:
    # Atomic write: serialize to a temp file in the same dir, then os.replace
    # so a crash mid-write can never corrupt the existing cache file.
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PIN_CACHE_FILE.with_suffix(PIN_CACHE_FILE.suffix + ".tmp")
        tmp.write_text(
            json.dumps(_PIN_CACHE, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, PIN_CACHE_FILE)
    except Exception:
        pass


_load_pin_cache()


def _fix_mojibake(text: str) -> str:
    """Reverse Windows-1252-as-UTF-8 double encoding.

    Older code decoded Jira API responses as CP1252 instead of UTF-8, then
    stored the garbled string.  We reverse by mapping each character back to
    its original byte: CP1252-defined chars (0x80-0x9F) via an explicit table,
    everything in U+0000-U+00FF via its byte value.  If the resulting bytes
    decode as valid UTF-8 and differ from the input, the string was corrupted.
    """
    if not text:
        return text
    # CP1252 defines extra mappings in the 0x80-0x9F range that differ from
    # Latin-1.  Python’s cp1252 codec raises UnicodeEncodeError for the
    # undefined slots (0x81/8D/8F/90/9D), so we use a manual table keyed by
    # Unicode codepoint instead.
    _cp1252_extra: dict[int, int] = {
        0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84,
        0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87, 0x02C6: 0x88,
        0x2030: 0x89, 0x0160: 0x8A, 0x2039: 0x8B, 0x0152: 0x8C,
        0x017D: 0x8E, 0x2018: 0x91, 0x2019: 0x92, 0x201C: 0x93,
        0x201D: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97,
        0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A, 0x203A: 0x9B,
        0x0153: 0x9C, 0x017E: 0x9E, 0x0178: 0x9F,
    }
    try:
        raw = bytearray()
        for ch in text:
            cp = ord(ch)
            if cp < 0x80:
                raw.append(cp)
            elif cp in _cp1252_extra:
                raw.append(_cp1252_extra[cp])
            elif cp <= 0xFF:
                # Latin-1 range — also covers the undefined CP1252 slots
                # (0x81/8D/8F/90/9D) which Python decoded to the same codepoint.
                raw.append(cp)
            else:
                # Codepoint outside CP1252 range means the string is not pure
                # mojibake; leave it unchanged.
                return text
        fixed = bytes(raw).decode("utf-8")
        return fixed if fixed != text else text
    except (ValueError, UnicodeDecodeError):
        return text


def _fix_form_result_encoding(result: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a cached form result with mojibake repaired."""
    result = dict(result)
    if "clean_requirements_text" in result:
        result["clean_requirements_text"] = _fix_mojibake(
            result.get("clean_requirements_text") or ""
        )
    if isinstance(result.get("clean_fields"), dict):
        result["clean_fields"] = {
            k: _fix_mojibake(v) if isinstance(v, str) else v
            for k, v in result["clean_fields"].items()
        }
    return result


def _profile() -> dict[str, str]:
    global _PROFILE_CACHE
    if _PROFILE_CACHE is None:
        _PROFILE_CACHE = load_atlassian_profile(resolve_profile_path(SCRIPT_DIR))
    return _PROFILE_CACHE


def _jira_url_for(key: str) -> str:
    base = (_profile().get("base_url") or "").rstrip("/")
    return f"{base}/browse/{key}" if base else f"/browse/{key}"


def _jira_auth() -> str:
    profile = _profile()
    email = profile.get("email") or ""
    token = (
        os.environ.get("JIRA_API_TOKEN")
        or os.environ.get("ATLASSIAN_API_TOKEN")
        or os.environ.get("CONFLUENCE_API_TOKEN")
    )
    if not token:
        raise HTTPException(500, "ATLASSIAN_API_TOKEN (or JIRA_API_TOKEN) is required")
    if not email:
        raise HTTPException(500, "Profile email is required for Jira auth")
    return basic_auth(email, token)


_CLOUD_ID_CACHE: str | None = None


def _cloud_id() -> str:
    global _CLOUD_ID_CACHE
    if _CLOUD_ID_CACHE:
        return _CLOUD_ID_CACHE
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    try:
        _CLOUD_ID_CACHE = get_cloud_id(base, _jira_auth())
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-500:]
        except Exception:
            pass
        raise HTTPException(502, f"Failed to resolve cloud_id: {detail or exc.reason}") from exc
    except Exception as exc:
        raise HTTPException(502, f"Failed to resolve cloud_id: {exc}") from exc
    return _CLOUD_ID_CACHE


def _adf_extract_media(node: Any) -> list[dict[str, Any]]:
    """Recursively collect media (image/attachment) items from an ADF tree.

    Each item: ``{"media_id": str, "type": "file"|"link", "width": int|None, "height": int|None,
    "filename": str|None, "alt": str|None}``.
    """
    if node is None:
        return []
    if isinstance(node, list):
        items: list[dict[str, Any]] = []
        for n in node:
            items.extend(_adf_extract_media(n))
        return items
    if not isinstance(node, dict):
        return []
    items: list[dict[str, Any]] = []
    node_type = node.get("type")
    if node_type == "media":
        attrs = node.get("attrs") or {}
        media_id = attrs.get("id")
        if media_id:
            items.append({
                "media_id": str(media_id),
                "type": attrs.get("type") or "file",
                "width": attrs.get("width"),
                "height": attrs.get("height"),
                "filename": attrs.get("fileName") or attrs.get("alt") or None,
                "alt": attrs.get("alt") or attrs.get("fileName") or "",
            })
    # recurse into children
    for child in (node.get("content") or []):
        items.extend(_adf_extract_media(child))
    return items


def _resolve_media_attachment_ids(
    media_items: list[dict[str, Any]], issue_attachments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Replace temporary media UUIDs with permanent Jira attachment IDs.

    Jira Cloud ADF ``media`` nodes reference temporary UUIDs.  To serve the
    image we need the numeric attachment ID from the issue's attachment list.
    Matching is by filename; if no match is found the original temp ID is kept
    (the proxy will still try a fallback URL).
    """
    if not media_items or not issue_attachments:
        return media_items
    # Build a map: filename → permanent attachment ID
    name_to_id: dict[str, str] = {}
    for att in issue_attachments:
        att_id = str(att.get("id") or "")
        fname = att.get("filename") or ""
        if att_id and fname:
            name_to_id[fname] = att_id
    if not name_to_id:
        return media_items
    resolved: list[dict[str, Any]] = []
    for m in media_items:
        fname = m.get("filename") or m.get("alt") or ""
        perm_id = name_to_id.get(fname)
        if perm_id:
            m = dict(m)
            m["media_id"] = perm_id
        resolved.append(m)
    return resolved


def _adf_to_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, list):
        return "".join(_adf_to_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    if node_type == "media":
        return ""  # rendered separately via media_items, no text placeholder needed
    if node_type == "mediaSingle":
        return _adf_to_text(node.get("content"))  # delegate to inner media node
    if node_type == "mediaGroup":
        return _adf_to_text(node.get("content"))
    inner = _adf_to_text(node.get("content"))
    if node_type == "text":
        txt = node.get("text") or ""
        # Preserve hyperlinks as Markdown so the comment renderer keeps them clickable.
        href = None
        for mark in node.get("marks") or []:
            if mark.get("type") == "link":
                href = (mark.get("attrs") or {}).get("href")
                break
        if href and txt and txt != href:
            return f"[{txt}]({href})" + inner
        return (href or txt) + inner
    if node_type in ("inlineCard", "blockCard", "embedCard"):
        # Smart links: emit the raw URL; the renderer auto-links it.
        attrs = node.get("attrs") or {}
        url = attrs.get("url") or ((attrs.get("data") or {}).get("url") or "")
        return url + inner
    if node_type == "hardBreak":
        return "\n"
    if node_type in ("paragraph", "heading", "codeBlock"):
        return inner + "\n"
    if node_type == "listItem":
        return "- " + inner.rstrip("\n") + "\n"
    if node_type == "mention":
        attrs = node.get("attrs") or {}
        text = attrs.get("text") or attrs.get("displayName") or ""
        if not text.startswith("@"):
            text = "@" + text
        return text + inner
    return inner


def _text_with_mentions(line: str, mentions: dict[str, str]) -> list[dict[str, Any]]:
    if not line:
        return []
    if not mentions:
        return [{"type": "text", "text": line}]
    names = sorted(mentions.keys(), key=len, reverse=True)
    parts: list[dict[str, Any]] = []
    i = 0
    n = len(line)
    while i < n:
        if line[i] == "@":
            matched: str | None = None
            for name in names:
                if not name:
                    continue
                end = i + 1 + len(name)
                if end <= n and line[i + 1 : end] == name:
                    matched = name
                    break
            if matched:
                parts.append(
                    {
                        "type": "mention",
                        "attrs": {
                            "id": mentions[matched],
                            "text": f"@{matched}",
                        },
                    }
                )
                i += 1 + len(matched)
                continue
        if parts and parts[-1].get("type") == "text":
            parts[-1]["text"] += line[i]
        else:
            parts.append({"type": "text", "text": line[i]})
        i += 1
    return parts


# Bare http(s) URL; trailing sentence punctuation is trimmed off separately.
_URL_RE = re.compile(r"https?://[^\s<>]+")


def _split_trailing_punct(url: str) -> tuple[str, str]:
    trailing = ""
    while url and url[-1] in ".,;:!?\"')]}":
        trailing = url[-1] + trailing
        url = url[:-1]
    return url, trailing


def _inline_with_mentions(line: str, mentions: dict[str, str]) -> list[dict[str, Any]]:
    """Build inline ADF nodes from a line: URLs become smart-link inlineCards,
    @names become mention nodes, everything else is plain text."""
    if not line:
        return []
    parts: list[dict[str, Any]] = []
    last = 0
    for match in _URL_RE.finditer(line):
        url, trailing = _split_trailing_punct(match.group(0))
        if not url:
            continue
        if match.start() > last:
            parts.extend(_text_with_mentions(line[last : match.start()], mentions))
        parts.append({"type": "inlineCard", "attrs": {"url": url}})
        if trailing:
            parts.extend(_text_with_mentions(trailing, mentions))
        last = match.end()
    if last < len(line):
        parts.extend(_text_with_mentions(line[last:], mentions))
    return parts


def _text_to_adf(
    text: str, mentions: dict[str, str] | None = None
) -> dict[str, Any]:
    cleaned = (text or "").replace("\r\n", "\n").strip()
    if not cleaned:
        raise HTTPException(400, "Comment body cannot be empty")
    mention_map = mentions or {}
    paragraphs: list[dict[str, Any]] = []
    for chunk in cleaned.split("\n\n"):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        lines = chunk.split("\n")
        content: list[dict[str, Any]] = []
        for i, line in enumerate(lines):
            if i > 0:
                content.append({"type": "hardBreak"})
            content.extend(_inline_with_mentions(line, mention_map))
        if content:
            paragraphs.append({"type": "paragraph", "content": content})
    if not paragraphs:
        paragraphs = [
            {"type": "paragraph", "content": [{"type": "text", "text": cleaned}]}
        ]
    return {"type": "doc", "version": 1, "content": paragraphs}


def _llm_request_payload(
    system: str, user: str, *, max_tokens: int, temperature: float, stream: bool,
    model: str | None = None,
) -> tuple[str, dict[str, str], bytes]:
    """Resolve API key/URL/model and build the OpenAI-compatible request body.

    Centralised so streaming and non-streaming calls stay in sync (model,
    temperature, system+user wiring, headers).
    """
    api_key = os.environ.get("DEEPSEEK_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(500, "DEEPSEEK_KEY env var is required for AI draft")
    base_url = (os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_LLM_BASE_URL).rstrip("/")
    resolved_model = model or os.environ.get("PIN_REPORT_LLM_MODEL", DEFAULT_LLM_MODEL)
    url = f"{base_url}/chat/completions"
    payload: dict[str, Any] = {
        "model": resolved_model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if stream:
        payload["stream"] = True
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if stream:
        headers["Accept"] = "text/event-stream"
    return url, headers, json.dumps(payload).encode("utf-8")


def _llm_chat(system: str, user: str, *, max_tokens: int = 800, temperature: float = 0.4, model: str | None = None) -> str:
    url, headers, body = _llm_request_payload(
        system, user, max_tokens=max_tokens, temperature=temperature, stream=False, model=model,
    )
    try:
        data = request_json(
            url,
            method="POST",
            headers=headers,
            data=json.loads(body),
            insecure_env_var="PIN_REPORT_INSECURE_SSL",
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(502, f"LLM request failed: {detail or exc.reason}") from exc
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise HTTPException(502, "LLM response missing choices")
    content = choices[0].get("message", {}).get("content")
    return (content or "").strip()


def _llm_chat_stream(
    system: str, user: str, *, max_tokens: int = 800, temperature: float = 0.4
):
    """Yield content deltas from the LLM as they arrive (OpenAI-compatible SSE).

    Raises HTTPException on connection/HTTP errors so the endpoint can surface
    a clean error before any tokens reach the client.
    """
    url, headers, body = _llm_request_payload(
        system, user, max_tokens=max_tokens, temperature=temperature, stream=True
    )
    req = Request(url, data=body, method="POST", headers=headers)
    ctx = ssl_context("PIN_REPORT_INSECURE_SSL")
    try:
        resp = urlopen(req, context=ctx)
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(502, f"LLM stream request failed: {detail or exc.reason}") from exc
    except Exception as exc:
        raise HTTPException(502, f"LLM stream connect failed: {exc}") from exc

    try:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line or not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if data_str == "[DONE]":
                break
            try:
                obj = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = (choices[0].get("delta") or {}).get("content")
            if delta:
                yield delta
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _build_ai_draft_user_prompt(
    summary: dict[str, Any],
    user_instruction: str,
    recent_comments: list[dict[str, Any]] | None,
) -> str:
    parts: list[str] = [f"PIN Ticket: {summary.get('key', '')}"]
    if summary.get("status"):
        parts.append(f"Status: {summary['status']}")
    if summary.get("urgency"):
        parts.append(f"Urgency: {summary['urgency']}")
    if summary.get("summary"):
        parts.append(f"Summary: {summary['summary']}")

    analysis = summary.get("analysis") or {}
    analysis_lines = []
    for k, label in [
        ("form_request", "Form Request"),
        ("problem", "Problem"),
        ("background", "Background"),
        ("impact", "Business Impact"),
        ("expectation", "Expectation"),
    ]:
        v = (analysis.get(k) or "").strip()
        if v and v != "暂无描述":
            analysis_lines.append(f"- {label}: {v}")
    if analysis_lines:
        parts.append("\nLLM Analysis:")
        parts.extend(analysis_lines)

    clean = summary.get("clean_fields") or {}
    intake_lines = []
    for k in ["问题", "背景与客户洞察", "需求详情", "业务目标"]:
        v = (clean.get(k) or "").strip()
        if v:
            intake_lines.append(f"- {k}: {v}")
    if intake_lines:
        parts.append("\nIntake Form:")
        parts.extend(intake_lines)

    if recent_comments:
        parts.append("\nRecent comments (oldest → newest):")
        for c in recent_comments[-10:]:
            author = c.get("author") or "Unknown"
            body = (c.get("body_text") or "").strip()
            if not body:
                continue
            parts.append(f"- {author}: {body}")

    parts.append(f"\nUser instruction for the new comment:\n{user_instruction}")
    parts.append("\nWrite the comment body now in plain text:")
    return "\n".join(parts)


def _form_question_order(design: dict[str, Any]) -> list[str]:
    """Return question ids in the form's visual (layout) order.

    ProForma stores display order in ``design.layout`` (a list of doc blocks
    that embed question extensions), not in the ``questions`` map, whose key
    order is arbitrary.
    """
    order: list[str] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return
        attrs = node.get("attrs") or {}
        if node.get("type") == "extension" and attrs.get("extensionKey") == "question":
            qid = str((attrs.get("parameters") or {}).get("id") or "")
            if qid and qid not in seen:
                seen.add(qid)
                order.append(qid)
        walk(node.get("content"))

    for block in design.get("layout") or []:
        walk(block)
    return order


ASSESSMENT_EXPLANATION_LABEL = "Add a short explanation:"

# Per-field config for the Technical Assessment Form. Keyed by ProForma
# question label (stable across ticket template versions, unlike the qid).
#   default : option label to pre-select for choice fields
#   ai      : True for the field the explanation LLM fills (from comments)
#   gate    : (gating question label, [values]) — the field is only applicable
#             when the gating question's answer is one of `values`; mirrors the
#             form's conditional sections so Submit sends only the active branch.
ASSESSMENT_FIELD_CONFIG: dict[str, dict[str, Any]] = {
    "Are there existing features or workarounds available today?": {"default": "No"},
    "Feature Complexity": {"default": "Straightforward"},
    ASSESSMENT_EXPLANATION_LABEL: {"ai": True},
    "Overall TPM recommendation:": {"default": "Recommend moving forward to scoping"},
    "Description": {
        "gate": ("Are there existing features or workarounds available today?", ["Yes"]),
    },
    "Type of Feature": {
        "default": "New Feature",
        "gate": ("Overall TPM recommendation:", ["Recommend moving forward to scoping"]),
    },
    "Estimated Effort": {
        "default": "M - 10 - 14 days",
        "gate": ("Overall TPM recommendation:", ["Recommend moving forward to scoping"]),
    },
    "Needed Resources": {
        "gate": ("Overall TPM recommendation:", ["Recommend moving forward to scoping"]),
    },
    "Explanation": {
        "gate": ("Overall TPM recommendation:", ["Suggest holding or rejecting"]),
    },
}

# ProForma question type code -> answer kind used by the panel + write payload.
_ASSESSMENT_KIND = {
    "cs": "single", "cd": "single",
    "cl": "multi", "cm": "multi",
    "rt": "text", "tl": "text", "pg": "text", "ts": "text", "te": "text",
    "dt": "date", "dd": "date",
}


def _field_editmeta_options(key: str, jira_field: str) -> list[dict[str, str]]:
    """Resolve [{id,label}] options for a jiraField-backed question.

    Some ProForma jiraField questions (e.g. 'Type of Feature') omit their
    choices from the form schema on open forms; the option ids live on the
    Jira field instead. Best-effort — returns [] on any failure.
    """
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base or not jira_field:
        return []
    try:
        url = jira_api_v3_url(base, f"/issue/{key}/editmeta")
        data = request_json(
            url,
            headers={"Accept": "application/json", "Authorization": f"Basic {_jira_auth()}"},
            insecure_env_var="JIRA_INSECURE_SSL",
        )
    except Exception:
        return []
    field = ((data.get("fields") or {}) if isinstance(data, dict) else {}).get(jira_field) or {}
    out: list[dict[str, str]] = []
    for v in field.get("allowedValues") or []:
        oid = str(v.get("id") or "")
        label = (v.get("value") or v.get("name") or "").strip()
        if oid and label:
            out.append({"id": oid, "label": label})
    return out


def _assessment_model(
    key: str, design: dict[str, Any], answers: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Build the editable assessment fields from the live form schema.

    Returns required fields in form order, each:
      {id, label, kind, options:[{id,label}], default, gate, ai, value}
    ``value`` is the form's current answer (choice ids / text / date) — used to
    render submitted forms read-only. Choice options carry their ProForma/Jira
    ids (needed to write answers); jiraField questions missing choices fall back
    to the Jira field's options.
    """
    questions = design.get("questions") or {}
    answers = answers or {}
    out: list[dict[str, Any]] = []
    for qid in _form_question_order(design):
        q = questions.get(qid) or questions.get(str(qid))
        if not isinstance(q, dict):
            continue
        label = (q.get("label") or "").strip()
        cfg = ASSESSMENT_FIELD_CONFIG.get(label)
        if cfg is None:
            continue  # not part of the simplified assessment
        kind = _ASSESSMENT_KIND.get(q.get("type") or "", "text")
        options: list[dict[str, str]] = [
            {"id": str(c.get("id") or ""), "label": (c.get("label") or "").strip()}
            for c in (q.get("choices") or [])
            if (c.get("label") or "").strip()
        ]
        if not options and kind in ("single", "multi") and q.get("jiraField"):
            options = _field_editmeta_options(key, str(q.get("jiraField")))
        default = ""
        if kind in ("single", "multi"):
            want = cfg.get("default")
            labels = [o["label"] for o in options]
            default = want if want in labels else (labels[0] if labels else "")
        gate = cfg.get("gate")

        ans = answers.get(str(qid)) or answers.get(qid) or {}
        if kind == "multi":
            value: Any = [str(c) for c in (ans.get("choices") or [])]
        elif kind == "single":
            ids = [str(c) for c in (ans.get("choices") or [])]
            value = ids[0] if ids else ""
        elif kind == "date":
            value = ans.get("date") or ""
        else:
            value = ans.get("text") or ""

        out.append(
            {
                "id": str(qid),
                "label": label,
                "kind": kind,
                "options": options,
                "default": default,
                "gate": ({"by": gate[0], "values": gate[1]} if gate else None),
                "ai": bool(cfg.get("ai")),
                "value": value,
            }
        )
    return out


def _build_assessment_explain_prompt(comments: list[dict[str, Any]] | None) -> str:
    """Build the explanation prompt from the PIN's discussion only."""
    lines = ["Context from the PIN discussion (oldest → newest):"]
    has_body = False
    for c in (comments or [])[-30:]:
        author = c.get("author") or "Unknown"
        body = (c.get("body_text") or "").strip()
        if body:
            lines.append(f"- {author}: {body}")
            has_body = True
    if not has_body:
        return ""
    lines.append(
        "\nWrite the short explanation as a direct reply to the PIN Reporter now:"
    )
    return "\n".join(lines)


def _format_comment(raw: dict[str, Any]) -> dict[str, Any]:
    author = raw.get("author") or {}
    body_adt = raw.get("body")
    visibility = raw.get("visibility") or {}
    internal = bool(visibility and visibility.get("type") == "role")
    return {
        "id": str(raw.get("id") or ""),
        "author": author.get("displayName") or author.get("emailAddress") or "Unknown",
        "author_email": author.get("emailAddress") or "",
        "account_id": author.get("accountId") or "",
        "created": raw.get("created") or "",
        "updated": raw.get("updated") or "",
        "body_text": _adf_to_text(body_adt).rstrip("\n"),
        "media_items": _adf_extract_media(body_adt) if body_adt else [],
        "internal": internal,
    }


def _jira_search(jql: str, fields: list[str], limit: int = 200) -> list[dict[str, Any]]:
    """Run a JQL search against Jira REST API v3 and return issue list."""
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    url = jira_api_v3_url(base, "/search/jql")
    try:
        data = request_json(
            url,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Basic {_jira_auth()}",
            },
            data={"jql": jql, "maxResults": limit, "fields": fields},
            insecure_env_var="PIN_REPORT_INSECURE_SSL",
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(exc.code, f"Jira search failed: {detail or exc.reason}") from exc
    return (data.get("issues") or []) if isinstance(data, dict) else []


def _jira_get_issue(key: str, fields: list[str]) -> dict[str, Any]:
    """Fetch a single Jira issue by key."""
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    fields_param = ",".join(fields)
    url = jira_api_v3_url(base, f"/issue/{key}?fields={fields_param}")
    try:
        data = request_json(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {_jira_auth()}",
            },
            insecure_env_var="PIN_REPORT_INSECURE_SSL",
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(exc.code, f"Jira issue fetch failed: {detail or exc.reason}") from exc
    return data if isinstance(data, dict) else {}


def _issue_to_pin_summary(issue: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw Jira issue dict to the PinSummary shape expected by the frontend."""
    f = issue.get("fields") or {}
    key = issue.get("key") or ""
    status = ((f.get("status") or {}).get("name") or "Unknown")
    priority = ((f.get("priority") or {}).get("name") or "")
    description_adf = f.get("description")
    raw_attachments = f.get("attachment") or []
    media_items = _adf_extract_media(description_adf) if description_adf else []

    # Build lightweight attachment list (displayed in the Attachments card)
    attachment_items: list[dict[str, Any]] = []
    for att in raw_attachments:
        att_id = str(att.get("id") or "")
        att_name = att.get("filename") or ""
        if not att_id or not att_name:
            continue
        author = att.get("author") or {}
        attachment_items.append({
            "id": att_id,
            "filename": att_name,
            "size": att.get("size") or 0,
            "mime_type": att.get("mimeType") or "",
            "author": author.get("displayName") or "",
            "created": att.get("created") or "",
        })

    reporter = f.get("reporter") or {}
    assignee = f.get("assignee") or {}
    return {
        "key": key,
        "status": status,
        "summary": f.get("summary") or "",
        "reporter": reporter.get("displayName") or "",
        "reporter_account_id": reporter.get("accountId") or "",
        "reporter_email": reporter.get("emailAddress") or "",
        "assignee": assignee.get("displayName") or "",
        "assignee_account_id": assignee.get("accountId") or "",
        "jira_url": _jira_url_for(key),
        "urgency": priority,
        "created": f.get("created") or "",
        "description_text": _adf_to_text(description_adf),
        "description_media_items": _resolve_media_attachment_ids(media_items, raw_attachments),
        "attachments": attachment_items,
    }


@app.get("/api/pins")
def list_pins() -> dict[str, Any]:
    profile = _profile()
    account_id = profile.get("account_id") or ""
    if not account_id:
        raise HTTPException(500, "account_id missing from profile")
    statuses = ", ".join(f'"{s}"' for s in DEFAULT_STATUSES)
    jql = (
        f'project = PIN AND assignee in ("{account_id}") '
        f"AND status IN ({statuses}) ORDER BY created DESC"
    )
    issues = _jira_search(jql, ["key", "summary", "status", "priority", "created", "reporter", "assignee"])
    items = [_issue_to_pin_summary(i) for i in issues]
    return {"items": items}


@app.get("/api/pins/{key}")
def get_pin(key: str) -> dict[str, Any]:
    issue = _jira_get_issue(key, ["summary", "status", "priority", "description", "created", "attachment", "reporter", "assignee"])
    if not issue:
        raise HTTPException(404, f"PIN {key} not found")
    return _issue_to_pin_summary(issue)


@app.get("/api/pins/{key}/form")
def get_pin_form(key: str, reload: bool = False) -> dict[str, Any]:
    """Fetch the intake form for a PIN, with local caching.

    When ``reload=true`` (Reload Form button), bypasses cache, fetches fresh
    from Jira, and clears cached translations for this PIN.
    """

    # Return cached form when not forcing reload
    if not reload:
        pin_entry = _PIN_CACHE.get(key, {})
        cached = pin_entry.get("form")
        if cached and (time.time() - cached.get("ts", 0)) < _FORM_CACHE_TTL:
            result = cached["result"]
            fixed = _fix_form_result_encoding(result)
            if fixed != result:
                _PIN_CACHE.setdefault(key, {})["form"]["result"] = fixed
                _save_pin_cache()
            return fixed

    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    try:
        form = get_issue_form_by_name(
            base, _jira_auth(), key, DEFAULT_INTAKE_FORM_NAME, cloud_id=_cloud_id()
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-500:]
        except Exception:
            pass
        raise HTTPException(exc.code, f"Form fetch failed: {detail or exc.reason}") from exc
    except Exception as exc:
        raise HTTPException(502, f"Form fetch failed: {exc}") from exc

    if reload:
        _PIN_CACHE.setdefault(key, {}).pop("translations", None)
        _save_pin_cache()

    if not form:
        result = {"available": False}
    else:
        result = {
            "available": True,
            "form_id": str(form.get("id") or ""),
            "form_name": DEFAULT_INTAKE_FORM_NAME,
            "fields": form_answers_as_dict(form),
            "clean_fields": build_clean_intake_fields(form),
            "clean_requirements_text": build_clean_intake_requirements(form),
        }

    _PIN_CACHE.setdefault(key, {})["form"] = {"result": result, "ts": time.time()}
    _save_pin_cache()
    return result


@app.get("/api/pins/{key}/forms/submitted")
def list_pin_submitted_forms(key: str) -> dict[str, Any]:
    """List cleaned content for every submitted ProForma form (for LLM review)."""
    try:
        items = list_submitted_forms_clean(
            (_profile().get("base_url") or "").rstrip("/"),
            _jira_auth(),
            key,
            cloud_id=_cloud_id(),
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-500:]
        except Exception:
            pass
        raise HTTPException(
            exc.code, f"Submitted forms fetch failed: {detail or exc.reason}"
        ) from exc
    except Exception as exc:
        raise HTTPException(502, f"Submitted forms fetch failed: {exc}") from exc
    return {"key": key, "items": items}


@app.get("/api/pins/{key}/forms")
def list_pin_forms(key: str) -> dict[str, Any]:
    """List all ProForma forms attached to a PIN (metadata only)."""
    try:
        forms = list_issue_forms(_cloud_id(), key, _jira_auth())
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-500:]
        except Exception:
            pass
        raise HTTPException(exc.code, f"Forms list failed: {detail or exc.reason}") from exc
    except Exception as exc:
        raise HTTPException(502, f"Forms list failed: {exc}") from exc

    items: list[dict[str, Any]] = []
    for raw in forms:
        form_id = str(raw.get("id") or "")
        items.append(
            {
                "id": form_id,
                "name": (raw.get("name") or "").strip(),
                "submitted": bool(raw.get("submitted")),
                "lock": bool(raw.get("lock")),
                "internal": bool(raw.get("internal")),
                "updated": raw.get("updated") or "",
                "form_template_id": (raw.get("formTemplate") or {}).get("id") or "",
            }
        )
    return {"key": key, "items": items}


class AnalyzeRequest(BaseModel):
    clean_requirements_text: str | None = None


@app.get("/api/pins/{key}/analyze")
def get_cached_analysis(key: str, clean_text_hash: str = "") -> dict[str, Any]:
    """Return the cached analysis for a PIN without calling the LLM.

    NOTE: the stored ``hash`` now covers all prompt inputs (form text + summary +
    description), not just the form text — so a caller passing a clean-text-only
    hash will never match. Callers should omit ``clean_text_hash`` (the default)
    to get any TTL-valid cached result and refresh via POST/Re-analyze, which
    recomputes the full-input hash. The hash-match branch below is kept only for
    callers that compute the same full-input hash.
    When empty (no hash provided), returns any cached analysis regardless of
    hash match — the caller should validate freshness on its own.
    Returns ``{"cached": true, "result": {...}}`` on hit, or ``{"cached": false}`` on miss.
    """
    text_hash = clean_text_hash.strip()
    pin_entry = _PIN_CACHE.get(key, {})
    entry = pin_entry.get("analysis") if pin_entry else None
    if not entry or (time.time() - entry.get("ts", 0)) >= _ANALYSIS_CACHE_TTL:
        return {"cached": False}
    if not text_hash:
        # No hash provided — return whatever is cached; caller validates freshness.
        return {"cached": True, "result": entry["result"]}
    if entry.get("hash") == text_hash:
        return {"cached": True, "result": entry["result"]}
    return {"cached": False}


@app.post("/api/pins/{key}/analyze")
def analyze_pin(key: str, body: AnalyzeRequest | None = None, force: bool = False) -> dict[str, Any]:
    """Run LLM analysis for a single PIN.

    Results are cached to ``web/cache/pin_cache.json`` (TTL 7 days) under
    ``_PIN_CACHE[key]["analysis"]``. Pass ``?force=true`` to bypass the cache
    and refresh (Re-analyze button).
    """
    clean_text = (body.clean_requirements_text or "").strip() if body else ""

    # Fetch the issue first so the cache key can cover everything that actually
    # feeds the prompt (summary + description + form text), not just the form.
    # Hashing clean_text alone meant summary/description edits returned stale
    # analysis, and all form-less PINs collided on one empty-form hash.
    issue = _jira_get_issue(key, ["summary", "status", "priority", "description"])
    if not issue:
        raise HTTPException(404, f"PIN {key} not found")
    f = issue.get("fields") or {}
    summary = f.get("summary") or ""
    description_text = _adf_to_text(f.get("description"))
    text_hash = hashlib.sha256(
        "\x00".join([clean_text, summary, description_text]).encode()
    ).hexdigest()[:8]

    if not force:
        pin_entry = _PIN_CACHE.get(key, {})
        entry = pin_entry.get("analysis")
        if (
            entry
            and entry.get("hash") == text_hash
            and (time.time() - entry.get("ts", 0)) < _ANALYSIS_CACHE_TTL
        ):
            return entry["result"]

    payload: dict[str, Any] = {
        "key": key,
        "summary": summary,
        "description": description_text,
    }
    if clean_text:
        payload["intake_form_requirements"] = clean_text
    user_prompt = (
        "请分析以下 Jira issue，并输出指定 JSON：\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    api_key = os.environ.get("DEEPSEEK_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise HTTPException(500, "DEEPSEEK_KEY env var is required for LLM analysis")
    base_url = (os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_LLM_BASE_URL).rstrip("/")
    model = os.environ.get("PIN_REPORT_LLM_MODEL", DEFAULT_ANALYSIS_MODEL)
    url = f"{base_url}/chat/completions"
    req_payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": ANALYZE_SYSTEM_PROMPT_FULL},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    try:
        data = request_json(
            url,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            data=req_payload,
            insecure_env_var="PIN_REPORT_INSECURE_SSL",
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(502, f"LLM analysis failed: {detail or exc.reason}") from exc
    choices = (data.get("choices") or []) if isinstance(data, dict) else []
    if not choices:
        raise HTTPException(502, "LLM response missing choices")
    content = (choices[0].get("message") or {}).get("content") or ""
    if not content:
        raise HTTPException(502, "LLM response empty content")
    try:
        obj = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, f"LLM returned invalid JSON: {exc}") from exc
    result: dict[str, Any] = {}
    for k in ANALYSIS_KEYS:
        v = _coerce_field_text(obj.get(k))
        result[k] = v if v else "暂无描述"
    if _LABEL_MODULES:
        result["labels"] = normalize_labels(obj.get("labels"), _LABEL_MODULES, _LABEL_NATURES)

    _PIN_CACHE.setdefault(key, {})["analysis"] = {"result": result, "ts": time.time(), "hash": text_hash}
    _save_pin_cache()
    return result


@app.get("/api/pins/{key}/comments")
def list_comments(key: str) -> dict[str, Any]:
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    auth = _jira_auth()
    url = jira_api_v3_url(base, f"/issue/{key}/comment?orderBy=created")
    try:
        data = request_json(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {auth}",
            },
            insecure_env_var="JIRA_INSECURE_SSL",
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(
            exc.code, f"Jira comment fetch failed: {detail or exc.reason}"
        ) from exc
    raw_items = data.get("comments") if isinstance(data, dict) else []

    # Fetch issue attachments to resolve temporary media UUIDs → numeric attachment IDs
    attachments: list[dict[str, Any]] = []
    try:
        issue_url = jira_api_v3_url(base, f"/issue/{key}?fields=attachment")
        issue_data = request_json(
            issue_url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {auth}",
            },
            insecure_env_var="JIRA_INSECURE_SSL",
        )
        attachments = (issue_data.get("fields") or {}).get("attachment") or []
    except Exception:
        pass  # best-effort; images will still show via fallback URL

    # Jira system accounts whose comments should not be displayed
    _FILTERED_AUTHORS = {"Automation for Jira"}

    items: list[dict[str, Any]] = []
    for c in (raw_items or []):
        comment = _format_comment(c)
        if comment.get("author") in _FILTERED_AUTHORS:
            continue
        if comment.get("media_items"):
            comment["media_items"] = _resolve_media_attachment_ids(
                comment["media_items"], attachments
            )
        items.append(comment)
    return {"items": items, "total": len(items)}


class CommentCreate(BaseModel):
    body: str
    mentions: dict[str, str] | None = None
    internal: bool = False


@app.post("/api/pins/{key}/comments")
def add_comment(key: str, payload: CommentCreate) -> dict[str, Any]:
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    auth = _jira_auth()
    body_doc = _text_to_adf(payload.body, payload.mentions)
    comment_payload: dict[str, Any] = {"body": body_doc}
    if payload.internal:
        comment_payload["visibility"] = {"type": "role", "value": "Service Desk Team"}
    url = jira_api_v3_url(base, f"/issue/{key}/comment")
    try:
        data = request_json(
            url,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
            },
            data=comment_payload,
            insecure_env_var="JIRA_INSECURE_SSL",
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(
            exc.code, f"Jira comment add failed: {detail or exc.reason}"
        ) from exc
    return {"ok": True, "comment": _format_comment(data or {})}


class CommentDraftRequest(BaseModel):
    prompt: str
    recent_comments: list[dict[str, Any]] | None = None
    analysis: dict[str, str] | None = None


@app.post("/api/pins/{key}/comments/ai-draft")
def draft_comment(key: str, payload: CommentDraftRequest) -> dict[str, Any]:
    user_instruction = (payload.prompt or "").strip()
    if not user_instruction:
        raise HTTPException(400, "Prompt cannot be empty")
    issue = _jira_get_issue(key, ["summary", "status", "priority"])
    f = (issue.get("fields") or {}) if issue else {}
    summary_ctx = {
        "key": key,
        "status": ((f.get("status") or {}).get("name") or ""),
        "urgency": ((f.get("priority") or {}).get("name") or ""),
        "summary": f.get("summary") or "",
        "analysis": payload.analysis or {},
    }
    user_prompt = _build_ai_draft_user_prompt(
        summary_ctx, user_instruction, payload.recent_comments
    )
    text = _llm_chat(AI_DRAFT_SYSTEM_PROMPT, user_prompt)
    if not text:
        raise HTTPException(502, "LLM returned empty content")
    return {"text": text}


@app.post("/api/pins/{key}/comments/ai-draft/stream")
def draft_comment_stream(key: str, payload: CommentDraftRequest):
    """Stream the AI draft as NDJSON.

    Each line is a JSON object: {"delta": "..."} for tokens, {"done": true}
    when complete, {"error": "..."} if the LLM call fails mid-stream. Errors
    raised before any token (e.g. missing API key, bad payload) surface as
    normal HTTP errors via raise HTTPException.
    """
    user_instruction = (payload.prompt or "").strip()
    if not user_instruction:
        raise HTTPException(400, "Prompt cannot be empty")
    issue = _jira_get_issue(key, ["summary", "status", "priority"])
    f = (issue.get("fields") or {}) if issue else {}
    summary_ctx = {
        "key": key,
        "status": ((f.get("status") or {}).get("name") or ""),
        "urgency": ((f.get("priority") or {}).get("name") or ""),
        "summary": f.get("summary") or "",
        "analysis": payload.analysis or {},
    }
    user_prompt = _build_ai_draft_user_prompt(
        summary_ctx, user_instruction, payload.recent_comments
    )

    def gen():
        try:
            for delta in _llm_chat_stream(AI_DRAFT_SYSTEM_PROMPT, user_prompt):
                if not delta:
                    continue
                yield json.dumps({"delta": delta}, ensure_ascii=False) + "\n"
            yield json.dumps({"done": True}) + "\n"
        except HTTPException as exc:
            yield json.dumps({"error": str(exc.detail)}, ensure_ascii=False) + "\n"
        except Exception as exc:  # noqa: BLE001 - surface to client, never crash
            yield json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _get_assessment_form(key: str, form_id: str) -> dict[str, Any]:
    """Fetch a ProForma form, mapping Jira errors to clean HTTPExceptions."""
    try:
        return get_issue_form(_cloud_id(), key, form_id, _jira_auth())
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-500:]
        except Exception:
            pass
        raise HTTPException(
            exc.code, _jira_error_message(detail, exc.reason or "form fetch failed")
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Form fetch failed: {exc}") from exc


@app.post("/api/pins/{key}/forms/{form_id}/assessment")
def draft_assessment(key: str, form_id: str) -> dict[str, Any]:
    """Return the editable Technical Assessment Form model (no LLM, no writes).

    Required fields in form order with options/defaults, branch gating, and each
    field's current answer (``value``) so a submitted form can render read-only.
    The 'Add a short explanation' draft is generated separately, on demand, via
    the /assessment/explain endpoint.
    """
    if not (_profile().get("base_url") or "").rstrip("/"):
        raise HTTPException(500, "Jira base_url missing from profile")
    form_detail = _get_assessment_form(key, form_id)
    answers = (form_detail.get("state") or {}).get("answers") or {}
    fields = _assessment_model(key, form_detail.get("design") or {}, answers)
    return {
        "fields": fields,
        "explanation_label": ASSESSMENT_EXPLANATION_LABEL,
    }


@app.post("/api/pins/{key}/forms/{form_id}/assessment/explain")
def explain_assessment(key: str, form_id: str) -> dict[str, Any]:
    """Draft the 'Add a short explanation' text from the PIN's comments only."""
    try:
        comments = list_comments(key).get("items") or []
    except Exception:
        comments = []
    user_prompt = _build_assessment_explain_prompt(comments)
    if not user_prompt:
        return {"explanation": ""}
    # Flash is the fast, light-reasoning model — well-suited to this 1-3
    # sentence task and much quicker than the default (heavy-reasoning) model.
    explanation = _llm_chat(
        ASSESSMENT_EXPLAIN_SYSTEM_PROMPT,
        user_prompt,
        max_tokens=600,
        model=DEFAULT_TRANSLATE_MODEL,
    )
    return {"explanation": explanation}


class AssessmentSubmitRequest(BaseModel):
    # qid -> value: string for text/date, or list[str] of option ids for
    # single/multi choice (single carries a one-element list).
    answers: dict[str, Any]
    submit: bool = True


def _format_assessment_answer(kind: str, value: Any) -> dict[str, Any] | None:
    """Map a panel value to the ProForma answer shape for its question kind."""
    if kind in ("single", "multi"):
        ids = value if isinstance(value, list) else ([value] if value else [])
        ids = [str(v) for v in ids if str(v).strip()]
        if not ids:
            return None
        return {"text": "", "choices": ids}
    if kind == "date":
        v = str(value or "").strip()
        return {"date": v} if v else None
    v = str(value or "").strip()
    return {"text": v} if v else None


@app.post("/api/pins/{key}/forms/{form_id}/assessment/submit")
def submit_assessment(key: str, form_id: str, payload: AssessmentSubmitRequest) -> dict[str, Any]:
    """Write the assessment answers to the ProForma form, then submit it.

    Sends answers only for the currently-applicable fields (the active branch).
    Existing answers on the form are preserved; ours overlay them. Submission is
    validated server-side by Jira — validation failures surface as 4xx.
    """
    if not (_profile().get("base_url") or "").rstrip("/"):
        raise HTTPException(500, "Jira base_url missing from profile")
    auth = _jira_auth()
    cloud_id = _cloud_id()
    form_detail = _get_assessment_form(key, form_id)
    design = form_detail.get("design") or {}
    questions = design.get("questions") or {}

    # Build the answers payload: start from existing answers, overlay ours.
    answers: dict[str, Any] = dict((form_detail.get("state") or {}).get("answers") or {})
    for qid, value in (payload.answers or {}).items():
        q = questions.get(str(qid)) or questions.get(qid)
        if not isinstance(q, dict):
            continue
        kind = _ASSESSMENT_KIND.get(q.get("type") or "", "text")
        formatted = _format_assessment_answer(kind, value)
        if formatted is not None:
            answers[str(qid)] = formatted

    try:
        save_issue_form_answers(cloud_id, key, form_id, answers, auth)
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-800:]
        except Exception:
            pass
        raise HTTPException(exc.code, _jira_error_message(detail, "form save failed")) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Form save failed: {exc}") from exc

    if not payload.submit:
        return {"ok": True, "submitted": False, "key": key, "form_id": form_id}

    try:
        result = submit_issue_form(cloud_id, key, form_id, auth)
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-800:]
        except Exception:
            pass
        # 400 here is typically "required answers missing" validation.
        raise HTTPException(exc.code, _jira_error_message(detail, "form submit failed")) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"Form submit failed: {exc}") from exc

    return {
        "ok": True,
        "submitted": True,
        "status": result.get("status") or "",
        "key": key,
        "form_id": form_id,
    }


@app.get("/api/pins/{key}/transitions")
def list_transitions(key: str) -> dict[str, Any]:
    """Return available workflow transitions for a PIN issue."""
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    auth = _jira_auth()
    url = jira_api_v3_url(base, f"/issue/{key}/transitions")
    try:
        data = request_json(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {auth}",
            },
            insecure_env_var="JIRA_INSECURE_SSL",
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(exc.code, f"Jira transitions fetch failed: {detail or exc.reason}") from exc
    raw = (data.get("transitions") or []) if isinstance(data, dict) else []
    items: list[dict[str, str]] = [
        {
            "id": str(t.get("id") or ""),
            "name": t.get("name") or "",
            "to_status": ((t.get("to") or {}).get("name") or ""),
        }
        for t in raw
        if t.get("id") and t.get("name")
    ]
    return {"items": items}


class TransitionRequest(BaseModel):
    transition_id: str


def _jira_error_message(detail: str, fallback: str) -> str:
    """Extract a human-readable message from a Jira error payload, falling back
    to the raw text / reason when it isn't the expected JSON shape."""
    try:
        obj = json.loads(detail)
    except Exception:
        return (detail or fallback).strip()
    parts = [m for m in (obj.get("errorMessages") or []) if m]
    parts.extend(f"{k}: {v}" for k, v in (obj.get("errors") or {}).items() if v)
    return "; ".join(parts) or (detail or fallback).strip()


@app.post("/api/pins/{key}/transition")
def do_transition(key: str, payload: TransitionRequest) -> dict[str, Any]:
    """Apply a workflow transition to a PIN issue."""
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    auth = _jira_auth()
    url = jira_api_v3_url(base, f"/issue/{key}/transitions")
    try:
        request_json(
            url,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
            },
            data={"transition": {"id": payload.transition_id}},
            insecure_env_var="JIRA_INSECURE_SSL",
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(
            exc.code, _jira_error_message(detail, exc.reason or "transition failed")
        ) from exc
    issue = _jira_get_issue(key, ["summary", "status", "priority", "description", "created", "attachment", "reporter", "assignee"])
    return _issue_to_pin_summary(issue)


class AssigneeRequest(BaseModel):
    account_id: str


@app.put("/api/pins/{key}/assignee")
def update_assignee(key: str, payload: AssigneeRequest) -> dict[str, Any]:
    """Reassign a PIN issue to a different Jira user."""
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    auth = _jira_auth()
    url = jira_api_v3_url(base, f"/issue/{key}")
    try:
        request_json(
            url,
            method="PUT",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
            },
            data={"fields": {"assignee": {"accountId": payload.account_id}}},
            insecure_env_var="JIRA_INSECURE_SSL",
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(
            exc.code, _jira_error_message(detail, exc.reason or "assignee update failed")
        ) from exc
    issue = _jira_get_issue(key, ["summary", "status", "priority", "description", "created", "attachment", "reporter", "assignee"])
    return _issue_to_pin_summary(issue)


@app.get("/api/users/search")
def search_users(q: str = "", max_results: int = 8) -> dict[str, Any]:
    query = (q or "").strip()
    if not query:
        return {"items": []}
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    auth = _jira_auth()
    capped = max(1, min(max_results, 20))
    url = jira_api_v3_url(
        base, f"/user/search?query={quote(query)}&maxResults={capped}"
    )
    try:
        data = request_json(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {auth}",
            },
            insecure_env_var="JIRA_INSECURE_SSL",
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(
            exc.code, f"Jira user search failed: {detail or exc.reason}"
        ) from exc
    users = data if isinstance(data, list) else []
    items: list[dict[str, str]] = []
    for u in users:
        if not isinstance(u, dict):
            continue
        if u.get("active") is False:
            continue
        account_type = u.get("accountType")
        if account_type and account_type != "atlassian":
            continue
        items.append(
            {
                "account_id": u.get("accountId") or "",
                "display_name": u.get("displayName") or "",
                "email": u.get("emailAddress") or "",
                "avatar_url": (u.get("avatarUrls") or {}).get("24x24") or "",
            }
        )
    return {"items": items}


@app.get("/api/translate")
def translate_text(text: str = "", to: str = "zh", pin_key: str = "", field: str = "") -> dict[str, Any]:
    """Translate text using the configured LLM, with persistent per-PIN cache.

    Cache key is (pin_key, field). Without PIN context the result is not cached.
    Translations are invalidated by Reload Form, not by time.
    Returns ``{"translated": "...", "cached": bool}``.
    """
    if not text.strip():
        return {"translated": "", "cached": False}

    if pin_key and field:
        existing = _PIN_CACHE.get(pin_key, {}).get("translations", {}).get(field)
        if existing:
            return {"translated": existing, "cached": True}

    lang_map = {"zh": "Simplified Chinese", "en": "English"}
    target_lang = lang_map.get(to, to)
    system = (
        f"You are a Pacvue Ads Product Manager, you need to translate the user's text into {target_lang}. "
        "Output only the translated text — no explanations, no notes, no markdown."
    )
    translated = _llm_chat(system, text, max_tokens=1000, temperature=0.1,
                           model=os.environ.get("TRANSLATE_LLM_MODEL", DEFAULT_TRANSLATE_MODEL))

    if pin_key and field:
        _PIN_CACHE.setdefault(pin_key, {}).setdefault("translations", {})[field] = translated
        _save_pin_cache()
    return {"translated": translated, "cached": False}


@app.get("/api/profile")
def profile_endpoint() -> dict[str, str]:
    p = _profile()
    return {
        "base_url": p.get("base_url", ""),
        "account_id": p.get("account_id", ""),
        "email": p.get("email", ""),
    }


@app.get("/api/media/{media_id}")
def proxy_jira_attachment(media_id: str, filename: str = "", alt: str = ""):
    """Proxy Jira attachment content (images) through the backend.

    Jira Cloud ADF ``media`` nodes reference temporary attachment UUIDs.
    This endpoint tries multiple URL patterns to resolve the image, keeping
    credentials server-side.
    """
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    auth = _jira_auth()
    ctx = ssl_context("JIRA_INSECURE_SSL")

    fname = filename or alt or ""
    # REST API first (most reliable), then temporary attachment URL
    urls = [f"{base}/rest/api/3/attachment/content/{media_id}"]
    if fname:
        urls.append(f"{base}/secure/temporaryattachment/{media_id}/{fname}")

    last_err = ""
    for url in urls:
        req = Request(url, method="GET")
        req.add_header("Authorization", f"Basic {auth}")
        try:
            resp = urlopen(req, context=ctx)
            content_type = resp.headers.get("Content-Type") or "application/octet-stream"
            return Response(
                content=resp.read(),
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=3600"},
            )
        except Exception as exc:
            last_err = f"{url}: {exc}"
            continue

    raise HTTPException(502, last_err or "Failed to fetch attachment from Jira")


@app.get("/api/media/{media_id}/thumbnail")
def proxy_jira_attachment_thumbnail(media_id: str):
    """Proxy Jira attachment thumbnail through the backend.

    Uses ``GET /rest/api/3/attachment/thumbnail/{media_id}`` with server-side
    Basic Auth.  Falls back to the full-size content endpoint if the thumbnail
    is unavailable.
    """
    base = (_profile().get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(500, "Jira base_url missing from profile")
    auth = _jira_auth()
    ctx = ssl_context("JIRA_INSECURE_SSL")
    url = f"{base}/rest/api/3/attachment/thumbnail/{media_id}"
    req = Request(url, method="GET")
    req.add_header("Authorization", f"Basic {auth}")
    try:
        resp = urlopen(req, context=ctx)
        content_type = resp.headers.get("Content-Type") or "image/png"
        return Response(
            content=resp.read(),
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except HTTPError:
        pass  # fall back to full-size
    # Fallback: redirect to the full-size attachment proxy
    return proxy_jira_attachment(media_id)


if DIST_DIR.is_dir():
    _ASSETS_DIR = DIST_DIR / "assets"
    _INDEX_HTML = DIST_DIR / "index.html"
    _ICON32 = DIST_DIR / "icon32.png"

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        # FastAPI route order guarantees API routes match first; this is the
        # catch-all for everything else (SPA routes + static assets).
        file_path = DIST_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        # SPA fallback: any non-file, non-API path → index.html
        if _INDEX_HTML.is_file():
            return FileResponse(_INDEX_HTML)
        raise HTTPException(404, "Not Found")


def main() -> None:
    import uvicorn

    host = os.environ.get("PIN_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("PIN_WEB_PORT", "8765"))
    print(f"PIN Ticket Analysis server on http://{host}:{port} (repo={SCRIPT_DIR})")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
