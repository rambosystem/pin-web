from __future__ import annotations

import base64
from urllib.parse import quote


def basic_auth(email: str, token: str) -> str:
    return base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("utf-8")


def confluence_api_v2_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/wiki/api/v2{path}"


def jira_api_v3_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/rest/api/3{path}"


def quoted_title(title: str) -> str:
    return quote(title)
