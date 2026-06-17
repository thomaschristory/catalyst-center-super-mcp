"""httpx async client for Catalyst Center API calls.

Handles:
  - Auth via CatalystCenterAuth (single token-based flow)
  - Reactive re-login + retry on 401
  - Path-param substitution; query/body routing per the OpenAPI spec
  - Configurable retry on transient failures (502/503/504 by default)
  - Pagination auto-follow with reserved-param overrides

Reserved param keys (stripped before HTTP):
  _max_pages    (int)   override config.pagination.max_pages
  _page_size    (int)   override config.pagination.page_size
  _auto_follow  (bool)  if False, force single-page mode for paginatable ops
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import sys
import time
from typing import Any, TypeAlias
from urllib.parse import quote

import httpx

from .auth import CatalystCenterAuth
from .config import DebugConfig, PaginationConfig, RetryConfig
from .loader import OperationSpec, SpecIndex
from .pagination import CursorPaginator, OffsetPaginator, Paginator

_MUTATING_METHODS = frozenset({"post", "put", "delete", "patch"})

_RESERVED_PARAM_KEYS = ("_max_pages", "_page_size", "_auto_follow")

# Headers whose values are auth secrets — redacted from debug capture by
# default (#31). Compared case-insensitively. Covers both request-side
# (X-Auth-Token / Authorization / Cookie) and response-side (Set-Cookie).
_SENSITIVE_HEADERS = frozenset(
    {"x-auth-token", "authorization", "cookie", "set-cookie", "proxy-authorization"}
)
_REDACTED = "<redacted>"

# Body/query keys whose VALUES are credentials and must be masked when redaction
# is on (#31). Header redaction alone is not enough: Catalyst Center's own auth
# endpoint returns the credential *in the response body* — POST
# /dna/system/api/v1/auth/token yields {"Token": "<live JWT>"}. Matched
# case-insensitively as a substring of the key, so this also catches
# sessionId / apiKey etc.
_SENSITIVE_KEY_RE = re.compile(
    r"token|secret|password|passwd|passphrase|credential|cookie|"
    r"api[_-]?key|session[_-]?id|authorization|private[_-]?key",
    re.IGNORECASE,
)

# Captured bodies are truncated past this many serialized chars so an opt-in
# debug session can't silently double or overflow a tool result with a large
# upstream payload (#31).
_MAX_DEBUG_BODY_CHARS = 20_000


def _pick_paginator(style: str | None) -> Paginator | None:
    if style == "offset":
        return OffsetPaginator()
    if style == "cursor":
        return CursorPaginator()
    return None


DispatchResult: TypeAlias = dict[str, Any] | list[Any] | str


class Dispatcher:
    def __init__(
        self,
        base_url: str,
        auth: CatalystCenterAuth,
        verify_ssl: bool = True,
        timeout: float = 30.0,
        pagination: PaginationConfig | None = None,
        retry: RetryConfig | None = None,
        debug: DebugConfig | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._index: SpecIndex | None = None
        self._pagination_cfg = pagination or PaginationConfig()
        self._retry_cfg = retry or RetryConfig()
        self._debug_cfg = debug or DebugConfig()
        self._auth_lock = asyncio.Lock()

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            verify=verify_ssl,
            timeout=timeout,
            follow_redirects=False,
        )

    async def connect(self) -> None:
        """Authenticate against Catalyst Center. Must be called before any tool calls."""
        await self._auth.login(self._client)

    async def close(self) -> None:
        await self._client.aclose()

    def set_index(self, index: SpecIndex) -> None:
        self._index = index

    async def call(
        self, action_name: str, params: dict[str, Any], tool_name: str | None = None
    ) -> DispatchResult:
        if self._index is None:
            raise RuntimeError("SpecIndex not set — call set_index() first")

        async with self._auth_lock:
            if self._auth.needs_refresh():
                print(
                    "[dispatcher] Token nearing expiry — proactive refresh",
                    file=sys.stderr,
                )
                await self._auth.login(self._client)

        op = self._index.by_action_name.get(action_name)
        if op is None:
            return {
                "error": True,
                "message": (
                    f"Unknown action: '{action_name}'. "
                    f"Check the tool description for valid action names."
                ),
            }

        return await self._execute_with_retry(op, params, tool_name)

    async def _execute_with_retry(
        self, op: OperationSpec, params: dict[str, Any], tool_name: str | None = None
    ) -> DispatchResult:
        clean_params, overrides = _strip_reserved(params)
        auto_follow = overrides.get("_auto_follow", True)

        paginator = (
            _pick_paginator(op.pagination)
            if (self._pagination_cfg.enabled and auto_follow)
            else None
        )

        if paginator is None:
            return await self._execute_one_with_retry(op, clean_params, tool_name)

        max_pages_override = overrides.get("_max_pages")
        max_pages = (
            int(max_pages_override)
            if max_pages_override is not None
            else self._pagination_cfg.max_pages
        )
        page_size_override = overrides.get("_page_size")
        page_size = (
            int(page_size_override)
            if page_size_override is not None
            else self._pagination_cfg.page_size
        )

        # Bind tool_name into the per-page executor the paginator drives, so
        # captured debug records carry the calling tool without widening the
        # Paginator.paginate(op, params, executor) contract.
        async def _run_page(o: OperationSpec, p: dict[str, Any]) -> DispatchResult:
            return await self._execute_one_with_retry(o, p, tool_name)

        return await paginator.paginate(
            op,
            clean_params,
            _run_page,
            max_pages=max_pages,
            page_size=page_size,
        )

    async def _execute_one_with_retry(
        self, op: OperationSpec, params: dict[str, Any], tool_name: str | None = None
    ) -> DispatchResult:
        response = await self._execute(op, params, tool_name)
        if isinstance(response, dict) and response.get("_token_expired"):
            print("[dispatcher] Token expired — re-authenticating", file=sys.stderr)
            stale_token = self._auth._token
            async with self._auth_lock:
                # Double-check: if another concurrent call already refreshed
                # while we waited for the lock, the token will have changed.
                if self._auth._token == stale_token:
                    await self._auth.login(self._client)
            # The first 401 was the transparent retry round and is intentionally
            # not captured. This is the *retried* round: a 401 here is a real,
            # persistent failure, so let _execute capture it like any other error.
            response = await self._execute(op, params, tool_name, capture_401=True)
            if isinstance(response, dict) and response.get("_token_expired"):
                # Persistent 401 after re-auth — surface as a proper error
                # envelope rather than the internal sentinel. Carry the debug
                # record (built from the second 401 inside _execute) so this
                # error class — bad creds / token endpoint rejecting them — is as
                # diagnosable as every other HTTP error (#31).
                error: dict[str, Any] = {
                    "error": True,
                    "status_code": 401,
                    "message": (
                        "HTTP 401 after re-authentication — credentials may be "
                        "invalid or the token endpoint is rejecting them."
                    ),
                }
                dbg = response.get("debug")
                if dbg is not None:
                    error["debug"] = dbg
                return error
        return response

    async def _execute(
        self,
        op: OperationSpec,
        raw_params: dict[str, Any],
        tool_name: str | None = None,
        *,
        capture_401: bool = False,
    ) -> DispatchResult:
        path_param_names = {p.name for p in op.parameters if p.location == "path"}
        query_param_names = {p.name for p in op.parameters if p.location == "query"}

        path_params: dict[str, Any] = {}
        query_params: dict[str, Any] = {}
        body_params: dict[str, Any] = {}
        unknown_params: dict[str, Any] = {}

        for key, value in (raw_params or {}).items():
            if value is None:
                continue
            if key in path_param_names:
                path_params[key] = value
            elif key in query_param_names:
                query_params[key] = value
            elif op.has_body and op.method in ("post", "put", "patch"):
                body_params[key] = value
            else:
                unknown_params[key] = value

        if unknown_params:
            print(
                f"[dispatcher] WARNING: unrecognised params for '{op.action_name}': "
                f"{list(unknown_params.keys())} — forwarding as query params",
                file=sys.stderr,
            )
            query_params.update(unknown_params)

        url = op.path
        for name, value in path_params.items():
            # Percent-encode each path-param value before substitution so a
            # value containing '/', '..', '?', or '#' cannot alter the path
            # structure (path-injection / segment-escape). quote() with
            # safe='' leaves alphanumerics and '-._~' unescaped, so legitimate
            # UUIDs and dotted IPs survive unchanged.
            url = url.replace(f"{{{name}}}", quote(str(value), safe=""))

        if "{" in url:
            missing = re.findall(r"\{([^}]+)\}", url)
            return {
                "error": True,
                "message": (
                    f"Missing required path param(s) for '{op.action_name}': {missing}. "
                    f"Provide them in the params dict."
                ),
            }

        headers = {
            "Content-Type": "application/json",
            **self._auth.header(),
        }

        sent_body = body_params if body_params else None
        debug_on = self._debug_cfg.enabled
        started = time.monotonic()

        try:
            response = await self._send_with_retry(
                method=op.method.upper(),
                url=url,
                params=query_params or None,
                json=sent_body,
                headers=headers,
                retryable=self._is_retryable(op.method),
            )
        except httpx.RequestError as exc:
            result: dict[str, Any] = {"error": True, "message": f"Request failed: {exc}"}
            if debug_on:
                dbg = self._build_debug(
                    op,
                    tool_name,
                    url,
                    query_params,
                    sent_body,
                    headers,
                    response=None,
                    elapsed_ms=_elapsed_ms(started),
                    request_error=str(exc),
                )
                self._emit_debug(dbg)
                result["debug"] = dbg
            return result

        # 401 → internal token-expiry round we retry transparently, so it is
        # intentionally not captured on the first round. On the *retried* round
        # (capture_401=True) a 401 is a persistent auth rejection — the single
        # error class users most need to debug (bad creds / token endpoint
        # rejecting them) — so capture it like any other HTTP error (#31). The
        # record rides on the sentinel for _execute_one_with_retry to surface.
        if response.status_code == 401:
            sentinel: dict[str, Any] = {"_token_expired": True}
            if capture_401 and debug_on:
                dbg = self._build_debug(
                    op,
                    tool_name,
                    url,
                    query_params,
                    sent_body,
                    headers,
                    response=response,
                    elapsed_ms=_elapsed_ms(started),
                )
                self._emit_debug(dbg)
                sentinel["debug"] = dbg
            return sentinel

        elapsed_ms = _elapsed_ms(started)

        if response.is_error:
            result = {
                "error": True,
                "status_code": response.status_code,
                "message": f"HTTP {response.status_code}",
                "body": _safe_json(response),
            }
            # A failed upstream call is captured under BOTH capture modes —
            # diagnosing failures is the whole point of debug mode (#31).
            if debug_on:
                dbg = self._build_debug(
                    op,
                    tool_name,
                    url,
                    query_params,
                    sent_body,
                    headers,
                    response=response,
                    elapsed_ms=elapsed_ms,
                )
                self._emit_debug(dbg)
                result["debug"] = dbg
            return result

        data = _safe_json(response)
        if debug_on and self._debug_cfg.capture == "all":
            dbg = self._build_debug(
                op,
                tool_name,
                url,
                query_params,
                sent_body,
                headers,
                response=response,
                elapsed_ms=elapsed_ms,
            )
            self._emit_debug(dbg)
            # Only dict results can carry the debug object without reshaping the
            # payload; list/str successes are logged to stderr only (honest, no
            # silent wrapping that would confuse the LLM consumer).
            if isinstance(data, dict) and "debug" not in data:
                data = {**data, "debug": dbg}

        return data

    def _is_retryable(self, method: str) -> bool:
        if method.lower() in _MUTATING_METHODS:
            return self._retry_cfg.retry_mutating
        return True

    async def _send_with_retry(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None,
        json: dict[str, Any] | None,
        headers: dict[str, str],
        retryable: bool,
    ) -> httpx.Response:
        cfg = self._retry_cfg
        attempts = max(1, cfg.max_attempts) if retryable else 1
        last_response: httpx.Response | None = None

        for attempt in range(attempts):
            try:
                response = await self._client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                    headers=headers,
                )
            except httpx.RequestError:
                if attempt + 1 >= attempts:
                    raise
                await self._sleep_backoff(attempt)
                continue

            if response.status_code in cfg.statuses and attempt + 1 < attempts:
                last_response = response
                await self._sleep_backoff(attempt)
                continue

            return response

        assert last_response is not None
        return last_response

    async def _sleep_backoff(self, attempt: int) -> None:
        cfg = self._retry_cfg
        if cfg.backoff_base <= 0:
            return
        raw = min(cfg.backoff_cap, cfg.backoff_base * (2**attempt))
        half = raw / 2
        delay = half + random.uniform(0, half)
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # Debug capture (#31)
    # ------------------------------------------------------------------

    def _build_debug(
        self,
        op: OperationSpec,
        tool_name: str | None,
        path: str,
        query_params: dict[str, Any],
        body: dict[str, Any] | None,
        request_headers: dict[str, str],
        *,
        response: httpx.Response | None,
        elapsed_ms: float,
        request_error: str | None = None,
    ) -> dict[str, Any]:
        """Assemble the structured ``debug`` record for one upstream exchange.

        Captures exactly what was sent (resolved path, query, the serialized
        body — which is where the ``params``-becomes-body gotcha shows up) and
        what came back (status, error code, headers, body). When redaction is
        on, auth headers AND credential-shaped body/query values are masked, and
        oversized bodies are truncated."""
        redact = self._debug_cfg.redact
        dbg: dict[str, Any] = {
            "tool": tool_name,
            "action": op.action_name,
            "operation_id": op.operation_id,
            "timing_ms": round(elapsed_ms, 1),
            "request": {
                "method": op.method.upper(),
                "path": path,
                "url": f"{self._base_url}{path}",
                "query_params": _redact_data(dict(query_params), redact),
                "body": _cap_body(_redact_data(body, redact)),
                "headers": _redact_headers(request_headers, redact),
            },
        }
        if request_error is not None:
            dbg["request_error"] = request_error
            return dbg
        if response is not None:
            resp_body = _safe_json(response)
            dbg["response"] = {
                "status_code": response.status_code,
                "error_code": _error_code(resp_body) or None,
                "headers": _redact_headers(dict(response.headers), redact),
                "body": _cap_body(_redact_data(resp_body, redact)),
            }
        return dbg

    def _emit_debug(self, dbg: dict[str, Any]) -> None:
        """Log one redacted debug record to stderr as a single JSON line."""
        print(f"[dispatcher][debug] {json.dumps(dbg, default=str)}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Debug helpers (#31)
# ---------------------------------------------------------------------------


def _elapsed_ms(started: float) -> float:
    """Milliseconds elapsed since a ``time.monotonic()`` mark."""
    return (time.monotonic() - started) * 1000.0


def _redact_headers(headers: dict[str, str], redact: bool) -> dict[str, str]:
    """Copy headers, masking auth-bearing ones when ``redact`` is on (#31)."""
    out: dict[str, str] = {}
    for key, value in (headers or {}).items():
        if redact and key.lower() in _SENSITIVE_HEADERS:
            out[key] = _REDACTED
        else:
            out[key] = value
    return out


def _redact_data(obj: Any, redact: bool) -> Any:
    """Recursively mask values under credential-shaped keys when ``redact`` is on.

    Header redaction alone leaks tokens that Catalyst Center returns *in the
    body*: the auth endpoint POST /dna/system/api/v1/auth/token responds with
    ``{"Token": "<live JWT>"}``. We walk the captured request/response body and
    query dict and replace the value of any key whose name matches
    ``_SENSITIVE_KEY_RE`` with ``<redacted>``, so a shared capture can't carry a
    replayable credential. Non-matching values (ordinary data, error codes)
    pass through untouched."""
    if not redact:
        return obj
    if isinstance(obj, dict):
        return {
            key: (_REDACTED if _SENSITIVE_KEY_RE.search(str(key)) else _redact_data(value, redact))
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_data(item, redact) for item in obj]
    return obj


def _cap_body(value: Any) -> Any:
    """Truncate an oversized captured body to keep debug records bounded (#31)."""
    if value is None:
        return None
    try:
        serialized = json.dumps(value, default=str)
    except Exception:
        serialized = str(value)
    if len(serialized) <= _MAX_DEBUG_BODY_CHARS:
        return value
    return {
        "_truncated": True,
        "_original_chars": len(serialized),
        "preview": serialized[:_MAX_DEBUG_BODY_CHARS],
    }


def _error_code(body: Any) -> str | None:
    """Pull Catalyst Center's error code out of a response body, if present.

    Catalyst Center error envelopes vary; the common shapes carry the code at
    the top level (``errorCode`` / ``code``) or nested under ``response`` /
    ``error``. The code is not a secret and is not masked."""
    if not isinstance(body, dict):
        return None
    for key in ("errorCode", "error_code", "code"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    for nested_key in ("response", "error"):
        nested = body.get(nested_key)
        if isinstance(nested, dict):
            code = _error_code(nested)
            if code:
                return code
    return None


def _safe_json(response: httpx.Response) -> DispatchResult:
    try:
        data = response.json()
    except Exception:
        return {"raw": response.text}
    if isinstance(data, (dict, list, str)):
        return data
    return {"raw": str(data)}


def _strip_reserved(
    params: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split reserved underscore keys out of params. Returns (clean, overrides)."""
    clean: dict[str, Any] = {}
    overrides: dict[str, Any] = {}
    for key, value in (params or {}).items():
        if key in _RESERVED_PARAM_KEYS:
            overrides[key] = value
        else:
            clean[key] = value
    return clean, overrides
