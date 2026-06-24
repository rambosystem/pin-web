from __future__ import annotations

import json
import os
import ssl
from typing import Any
from urllib.request import Request, urlopen


def ssl_context(insecure_env_var: str | None = None) -> ssl.SSLContext:
    if insecure_env_var and os.environ.get(insecure_env_var) == "1":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    ctx = ssl.create_default_context()
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())
    except ImportError:
        pass
    return ctx


def request_json(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
    insecure_env_var: str | None = None,
) -> Any:
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    req = Request(url, data=payload, method=method, headers=headers or {})
    with urlopen(req, context=ssl_context(insecure_env_var)) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}
