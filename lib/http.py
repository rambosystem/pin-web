from __future__ import annotations

import http.client
import json
import os
import ssl
import threading
import time
from email.message import Message
from io import BytesIO
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlsplit

# Default per-request timeout (seconds) for outbound calls. Jira and the LLM
# API can occasionally hang; without a timeout a stuck call pins a worker
# thread forever and the whole app slows down.
DEFAULT_TIMEOUT = 60.0
# TCP connect + TLS handshake budget. Cross-border links from the deployment
# host occasionally black-hole a brand-new connection; a short handshake
# timeout plus one retry turns a 60 s stall into a few seconds.
CONNECT_TIMEOUT = float(os.environ.get("HTTP_CONNECT_TIMEOUT", "12"))

_SSL_CTX_LOCK = threading.Lock()
_SSL_CTX_CACHE: dict[bool, ssl.SSLContext] = {}


def ssl_context(insecure_env_var: str | None = None) -> ssl.SSLContext:
    """Return a (cached) SSL context. Building one loads the whole CA bundle,
    so it is created once per mode and shared."""
    insecure = bool(insecure_env_var and os.environ.get(insecure_env_var) == "1")
    with _SSL_CTX_LOCK:
        ctx = _SSL_CTX_CACHE.get(insecure)
        if ctx is not None:
            return ctx
        ctx = ssl.create_default_context()
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        else:
            try:
                import certifi

                ctx.load_verify_locations(certifi.where())
            except ImportError:
                pass
        _SSL_CTX_CACHE[insecure] = ctx
        return ctx


# ---------------------------------------------------------------------------
# Keep-alive connection pool
# ---------------------------------------------------------------------------
# A TLS handshake to Atlassian from the deployment host costs ~1.8 s, and the
# original urllib-based client opened a fresh connection for every call. This
# tiny pool keeps idle HTTP(S) connections per host and reuses them across
# requests (and across worker threads; a connection is never shared
# concurrently).

_POOL_LOCK = threading.Lock()
_POOL_IDLE: dict[tuple[str, str, int, bool], list[tuple[http.client.HTTPConnection, float]]] = {}
_POOL_MAX_IDLE_PER_HOST = 8
_POOL_IDLE_TTL = 90.0  # drop idle connections older than this (servers close them anyway)

_RETRYABLE = (
    http.client.RemoteDisconnected,
    http.client.BadStatusLine,
    http.client.CannotSendRequest,
    http.client.ResponseNotReady,
    BrokenPipeError,
    ConnectionResetError,
    ConnectionAbortedError,
    ssl.SSLError,
)


def _pool_key(scheme: str, host: str, port: int, insecure: bool) -> tuple[str, str, int, bool]:
    return (scheme, host, port, insecure)


def _new_connection(scheme: str, host: str, port: int, insecure_env_var: str | None, timeout: float):
    """Open a connection: connect + TLS under CONNECT_TIMEOUT (retried once on a
    stall), then switch the socket to the per-request read timeout."""
    connect_timeout = min(CONNECT_TIMEOUT, timeout)
    last_exc: Exception | None = None
    for _attempt in range(2):
        if scheme == "https":
            conn = http.client.HTTPSConnection(
                host, port, timeout=connect_timeout, context=ssl_context(insecure_env_var)
            )
        else:
            conn = http.client.HTTPConnection(host, port, timeout=connect_timeout)
        try:
            conn.connect()
        except (OSError, ssl.SSLError) as exc:  # socket.timeout is an OSError
            last_exc = exc
            _discard(conn)
            continue
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        return conn
    assert last_exc is not None
    raise last_exc


def _acquire(scheme: str, host: str, port: int, insecure_env_var: str | None, timeout: float):
    """Return (connection, reused_flag)."""
    insecure = bool(insecure_env_var and os.environ.get(insecure_env_var) == "1")
    key = _pool_key(scheme, host, port, insecure)
    now = time.time()
    with _POOL_LOCK:
        idle = _POOL_IDLE.get(key) or []
        while idle:
            conn, ts = idle.pop()
            if now - ts <= _POOL_IDLE_TTL:
                conn.timeout = timeout
                if conn.sock is not None:
                    try:
                        conn.sock.settimeout(timeout)
                    except OSError:
                        pass
                return conn, True
            try:
                conn.close()
            except Exception:
                pass
    return _new_connection(scheme, host, port, insecure_env_var, timeout), False


def _release(scheme: str, host: str, port: int, insecure_env_var: str | None, conn) -> None:
    insecure = bool(insecure_env_var and os.environ.get(insecure_env_var) == "1")
    key = _pool_key(scheme, host, port, insecure)
    with _POOL_LOCK:
        idle = _POOL_IDLE.setdefault(key, [])
        if len(idle) >= _POOL_MAX_IDLE_PER_HOST:
            try:
                conn.close()
            except Exception:
                pass
            return
        idle.append((conn, time.time()))


def _discard(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def request_raw(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    insecure_env_var: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, Message, bytes]:
    """Perform an HTTP request over a pooled keep-alive connection.

    Returns ``(status, headers, body_bytes)`` for any status. Follows up to 3
    redirects. A connection that turns out to be stale (server closed it while
    idle) is discarded and the request retried once on a fresh connection.
    """
    hdrs = {"Accept-Encoding": "identity"}
    hdrs.update(headers or {})

    for _redirect in range(4):
        parts = urlsplit(url)
        scheme = parts.scheme or "https"
        host = parts.hostname or ""
        port = parts.port or (443 if scheme == "https" else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        last_exc: Exception | None = None
        for attempt in range(2):
            conn, reused = _acquire(scheme, host, port, insecure_env_var, timeout)
            try:
                conn.request(method, path, body=body, headers=hdrs)
                resp = conn.getresponse()
                raw = resp.read()
            except _RETRYABLE as exc:
                _discard(conn)
                last_exc = exc
                # Only retry when the failure could be a stale pooled socket.
                if reused and attempt == 0:
                    continue
                raise
            except Exception:
                _discard(conn)
                raise
            if resp.will_close:
                _discard(conn)
            else:
                _release(scheme, host, port, insecure_env_var, conn)

            if resp.status in (301, 302, 303, 307, 308) and resp.getheader("Location"):
                url = resp.getheader("Location") or url
                if resp.status == 303 or (resp.status in (301, 302) and method == "POST"):
                    method, body = "GET", None
                break  # follow redirect
            return resp.status, resp.headers, raw
        else:  # pragma: no cover - loop exhausted without break/return
            if last_exc:
                raise last_exc
    raise HTTPError(url, 310, "Too many redirects", Message(), None)


def request_json(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
    insecure_env_var: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """JSON request helper (drop-in for the previous urllib implementation).

    Raises ``urllib.error.HTTPError`` for 4xx/5xx so existing callers that
    inspect ``exc.code`` / ``exc.read()`` keep working.
    """
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    hdrs = dict(headers or {})
    if payload is not None and not any(k.lower() == "content-type" for k in hdrs):
        hdrs["Content-Type"] = "application/json"
    status, resp_headers, raw = request_raw(
        url, method=method, headers=hdrs, body=payload,
        insecure_env_var=insecure_env_var, timeout=timeout,
    )
    if status >= 400:
        raise HTTPError(url, status, http.client.responses.get(status, "Error"), resp_headers, BytesIO(raw))
    text = raw.decode("utf-8")
    return json.loads(text) if text else {}
