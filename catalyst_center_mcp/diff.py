"""Compare two bundled spec versions.

Verbatim port of sdwan's diff module. Used by the CLI `--diff` flag in
a later session; not invoked at scaffold time.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""

from __future__ import annotations

from typing import Any


def diff_versions(a: Any, b: Any) -> Any:
    raise NotImplementedError("scaffold only — implement per design doc")


def print_diff(diff: Any) -> None:
    raise NotImplementedError("scaffold only — implement per design doc")
