"""FastMCP server entry point.

`main()` is the script target declared in pyproject.toml. Wires up
config loading, spec loading, auth, dispatcher, tool registration, and
transport selection (stdio / sse / streamable-http).

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("scaffold only — implement per design doc")
