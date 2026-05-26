"""fetch_spec tests — unknown version, success, cleanup on failure, shape validation."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from catalyst_center_mcp.fetcher import (
    KNOWN_SPEC_URLS,
    SpecContentInvalidError,
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
async def test_success_swagger_2_accepted(tmp_path: Path):
    """Swagger 2.0 specs (top-level 'swagger' key) are also valid."""
    url = KNOWN_SPEC_URLS["2.3.7.9"]
    body = b'{"swagger": "2.0", "paths": {}}'
    respx.get(url).mock(return_value=httpx.Response(200, content=body))

    async with httpx.AsyncClient() as c:
        result = await fetch_spec("2.3.7.9", tmp_path, client=c)

    assert result.exists()


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


@pytest.mark.asyncio
@respx.mock
async def test_wrong_shape_rate_limit_error_raises(tmp_path: Path):
    """200 OK + valid JSON but not an OpenAPI/Swagger doc → SpecContentInvalidError."""
    url = KNOWN_SPEC_URLS["2.3.7.9"]
    body = b'{"error": "rate-limited"}'
    respx.get(url).mock(return_value=httpx.Response(200, content=body))

    async with httpx.AsyncClient() as c:
        with pytest.raises(SpecContentInvalidError) as exc_info:
            await fetch_spec("2.3.7.9", tmp_path, client=c)

    msg = str(exc_info.value)
    assert url in msg
    assert "rate-limited" in msg
    assert "pubhub" in msg.lower()
    # No file left behind.
    assert not list(tmp_path.glob("*.json"))
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
@respx.mock
async def test_wrong_shape_missing_paths_raises(tmp_path: Path):
    """openapi key present but no paths → invalid."""
    url = KNOWN_SPEC_URLS["2.3.7.9"]
    body = b'{"openapi": "3.0.3"}'
    respx.get(url).mock(return_value=httpx.Response(200, content=body))

    async with httpx.AsyncClient() as c:
        with pytest.raises(SpecContentInvalidError):
            await fetch_spec("2.3.7.9", tmp_path, client=c)

    assert not list(tmp_path.glob("*.json"))
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
@respx.mock
async def test_wrong_shape_json_array_raises(tmp_path: Path):
    """Valid JSON but not even a dict → invalid."""
    url = KNOWN_SPEC_URLS["2.3.7.9"]
    body = b'["not", "a", "spec"]'
    respx.get(url).mock(return_value=httpx.Response(200, content=body))

    async with httpx.AsyncClient() as c:
        with pytest.raises(SpecContentInvalidError):
            await fetch_spec("2.3.7.9", tmp_path, client=c)

    assert not list(tmp_path.glob("*.json"))
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
@respx.mock
async def test_redirect_followed(tmp_path: Path):
    """Pubhub may redirect via CDN — fetcher must follow."""
    url = KNOWN_SPEC_URLS["2.3.7.9"]
    redirect_target = "https://cdn.example.com/spec.json"
    body = b'{"openapi": "3.0.3", "paths": {}}'
    respx.get(url).mock(return_value=httpx.Response(302, headers={"location": redirect_target}))
    respx.get(redirect_target).mock(return_value=httpx.Response(200, content=body))

    # Use module's own client so follow_redirects=True is exercised.
    result = await fetch_spec("2.3.7.9", tmp_path)
    assert result.exists()
    assert result.read_bytes() == body
