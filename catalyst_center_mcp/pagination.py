"""Pagination strategies for Catalyst Center endpoints.

Two strategies, detected at spec-load time and stored on
`OperationSpec.pagination`:

- "offset": classic offset + limit query params. Stops when a page returns
  fewer items than the configured size, or when the response list is empty.
- "cursor": opaque cursor token threaded through query params; server returns
  `nextCursor` in the response body. Stops when `nextCursor` is absent.

When auto-follow fires, the paginator wraps the response:

    {
        "response": [...combined items...],
        "version": <last seen>,
        "_paginated": {
            "pages": N,
            "truncated": bool,
            "next_cursor": dict | None,
        },
    }

Single-page calls still return the wrapped shape so the LLM can rely on the
`_paginated` key as the auto-follow signal.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from .loader import OperationSpec

Executor = Callable[[OperationSpec, dict[str, Any]], Awaitable[Any]]

# The list key Catalyst Center uses inside the {response, version} envelope
# is "response" itself. Fall back to the first list-typed top-level key if
# the server returns a non-standard envelope.
_DEFAULT_LIST_KEY = "response"


class Paginator(Protocol):
    async def paginate(
        self,
        op: OperationSpec,
        params: dict[str, Any],
        executor: Executor,
        max_pages: int,
        page_size: int | None,
    ) -> dict[str, Any]: ...


def _first_list_key(page: dict[str, Any]) -> str | None:
    if not isinstance(page, dict):
        return None
    if isinstance(page.get(_DEFAULT_LIST_KEY), list):
        return _DEFAULT_LIST_KEY
    for key, value in page.items():
        if isinstance(value, list):
            return str(key)
    return None


def _wrap(
    pages: list[dict[str, Any]],
    truncated: bool,
    next_cursor: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge `pages` into a single envelope under the discovered list key."""
    if not pages:
        return {
            "response": [],
            "version": "",
            "_paginated": {"pages": 0, "truncated": False, "next_cursor": None},
        }

    first = pages[0] if isinstance(pages[0], dict) else {}
    list_key = _first_list_key(first)

    stitched: list[Any] = []
    if list_key is not None:
        for page in pages:
            if isinstance(page, dict):
                items = page.get(list_key)
                if isinstance(items, list):
                    stitched.extend(items)

    out: dict[str, Any] = {k: v for k, v in first.items() if k != list_key}
    if list_key is not None:
        # Always expose stitched items under "response" so the wire shape is
        # predictable across endpoints that use unusual list-key names.
        out["response"] = stitched
    out["_paginated"] = {
        "pages": len(pages),
        "truncated": truncated,
        "next_cursor": next_cursor,
    }
    return out


class OffsetPaginator:
    """offset + limit pagination. Stops on a short page or an empty page."""

    async def paginate(
        self,
        op: OperationSpec,
        params: dict[str, Any],
        executor: Executor,
        max_pages: int,
        page_size: int | None,
    ) -> dict[str, Any]:
        pages: list[dict[str, Any]] = []
        current = dict(params)

        effective_size: int | None = page_size
        if effective_size is None and current.get("limit") is not None:
            try:
                effective_size = int(current["limit"])
            except (TypeError, ValueError):
                effective_size = None

        offset = int(current.get("offset", 0) or 0)
        next_cursor: dict[str, Any] | None = None
        truncated = False

        while len(pages) < max_pages:
            current["offset"] = offset
            if effective_size is not None:
                current["limit"] = effective_size
            page = await executor(op, current)
            page_dict = page if isinstance(page, dict) else {}
            pages.append(page_dict)

            list_key = _first_list_key(page_dict)
            items = page_dict.get(list_key) if list_key else None
            count = len(items) if isinstance(items, list) else 0

            if count == 0:
                break
            if effective_size is None:
                # No page-size hint — can't reliably detect a short page,
                # so stop after a single fetch rather than spinning.
                break
            if count < effective_size:
                break

            offset += count
        else:
            truncated = True
            next_cursor = {"offset": offset}
            if effective_size is not None:
                next_cursor["limit"] = effective_size

        return _wrap(pages, truncated=truncated, next_cursor=next_cursor)


class CursorPaginator:
    """Opaque-cursor pagination. Stops when `nextCursor` is absent in the response."""

    async def paginate(
        self,
        op: OperationSpec,
        params: dict[str, Any],
        executor: Executor,
        max_pages: int,
        page_size: int | None,
    ) -> dict[str, Any]:
        pages: list[dict[str, Any]] = []
        current = dict(params)
        if page_size is not None:
            current["limit"] = page_size

        cursor: str | None = current.get("cursor")
        truncated = False

        while len(pages) < max_pages:
            current["cursor"] = cursor
            page = await executor(op, current)
            page_dict = page if isinstance(page, dict) else {}
            pages.append(page_dict)

            next_token = page_dict.get("nextCursor") or page_dict.get("cursor")
            if not next_token:
                cursor = None
                break
            cursor = str(next_token)
        else:
            truncated = True

        next_cursor_obj = {"cursor": cursor} if (truncated and cursor) else None
        return _wrap(pages, truncated=truncated, next_cursor=next_cursor_obj)
