"""Credentials must be validated *before* spec loading at startup (#26).

Spec loading (and auto-fetch) is pointless without credentials, and the old
behaviour crashed on a missing YAML before credentials were ever read.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from catalyst_center_mcp import server


def test_require_credentials_fires_before_spec_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CATALYST_CENTER_USERNAME", raising=False)
    monkeypatch.delenv("CATALYST_CENTER_PASSWORD", raising=False)
    monkeypatch.chdir(tmp_path)  # empty dir: no YAML, no .env

    # If SpecLoader were reached it would raise this sentinel instead of the
    # credentials error — proving the credential check runs first.
    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("SpecLoader must not run before credentials are validated")

    monkeypatch.setattr(server, "SpecLoader", _boom)

    args = server.parse_args([])
    with pytest.raises(RuntimeError, match="credentials"):
        asyncio.run(server._connect_and_register(args))
