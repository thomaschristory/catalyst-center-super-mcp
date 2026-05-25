"""Pagination strategies for Catalyst Center endpoints.

Verbatim port of sdwan's pagination module. Primary strategy is
offset/limit (Catalyst Center's dominant convention). Hybrid
auto-follow + cursor support driven by config.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""

from __future__ import annotations

from typing import Any


async def paginate(*args: object, **kwargs: object) -> Any:
    raise NotImplementedError("scaffold only — implement per design doc")
