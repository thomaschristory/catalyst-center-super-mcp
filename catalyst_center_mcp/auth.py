"""Catalyst Center upstream authentication.

Single flow: HTTP Basic against POST /dna/system/api/v1/auth/token, returns
a token used as the `X-Auth-Token` header on every subsequent request.
Reactive refresh on 401. No JWT/session dual-mode (unlike sdwan).

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""

from __future__ import annotations

import httpx


class CatalystCenterAuth:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("scaffold only — implement per design doc")

    async def fetch_token(self, client: httpx.AsyncClient) -> str:
        raise NotImplementedError("scaffold only — implement per design doc")

    def header(self) -> dict[str, str]:
        raise NotImplementedError("scaffold only — implement per design doc")
