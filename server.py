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
import threading
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
from lib.domain import (  # noqa: E402
    PROMPT_VERSION,
    analysis_domain_block,
    translate_system_prompt,
)
from lib.env import load_dotenv  # noqa: E402
from lib.http import request_json, request_raw, ssl_context  # noqa: E402
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
    "你是 Pacvue（零售媒体广告 SaaS）的资深产品需求评审专家，为 PIN（Product Incoming Need）工单做结构化分析，供产品/技术评审快速决策。"
    + analysis_domain_block() +
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
# Endpoints run in a thread pool; concurrent translate calls used to race on
# the same temp file and could leave a truncated/corrupt cache on disk (which
# then silently failed to load on the next start => "translations lost").
_PIN_CACHE_LOCK = threading.RLock()
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
    except Exception as exc:  # noqa: BLE001
        # Never silently discard: keep the broken file for inspection.
        print(f"[cache] failed to load {PIN_CACHE_FILE}: {exc}", flush=True)
        try:
            os.replace(PIN_CACHE_FILE, PIN_CACHE_FILE.with_suffix(".corrupt.json"))
        except Exception:
            pass


def _save_pin_cache() -> None:
    # Atomic write: serialize to a temp file in the same dir, then os.replace
    # so a crash mid-write can never corrupt the existing cache file. The lock
    # serialises writers so two threads never share the temp file.
    with _PIN_CACHE_LOCK:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = PIN_CACHE_FILE.with_suffix(PIN_CACHE_FILE.suffix + ".tmp")
            tmp.write_text(
                json.dumps(_PIN_CACHE, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, PIN_CACHE_FILE)
        except Exception as exc:  # noqa: BLE001
            print(f"[cache] failed to persist {PIN_CACHE_FILE}: {exc}", flush=True)


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


_LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT_SECONDS", "180"))


def _llm_chat(system: str, user: str, *, max_tokens: int = 800, temperature: float = 0.4, model: str | None = None) -> str:
    return _llm_chat_full(system, user, max_tokens=max_tokens, temperature=temperature, model=model)[0]


def _llm_chat_full(
    system: str, user: str, *, max_tokens: int = 800, temperature: float = 0.4, model: str | None = None,
) -> tuple[str, str]:
    """Non-streaming chat call. Returns ``(content, finish_reason)``."""
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
            timeout=_LLM_TIMEOUT,
        )
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(502, f"LLM request failed: {detail or exc.reason}") from exc
    except OSError as exc:
        raise HTTPException(502, f"LLM request failed: {exc}") from exc
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise HTTPException(502, "LLM response missing choices")
    content = choices[0].get("message", {}).get("content")
    finish_reason = str(choices[0].get("finish_reason") or "")
    return (content or "").strip(), finish_reason


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


# ---------------------------------------------------------------------------
# PIN list cache (stale-while-revalidate)
# ---------------------------------------------------------------------------
# The Jira search behind /api/pins takes several seconds from the deployment
# host, and the list page re-requested it on every visit. We keep the last
# result in memory and serve it instantly. It is refreshed once a day by a
# background thread (and in the background when a served copy is older than
# _PINS_LIST_TTL, also a day by default); visits never wait on Jira. ``?refresh=true`` forces a
# synchronous fetch (the Refresh button).
_PINS_LIST_TTL = float(os.environ.get("PINS_LIST_TTL_SECONDS", str(24 * 3600)))
_PINS_LIST_WARM_INTERVAL = float(os.environ.get("PINS_LIST_WARM_INTERVAL_SECONDS", str(24 * 3600)))
_PINS_LIST_CACHE: dict[str, Any] = {"items": None, "ts": 0.0, "error": ""}
_PINS_LIST_FILE = CACHE_DIR / "pin_list.json"  # last good list, so a restart serves instantly
_PINS_LIST_LOCK = threading.Lock()
_PINS_LIST_FETCH_LOCK = threading.Lock()  # only one Jira search in flight at a time
_PINS_LIST_REFRESHING = False
_PIN_LIST_FIELDS = ["key", "summary", "status", "priority", "created", "reporter", "assignee"]


