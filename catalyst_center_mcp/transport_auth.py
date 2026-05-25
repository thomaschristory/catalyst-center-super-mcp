"""Bearer-token auth for the MCP server's SSE / streamable-HTTP transports.

Distinct from upstream Catalyst Center auth (see auth.py). Protects the
MCP server itself when exposed over the network. Verbatim port of sdwan's
transport_auth module.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""

from __future__ import annotations

from typing import Any


def make_bearer_middleware(*args: object, **kwargs: object) -> Any:
    raise NotImplementedError("scaffold only — implement per design doc")
