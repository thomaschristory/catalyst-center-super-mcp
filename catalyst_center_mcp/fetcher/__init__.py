"""Auto-fetch Catalyst Center OpenAPI specs from DevNet at startup.

Subpackage placeholder only. Real DevNet download flow is deferred —
the canonical URL discovery is non-trivial and out of scope for the
bootstrap session. config.yaml ships with `auto_fetch: false`; real
implementation will set the default to `true`.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""

from __future__ import annotations

from pathlib import Path


def fetch_spec(version: str, dest: Path) -> None:
    raise NotImplementedError("scaffold only — implement per design doc")