def _fetch_pin_list_from_jira() -> list[dict[str, Any]]:
    profile = _profile()
    account_id = profile.get("account_id") or ""
    if not account_id:
        raise HTTPException(500, "account_id missing from profile")
    statuses = ", ".join(f'"{s}"' for s in DEFAULT_STATUSES)
    jql = (
        f'project = PIN AND assignee in ("{account_id}") '
        f"AND status IN ({statuses}) ORDER BY created DESC"
    )
    issues = _jira_search(jql, _PIN_LIST_FIELDS)
    return [_issue_to_pin_summary(i) for i in issues]


def _refresh_pin_list(*, wait: bool = True) -> list[dict[str, Any]] | None:
    """Fetch the list from Jira and store it. Concurrent callers coalesce: if a
    fetch is already running, ``wait=True`` waits for it and returns its result,
    ``wait=False`` returns None immediately."""
    if not _PINS_LIST_FETCH_LOCK.acquire(blocking=wait):
        return None
    try:
        started = time.time()
        with _PINS_LIST_LOCK:
            # Another thread may have just refreshed while we waited for the lock.
            if _PINS_LIST_CACHE["items"] is not None and started - _PINS_LIST_CACHE["ts"] < 1.0:
                return list(_PINS_LIST_CACHE["items"])
        t0 = time.time()
        items = _fetch_pin_list_from_jira()
        now = time.time()
        with _PINS_LIST_LOCK:
            _PINS_LIST_CACHE.update({"items": items, "ts": now, "error": ""})
        print(f"[pins] list refreshed: {len(items)} items in {now - t0:.1f}s", flush=True)
        _save_pin_list_file(items, now)
        _prune_pin_cache({p.get("key") for p in items})
        return items
    except Exception as exc:  # noqa: BLE001
        with _PINS_LIST_LOCK:
            _PINS_LIST_CACHE["error"] = str(getattr(exc, "detail", exc))
        raise
    finally:
        _PINS_LIST_FETCH_LOCK.release()


def _prune_pin_cache(live_keys: set[str]) -> None:
    """Drop cached translations/analysis/forms for PINs that are no longer in
    the working list (processed / closed). Skipped when the list is empty so a
    bad Jira response can never wipe the cache."""
    if not live_keys:
        return
    with _PIN_CACHE_LOCK:
        gone = [k for k in _PIN_CACHE if k not in live_keys]
        for k in gone:
            _PIN_CACHE.pop(k, None)
    if gone:
        _save_pin_cache()
        print(f"[cache] pruned {len(gone)} PIN(s) no longer in the list: {', '.join(sorted(gone)[:10])}"
              + (" ..." if len(gone) > 10 else ""), flush=True)


def _save_pin_list_file(items: list[dict[str, Any]], ts: float) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _PINS_LIST_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"items": items, "ts": ts}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _PINS_LIST_FILE)
    except Exception as exc:  # noqa: BLE001
        print(f"[pins] failed to persist list cache: {exc}", flush=True)


def _load_pin_list_file() -> None:
    """Seed the in-memory list from the last persisted copy (marked stale so
    the startup warm-up still refreshes it)."""
    try:
        if not _PINS_LIST_FILE.exists():
            return
        raw = json.loads(_PINS_LIST_FILE.read_text(encoding="utf-8"))
        items = raw.get("items") if isinstance(raw, dict) else None
        if isinstance(items, list):
            with _PINS_LIST_LOCK:
                _PINS_LIST_CACHE.update({"items": items, "ts": float(raw.get("ts") or 0.0)})
            print(f"[pins] loaded {len(items)} items from {_PINS_LIST_FILE.name}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[pins] failed to load persisted list: {exc}", flush=True)


_load_pin_list_file()


