"""Tests for offset and cursor paginators."""

from __future__ import annotations

from typing import Any

import pytest

from catalyst_center_mcp.loader import OperationSpec, ParameterSpec
from catalyst_center_mcp.pagination import CursorPaginator, OffsetPaginator


def _offset_op() -> OperationSpec:
    return OperationSpec(
        operation_id="x",
        action_name="x",
        summary="",
        method="get",
        path="/x",
        tag="X",
        parameters=[
            ParameterSpec(name="offset", location="query"),
            ParameterSpec(name="limit", location="query"),
        ],
        pagination="offset",
    )


def _cursor_op(method: str = "get") -> OperationSpec:
    return OperationSpec(
        operation_id="x",
        action_name="x",
        summary="",
        method=method,
        path="/x",
        tag="X",
        parameters=[
            ParameterSpec(name="cursor", location="query"),
            ParameterSpec(name="limit", location="query"),
        ],
        pagination="cursor",
    )


@pytest.mark.asyncio
async def test_offset_single_page_passes_through() -> None:
    page = {"response": [{"id": 1}, {"id": 2}], "version": "1.0"}

    async def executor(op: OperationSpec, params: dict[str, Any]) -> Any:
        return page

    out = await OffsetPaginator().paginate(_offset_op(), {}, executor, max_pages=5, page_size=None)
    # Single page → still wrapped with _paginated metadata, items merged into response list.
    assert out["response"] == [{"id": 1}, {"id": 2}]
    assert out["version"] == "1.0"
    assert out["_paginated"]["pages"] == 1
    assert out["_paginated"]["truncated"] is False
    assert out["_paginated"]["next_cursor"] is None


@pytest.mark.asyncio
async def test_offset_stitches_two_pages_then_short_page_stops() -> None:
    pages = [
        {"response": [1, 2, 3], "version": "1.0"},
        {"response": [4, 5], "version": "1.0"},  # short → stop
    ]
    seen: list[dict[str, Any]] = []

    async def executor(op: OperationSpec, params: dict[str, Any]) -> Any:
        seen.append(dict(params))
        return pages.pop(0)

    out = await OffsetPaginator().paginate(
        _offset_op(), {"limit": 3}, executor, max_pages=5, page_size=None
    )
    assert out["response"] == [1, 2, 3, 4, 5]
    assert out["_paginated"]["pages"] == 2
    assert out["_paginated"]["truncated"] is False
    # Offsets advance by limit (3): 0, 3.
    assert [c["offset"] for c in seen] == [0, 3]


@pytest.mark.asyncio
async def test_offset_truncated_at_max_pages() -> None:
    full_page = {"response": list(range(10)), "version": "1.0"}

    async def executor(op: OperationSpec, params: dict[str, Any]) -> Any:
        return full_page

    out = await OffsetPaginator().paginate(
        _offset_op(), {"limit": 10}, executor, max_pages=2, page_size=None
    )
    assert out["_paginated"]["pages"] == 2
    assert out["_paginated"]["truncated"] is True
    assert out["_paginated"]["next_cursor"] == {"offset": 20, "limit": 10}


@pytest.mark.asyncio
async def test_offset_empty_page_stops() -> None:
    async def executor(op: OperationSpec, params: dict[str, Any]) -> Any:
        return {"response": [], "version": "1.0"}

    out = await OffsetPaginator().paginate(
        _offset_op(), {"limit": 5}, executor, max_pages=5, page_size=None
    )
    assert out["response"] == []
    assert out["_paginated"]["pages"] == 1
    assert out["_paginated"]["truncated"] is False


@pytest.mark.asyncio
async def test_offset_page_size_override() -> None:
    pages = [{"response": [1, 2], "version": "1.0"}]
    seen: list[dict[str, Any]] = []

    async def executor(op: OperationSpec, params: dict[str, Any]) -> Any:
        seen.append(dict(params))
        return pages.pop()

    await OffsetPaginator().paginate(_offset_op(), {}, executor, max_pages=5, page_size=50)
    assert seen[0]["limit"] == 50


@pytest.mark.asyncio
async def test_cursor_single_page_no_next() -> None:
    async def executor(op: OperationSpec, params: dict[str, Any]) -> Any:
        return {"response": [{"id": 1}], "version": "1.0"}

    out = await CursorPaginator().paginate(_cursor_op(), {}, executor, max_pages=5, page_size=None)
    assert out["response"] == [{"id": 1}]
    assert out["_paginated"]["pages"] == 1
    assert out["_paginated"]["truncated"] is False


@pytest.mark.asyncio
async def test_cursor_stitches_pages() -> None:
    pages = [
        {"response": [1, 2], "nextCursor": "c1", "version": "1.0"},
        {"response": [3, 4], "nextCursor": "c2", "version": "1.0"},
        {"response": [5], "version": "1.0"},  # no nextCursor → stop
    ]
    seen: list[dict[str, Any]] = []

    async def executor(op: OperationSpec, params: dict[str, Any]) -> Any:
        seen.append(dict(params))
        return pages.pop(0)

    out = await CursorPaginator().paginate(_cursor_op(), {}, executor, max_pages=5, page_size=None)
    assert out["response"] == [1, 2, 3, 4, 5]
    assert out["_paginated"]["pages"] == 3
    assert out["_paginated"]["truncated"] is False
    # Cursor threaded through subsequent calls.
    assert [c.get("cursor") for c in seen] == [None, "c1", "c2"]


@pytest.mark.asyncio
async def test_cursor_truncated_emits_next_cursor() -> None:
    pages = [
        {"response": [1], "nextCursor": "c1", "version": "1.0"},
        {"response": [2], "nextCursor": "c2", "version": "1.0"},
    ]

    async def executor(op: OperationSpec, params: dict[str, Any]) -> Any:
        return pages.pop(0)

    out = await CursorPaginator().paginate(_cursor_op(), {}, executor, max_pages=2, page_size=None)
    assert out["_paginated"]["truncated"] is True
    assert out["_paginated"]["next_cursor"] == {"cursor": "c2"}


@pytest.mark.asyncio
async def test_cursor_post_preserves_body() -> None:
    pages = [{"response": [1], "version": "1.0"}]
    seen: list[dict[str, Any]] = []

    async def executor(op: OperationSpec, params: dict[str, Any]) -> Any:
        seen.append(dict(params))
        return pages.pop()

    await CursorPaginator().paginate(
        _cursor_op(method="post"),
        {"filter": {"severity": "critical"}},
        executor,
        max_pages=3,
        page_size=None,
    )
    assert seen[0]["filter"] == {"severity": "critical"}


@pytest.mark.asyncio
async def test_response_without_list_returns_passthrough() -> None:
    async def executor(op: OperationSpec, params: dict[str, Any]) -> Any:
        # No "response" list key — paginator must not crash, just stop after one page.
        return {"count": 4, "version": "1.0"}

    out = await OffsetPaginator().paginate(_offset_op(), {}, executor, max_pages=5, page_size=None)
    assert out["_paginated"]["pages"] == 1
    assert out["count"] == 4
