"""MCP tool registration from a loaded SpecIndex.

Verbatim port of sdwan's tools module. One MCP tool per ToolGroup;
description enumerates actions and their params. RW gate enforced
here — write tools are not registered when `read_write=False`.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""

from __future__ import annotations

from typing import Any


def register_tools(
    mcp: Any,
    index: Any,
    dispatcher: Any,
    read_write: bool,
) -> None:
    raise NotImplementedError("scaffold only — implement per design doc")
