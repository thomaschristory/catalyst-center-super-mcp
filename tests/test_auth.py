"""Tests for Catalyst Center authentication."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from catalyst_center_mcp.auth import AuthError, CatalystCenterAuth


def _make_auth(**overrides: object) -> CatalystCenterAuth:
    defaults: dict[str, object] = {
        "host": "cc.example.com",
        "port": 443,
        "username": "devnetuser",
        "password": "Cisco123!",
        "verify_ssl": False,
    }
    defaults.update(overrides)
    return CatalystCenterAuth(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
@respx.mock
async def test_login_captures_token() -> None:
    respx.post("https://cc.example.com:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "abc.def.ghi", "message": ""})
    )
    auth = _make_auth()
    async with httpx.AsyncClient(verify=False) as client:
        await auth.login(client)
    assert auth.header() == {"X-Auth-Token": "abc.def.ghi"}


@pytest.mark.asyncio
@respx.mock
async def test_login_ignores_message_field() -> None:
    respx.post("https://cc.example.com:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "t1", "message": "stuff", "extra": 1})
    )
    auth = _make_auth()
    async with httpx.AsyncClient(verify=False) as client:
        await auth.login(client)
    assert auth.header()["X-Auth-Token"] == "t1"


@pytest.mark.asyncio
@respx.mock
async def test_login_sends_basic_auth_header() -> None:
    """The token endpoint expects HTTP Basic — verify the Authorization header on the request."""
    route = respx.post("https://cc.example.com:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "t", "message": ""})
    )
    auth = _make_auth(username="user", password="pass")
    async with httpx.AsyncClient(verify=False) as client:
        await auth.login(client)
    sent = route.calls[0].request
    expected = "Basic " + base64.b64encode(b"user:pass").decode()
    assert sent.headers["Authorization"] == expected


@pytest.mark.asyncio
@respx.mock
async def test_login_401_raises_autherror() -> None:
    respx.post("https://cc.example.com:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )
    auth = _make_auth()
    async with httpx.AsyncClient(verify=False) as client:
        with pytest.raises(AuthError, match="401"):
            await auth.login(client)


@pytest.mark.asyncio
@respx.mock
async def test_login_500_raises_autherror() -> None:
    respx.post("https://cc.example.com:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(500, text="boom")
    )
    auth = _make_auth()
    async with httpx.AsyncClient(verify=False) as client:
        with pytest.raises(AuthError, match="500"):
            await auth.login(client)


@pytest.mark.asyncio
@respx.mock
async def test_login_missing_token_field_raises() -> None:
    respx.post("https://cc.example.com:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"message": "where's the token?"})
    )
    auth = _make_auth()
    async with httpx.AsyncClient(verify=False) as client:
        with pytest.raises(AuthError, match="Token"):
            await auth.login(client)


@pytest.mark.asyncio
async def test_header_before_login_raises() -> None:
    auth = _make_auth()
    with pytest.raises(AuthError, match="login"):
        auth.header()


@pytest.mark.asyncio
async def test_missing_credentials_raise_on_login() -> None:
    auth = _make_auth(username="", password="")
    async with httpx.AsyncClient(verify=False) as client:
        with pytest.raises(AuthError, match="credentials"):
            await auth.login(client)


@pytest.mark.asyncio
@respx.mock
async def test_relogin_replaces_token() -> None:
    respx.post("https://cc.example.com:443/dna/system/api/v1/auth/token").mock(
        side_effect=[
            httpx.Response(200, json={"Token": "first", "message": ""}),
            httpx.Response(200, json={"Token": "second", "message": ""}),
        ]
    )
    auth = _make_auth()
    async with httpx.AsyncClient(verify=False) as client:
        await auth.login(client)
        assert auth.header()["X-Auth-Token"] == "first"
        await auth.login(client)
        assert auth.header()["X-Auth-Token"] == "second"
