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


@pytest.mark.asyncio
@respx.mock
async def test_success_writes_json(tmp_path: Path):
    url = KNOWN_SPEC_URLS["2.3.7.9"]
    body = b'{"openapi": "3.0.3", "paths": {}}'
    respx.get(url).mock(return_value=httpx.Response(200, content=body))

    async with httpx.AsyncClient() as c:
        result = await fetch_spec("2.3.7.9", tmp_path, client=c)

    assert result.exists()
    assert result.read_bytes() == body
    # No .tmp file left behind.
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
@respx.mock
async def test_network_error_no_partial_file(tmp_path: Path):
    url = KNOWN_SPEC_URLS["2.3.7.9"]
    respx.get(url).mock(side_effect=httpx.ConnectError("connection refused"))

    async with httpx.AsyncClient() as c:
        with pytest.raises(httpx.ConnectError):
            await fetch_spec("2.3.7.9", tmp_path, client=c)

    assert not list(tmp_path.glob("*.json"))
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
@respx.mock
async def test_invalid_json_no_partial_file(tmp_path: Path):
    url = KNOWN_SPEC_URLS["2.3.7.9"]
    respx.get(url).mock(return_value=httpx.Response(200, content=b"not-json"))

    async with httpx.AsyncClient() as c:
        with pytest.raises(json.JSONDecodeError):
            await fetch_spec("2.3.7.9", tmp_path, client=c)

    assert not list(tmp_path.glob("*.json"))
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
@respx.mock
async def test_http_error_status_no_partial_file(tmp_path: Path):
    url = KNOWN_SPEC_URLS["2.3.7.9"]
    respx.get(url).mock(return_value=httpx.Response(503, content=b"Service Unavailable"))

    async with httpx.AsyncClient() as c:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_spec("2.3.7.9", tmp_path, client=c)

    assert not list(tmp_path.glob("*.json"))
    assert not list(tmp_path.glob("*.tmp"))
