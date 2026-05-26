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
import random
import re
import sys
from typing import Any, TypeAlias

import httpx

from .auth import CatalystCenterAuth
from .config import PaginationConfig, RetryConfig
from .loader import OperationSpec, SpecIndex
from .pagination import CursorPaginator, OffsetPaginator, Paginator

_MUTATING_METHODS = frozenset({"post", "put", "delete", "patch"})

_RESERVED_PARAM_KEYS = ("_max_pages", "_page_size", "_auto_follow")


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
    ):
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._index: SpecIndex | None = None
        self._pagination_cfg = pagination or PaginationConfig()
        self._retry_cfg = retry or RetryConfig()
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

    async def call(self, action_name: str, params: dict[str, Any]) -> DispatchResult:
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

        return await self._execute_with_retry(op, params)

    async def _execute_with_retry(
        self, op: OperationSpec, params: dict[str, Any]
    ) -> DispatchResult:
        clean_params, overrides = _strip_reserved(params)
        auto_follow = overrides.get("_auto_follow", True)

        paginator = (
            _pick_paginator(op.pagination)
            if (self._pagination_cfg.enabled and auto_follow)
            else None
        )

        if paginator is None:
            return await self._execute_one_with_retry(op, clean_params)

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

        return await paginator.paginate(
            op,
            clean_params,
            self._execute_one_with_retry,
            max_pages=max_pages,
            page_size=page_size,
        )

    async def _execute_one_with_retry(
        self, op: OperationSpec, params: dict[str, Any]
    ) -> DispatchResult:
        response = await self._execute(op, params)
        if isinstance(response, dict) and response.get("_token_expired"):
            print("[dispatcher] Token expired — re-authenticating", file=sys.stderr)
            stale_token = self._auth._token
            async with self._auth_lock:
                # Double-check: if another concurrent call already refreshed
                # while we waited for the lock, the token will have changed.
                if self._auth._token == stale_token:
                    await self._auth.login(self._client)
            response = await self._execute(op, params)
            if isinstance(response, dict) and response.get("_token_expired"):
                # Persistent 401 after re-auth — surface as a proper error
                # envelope rather than the internal sentinel.
                return {
                    "error": True,
                    "status_code": 401,
                    "message": (
                        "HTTP 401 after re-authentication — credentials may be "
                        "invalid or the token endpoint is rejecting them."
                    ),
                }
        return response

    async def _execute(self, op: OperationSpec, raw_params: dict[str, Any]) -> DispatchResult:
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
            url = url.replace(f"{{{name}}}", str(value))

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

        try:
            response = await self._send_with_retry(
                method=op.method.upper(),
                url=url,
                params=query_params or None,
                json=body_params if body_params else None,
                headers=headers,
                retryable=self._is_retryable(op.method),
            )
        except httpx.RequestError as exc:
            return {"error": True, "message": f"Request failed: {exc}"}

        if response.status_code == 401:
            return {"_token_expired": True}

        if response.is_error:
            return {
                "error": True,
                "status_code": response.status_code,
                "message": f"HTTP {response.status_code}",
                "body": _safe_json(response),
            }

        return _safe_json(response)

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
