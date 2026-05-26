"""fetch_spec tests — unknown version, success, cleanup on failure, verify_ssl."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from catalyst_center_mcp.fetcher import (
    KNOWN_SPEC_URLS,
    SpecVersionUnknownError,
    fetch_spec,
)


@pytest.mark.asyncio
async def test_unknown_version_raises(tmp_path: Path):
    with pytest.raises(SpecVersionUnknownError) as exc_info:
        await fetch_spec("99.9.9", tmp_path)
    msg = str(exc_info.value)
    assert "99.9.9" in msg
    # Helpful: lists supported versions and points at the source URL of truth.
    for v in KNOWN_SPEC_URLS:
        assert v in msg
    assert "developer.cisco.com" in msg
    # No file written for unknown version.
    assert not list(tmp_path.iterdir()) or all(p.is_dir() for p in tmp_path.iterdir())
