"""Request dispatch with auth, retry, and pagination.

Adapted from sdwan's dispatcher. Pagination param-name list extended to
include `offset` and `limit` (Catalyst Center's primary convention).
Reserved-param seam for future `_await_task: true` polling helper —
NOT implemented in v0.1.0; LLM orchestrates Catalyst Center's
`{taskId}` poll loop directly.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""

from __future__ import annotations

from typing import Any


class Dispatcher:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("scaffold only — implement per design doc")

    async def dispatch(self, action_name: str, params: dict[str, Any]) -> Any:
        raise NotImplementedError("scaffold only — implement per design doc")