def _refresh_pin_list_in_background() -> None:
    global _PINS_LIST_REFRESHING
    with _PINS_LIST_LOCK:
        if _PINS_LIST_REFRESHING or _PINS_LIST_FETCH_LOCK.locked():
            return  # a refresh (possibly the startup warm-up) is already running
        _PINS_LIST_REFRESHING = True

    def run() -> None:
        global _PINS_LIST_REFRESHING
        try:
            _refresh_pin_list(wait=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[pins] background refresh failed: {exc}", flush=True)
        finally:
            with _PINS_LIST_LOCK:
                _PINS_LIST_REFRESHING = False

    threading.Thread(target=run, name="pins-refresh", daemon=True).start()


def _pin_list_warm_loop() -> None:
    """Refresh the list once per _PINS_LIST_WARM_INTERVAL (daemon thread).
    A failed attempt is retried after a minute instead of waiting a whole day."""
    while True:
        try:
            _refresh_pin_list(wait=True)
            delay = _PINS_LIST_WARM_INTERVAL
        except Exception as exc:  # noqa: BLE001
            print(f"[pins] warm refresh failed: {exc}", flush=True)
            delay = min(60.0, _PINS_LIST_WARM_INTERVAL)
        time.sleep(delay)


def _patch_pin_list_cache(updated: dict[str, Any]) -> None:
    """Reflect a status/assignee change in the cached list right away, then
    schedule a real refresh so membership (JQL) is re-evaluated by Jira."""
    key = updated.get("key")
    if not key:
        return
    with _PINS_LIST_LOCK:
        items = _PINS_LIST_CACHE["items"]
        if items is not None:
            keep = updated.get("status") in DEFAULT_STATUSES
            new_items = [dict(updated) if p.get("key") == key else p for p in items if keep or p.get("key") != key]
            if keep and not any(p.get("key") == key for p in new_items):
                new_items.insert(0, dict(updated))
            _PINS_LIST_CACHE["items"] = new_items
    _refresh_pin_list_in_background()


@app.on_event("startup")
def _start_pin_list_warmer() -> None:
    if os.environ.get("PINS_LIST_WARM", "1") != "0":
        threading.Thread(target=_pin_list_warm_loop, name="pins-warm", daemon=True).start()


@app.get("/api/pins")
def list_pins(refresh: bool = False) -> dict[str, Any]:
    with _PINS_LIST_LOCK:
        items = _PINS_LIST_CACHE["items"]
        ts = _PINS_LIST_CACHE["ts"]
    if refresh or items is None:
        items = _refresh_pin_list(wait=True) or []
        return {"items": items, "cached": False, "age": 0}
    # Note: a list restored from disk is served immediately even while the
    # startup warm-up is still fetching; visits never wait on Jira.
    age = time.time() - ts
    if age > _PINS_LIST_TTL:
        _refresh_pin_list_in_background()
    return {"items": items, "cached": True, "age": round(age)}


_WEEKLY_CACHE: dict[str, Any] = {"key": "", "ts": 0.0, "data": None}
_WEEKLY_TTL = 600.0


@app.get("/api/pins/weekly-report")
def pins_weekly_report(refresh: bool = False) -> dict[str, Any]:
    """Per full calendar week (Mon-Sun) for the last 4 weeks, oldest first:
    PINs created, and PINs whose status changed (i.e. were handled)."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date, timedelta

    this_monday = date.today() - timedelta(days=date.today().weekday())
    cache_key = this_monday.isoformat()
    if (
        not refresh
        and _WEEKLY_CACHE["key"] == cache_key
        and time.time() - _WEEKLY_CACHE["ts"] < _WEEKLY_TTL
    ):
        return _WEEKLY_CACHE["data"]

    account_id = _profile().get("account_id") or ""
    if not account_id:
        raise HTTPException(500, "account_id missing from profile")
    who = f'assignee WAS IN ("{account_id}")'

    def count(jql: str) -> int:
        return len(_jira_search(jql, ["key"], limit=1000))

    def one_week(i: int) -> dict[str, Any]:
        start = this_monday - timedelta(days=7 * i)
        end = start + timedelta(days=7)
        s, e = start.isoformat(), end.isoformat()
        return {
            "week_start": s,
            "week_end": (end - timedelta(days=1)).isoformat(),
            "created": count(
                f'project = PIN AND {who} AND created >= "{s}" AND created < "{e}"'
            ),
            "handled": count(
                f'project = PIN AND {who} AND status CHANGED DURING ("{s}", "{e}")'
            ),
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        weeks = list(pool.map(one_week, [4, 3, 2, 1]))
    data = {"weeks": weeks}
    _WEEKLY_CACHE.update({"key": cache_key, "ts": time.time(), "data": data})
    return data


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
        _PIN_CACHE.setdefault(key, {}).pop("translation_hashes", None)
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


def _prepare_analysis(key: str, body: AnalyzeRequest | None, force: bool) -> tuple[dict[str, Any] | None, str, str]:
    """Shared prep for the analyze endpoints.

    Returns ``(cached_result, text_hash, user_prompt)``. ``cached_result`` is
    non-None when a fresh cache entry matches the full-input hash and ``force``
    is False; callers should return it as-is without calling the LLM.
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
            return entry["result"], text_hash, ""

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
    return None, text_hash, user_prompt


def _analysis_request(user_prompt: str, *, stream: bool) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build URL/headers/payload for the analysis LLM call (JSON-mode)."""
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
    if stream:
        req_payload["stream"] = True
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if stream:
        headers["Accept"] = "text/event-stream"
    return url, headers, req_payload


def _finalize_analysis(key: str, content: str, text_hash: str) -> dict[str, Any]:
    """Parse the model's JSON, normalise fields/labels, persist to cache."""
    if not content:
        raise HTTPException(502, "LLM response empty content")
    try:
        obj = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, f"LLM returned invalid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise HTTPException(502, "LLM returned non-object JSON")
    result: dict[str, Any] = {}
    for k in ANALYSIS_KEYS:
        v = _coerce_field_text(obj.get(k))
        result[k] = v if v else "暂无描述"
    if _LABEL_MODULES:
        result["labels"] = normalize_labels(obj.get("labels"), _LABEL_MODULES, _LABEL_NATURES)

    _PIN_CACHE.setdefault(key, {})["analysis"] = {"result": result, "ts": time.time(), "hash": text_hash}
    _save_pin_cache()
    return result


_JSON_SIMPLE_ESCAPES = {
    '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t",
}


def _partial_json_strings(buf: str, keys: tuple[str, ...]) -> dict[str, str]:
    """Extract top-level string values for ``keys`` from a possibly-truncated JSON object.

    Used to drive the typewriter effect: as the model streams a JSON object,
    we want to show each field's text as it grows, including the string that
    is currently open (unterminated). Only string values are returned; a field
    whose value is an array/object/number is left out and appears when the
    final ``json.loads`` runs. A trailing lone backslash (escape split across
    chunks) is dropped until the next chunk completes it.
    """
    out: dict[str, str] = {}
    n = len(buf)
    i = 0
    depth = 0

    def read_string(pos: int) -> tuple[str, int, bool]:
        """Read a JSON string whose opening quote is at ``pos``.

        Returns ``(decoded, next_index, closed)``.
        """
        j = pos + 1
        chars: list[str] = []
        while j < n:
            c = buf[j]
            if c == '"':
                return "".join(chars), j + 1, True
            if c == "\\":
                if j + 1 >= n:
                    break  # escape split across chunks; wait for more
                e = buf[j + 1]
                if e == "u":
                    if j + 6 > n:
                        break
                    try:
                        chars.append(chr(int(buf[j + 2 : j + 6], 16)))
                    except ValueError:
                        pass
                    j += 6
                    continue
                chars.append(_JSON_SIMPLE_ESCAPES.get(e, e))
                j += 2
                continue
            chars.append(c)
            j += 1
        return "".join(chars), n, False

    def skip_ws(pos: int) -> int:
        while pos < n and buf[pos] in " \t\r\n":
            pos += 1
        return pos

    while i < n:
        c = buf[i]
        if c == "{" or c == "[":
            depth += 1
            i += 1
            continue
        if c == "}" or c == "]":
            depth -= 1
            i += 1
            continue
        if c == '"':
            key, i, closed = read_string(i)
            if not closed:
                break
            if depth != 1:
                continue
            j = skip_ws(i)
            if j >= n or buf[j] != ":":
                continue  # a string value at depth 1 we don't care about
            j = skip_ws(j + 1)
            if j >= n:
                break
            if buf[j] == '"':
                val, i, _closed = read_string(j)
                if key in keys:
                    out[key] = val
                continue
            # Non-string value: skip it (nested container or scalar) so we
            # don't mistake its inner strings for top-level keys.
            if buf[j] in "{[":
                i = j  # let the main loop track depth for the container
                continue
            k = j
            while k < n and buf[k] not in ",}]":
                k += 1
            i = k
            continue
        i += 1
    return out


@app.post("/api/pins/{key}/analyze")
def analyze_pin(key: str, body: AnalyzeRequest | None = None, force: bool = False) -> dict[str, Any]:
    """Run LLM analysis for a single PIN.

    Results are cached to ``web/cache/pin_cache.json`` (TTL 7 days) under
    ``_PIN_CACHE[key]["analysis"]``. Pass ``?force=true`` to bypass the cache
    and refresh (Re-analyze button).
    """
    cached, text_hash, user_prompt = _prepare_analysis(key, body, force)
    if cached is not None:
        return cached
    url, headers, req_payload = _analysis_request(user_prompt, stream=False)
    try:
        data = request_json(
            url,
            method="POST",
            headers=headers,
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
    return _finalize_analysis(key, content, text_hash)


@app.post("/api/pins/{key}/analyze/stream")
def analyze_pin_stream(key: str, body: AnalyzeRequest | None = None, force: bool = False):
    """Streaming variant of ``analyze_pin`` (NDJSON) for the typewriter effect.

    Lines:
      {"cached": true, "result": {...}}   cache hit — no LLM call, single line
      {"partial": {"problem": "...", ...}} growing snapshot of the string fields
                                          parsed so far from the model's JSON
      {"result": {...}}                   final normalised result (also cached)
      {"error": "..."}                    LLM/parse failure after headers were sent
    Errors before the first byte (404 PIN, missing key) are normal HTTP errors.
    """
    cached, text_hash, user_prompt = _prepare_analysis(key, body, force)
    if cached is not None:
        return {"cached": True, "result": cached}
    url, headers, req_payload = _analysis_request(user_prompt, stream=True)
    req = Request(url, data=json.dumps(req_payload).encode("utf-8"), method="POST", headers=headers)
    ctx = ssl_context("PIN_REPORT_INSECURE_SSL")
    try:
        resp = urlopen(req, context=ctx, timeout=_LLM_TIMEOUT)
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        except Exception:
            pass
        raise HTTPException(502, f"LLM analysis failed: {detail or exc.reason}") from exc
    except Exception as exc:
        raise HTTPException(502, f"LLM analysis connect failed: {exc}") from exc

    def gen():
        buf = ""
        last_sent: dict[str, str] = {}
        try:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.startswith("data:"):
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
                if not delta:
                    continue
                buf += delta
                partial = _partial_json_strings(buf, ANALYSIS_KEYS)
                if partial != last_sent:
                    last_sent = partial
                    yield json.dumps({"partial": partial}, ensure_ascii=False) + "\n"
            result = _finalize_analysis(key, buf.strip(), text_hash)
            yield json.dumps({"result": result}, ensure_ascii=False) + "\n"
        except HTTPException as exc:
            yield json.dumps({"error": str(exc.detail)}, ensure_ascii=False) + "\n"
        except Exception as exc:  # noqa: BLE001 - surface to client, never crash
            yield json.dumps({"error": str(exc)}, ensure_ascii=False) + "\n"
        finally:
            try:
                resp.close()
            except Exception:
                pass

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    result = _issue_to_pin_summary(issue)
    _patch_pin_list_cache(result)
    return result


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
    result = _issue_to_pin_summary(issue)
    _patch_pin_list_cache(result)
    return result


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


class TranslateRequest(BaseModel):
    text: str = ""
    to: str = "zh"
    pin_key: str = ""
    field: str = ""


_TRANSLATE_MAX_TOKENS = int(os.environ.get("TRANSLATE_MAX_TOKENS", "4000"))
_TRANSLATE_TRUNCATED_MARK = "\n\n[翻译因长度限制被截断]"
_TRANSLATE_INFLIGHT: dict[tuple[str, str], threading.Lock] = {}
_TRANSLATE_INFLIGHT_LOCK = threading.Lock()


def _text_hash(text: str) -> str:
    # Prompt version is part of the hash so a prompt change re-translates everything lazily.
    return hashlib.sha256(f"{PROMPT_VERSION}\x00{text}".encode("utf-8")).hexdigest()[:12]


def _translation_lock(pin_key: str, field: str) -> threading.Lock:
    with _TRANSLATE_INFLIGHT_LOCK:
        lock = _TRANSLATE_INFLIGHT.get((pin_key, field))
        if lock is None:
            lock = threading.Lock()
            _TRANSLATE_INFLIGHT[(pin_key, field)] = lock
        return lock


def _cached_translation(pin_key: str, field: str, text: str) -> str | None:
    """Return a cached translation for (pin, field) if it still matches ``text``."""
    entry = _PIN_CACHE.get(pin_key, {})
    existing = (entry.get("translations") or {}).get(field)
    if not existing:
        return None
    stored_hash = (entry.get("translation_hashes") or {}).get(field)
    # Entries without a hash predate the domain-aware prompt (and the 1000-token
    # truncation fix): treat them as stale so they are redone on next view.
    if stored_hash and stored_hash == _text_hash(text):
        return existing
    return None


def _translate(text: str, to: str, pin_key: str, field: str) -> dict[str, Any]:
    """Translate text using the configured LLM, with persistent per-PIN cache.

    Cache key is (pin_key, field), validated against a hash of the source text
    so an edited description/form field is re-translated instead of showing a
    stale result. Without PIN context the result is not cached. Concurrent
    requests for the same (pin, field) coalesce into a single LLM call.
    Returns ``{"translated": "...", "cached": bool}``.
    """
    if not text.strip():
        return {"translated": "", "cached": False}

    cacheable = bool(pin_key and field)
    if cacheable:
        existing = _cached_translation(pin_key, field, text)
        if existing:
            return {"translated": existing, "cached": True}

    lang_map = {"zh": "简体中文", "en": "英文"}
    target_lang = lang_map.get(to, to)
    system = translate_system_prompt(target_lang)
    model = os.environ.get("TRANSLATE_LLM_MODEL", DEFAULT_TRANSLATE_MODEL)

    def call_llm() -> tuple[str, bool]:
        translated, finish_reason = _llm_chat_full(
            system, text, max_tokens=_TRANSLATE_MAX_TOKENS, temperature=0.1, model=model,
        )
        if not translated:
            raise HTTPException(502, "LLM returned an empty translation")
        truncated = finish_reason == "length"
        if truncated:
            # Truncated output: return it (better than nothing) but never cache it.
            translated += _TRANSLATE_TRUNCATED_MARK
        return translated, truncated

    if not cacheable:
        return {"translated": call_llm()[0], "cached": False}

    lock = _translation_lock(pin_key, field)
    with lock:
        # Another request may have finished the same translation while we waited.
        existing = _cached_translation(pin_key, field, text)
        if existing:
            return {"translated": existing, "cached": True}
        translated, truncated = call_llm()
        if not truncated:
            with _PIN_CACHE_LOCK:
                entry = _PIN_CACHE.setdefault(pin_key, {})
                entry.setdefault("translations", {})[field] = translated
                entry.setdefault("translation_hashes", {})[field] = _text_hash(text)
            _save_pin_cache()
    return {"translated": translated, "cached": False}


@app.post("/api/translate")
def translate_text_post(payload: TranslateRequest) -> dict[str, Any]:
    """Preferred entry point: JSON body avoids URL length limits on long texts."""
    return _translate(payload.text, payload.to, payload.pin_key, payload.field)


@app.get("/api/translate")
def translate_text(text: str = "", to: str = "zh", pin_key: str = "", field: str = "") -> dict[str, Any]:
    return _translate(text, to, pin_key, field)


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

    fname = filename or alt or ""
    # REST API first (most reliable), then temporary attachment URL
    urls = [f"{base}/rest/api/3/attachment/content/{media_id}"]
    if fname:
        urls.append(f"{base}/secure/temporaryattachment/{media_id}/{fname}")

    last_err = ""
    for url in urls:
        try:
            status, resp_headers, content = request_raw(
                url, headers={"Authorization": f"Basic {auth}"}, insecure_env_var="JIRA_INSECURE_SSL",
            )
            if status >= 400:
                last_err = f"{url}: HTTP {status}"
                continue
            content_type = resp_headers.get("Content-Type") or "application/octet-stream"
            return Response(
                content=content,
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
    url = f"{base}/rest/api/3/attachment/thumbnail/{media_id}"
    try:
        status, resp_headers, content = request_raw(
            url, headers={"Authorization": f"Basic {auth}"}, insecure_env_var="JIRA_INSECURE_SSL",
        )
        if status < 400:
            content_type = resp_headers.get("Content-Type") or "image/png"
            return Response(
                content=content,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )
    except Exception:
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
