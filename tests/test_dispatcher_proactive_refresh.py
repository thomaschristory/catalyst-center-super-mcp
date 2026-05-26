"""Proactive JWT refresh in the dispatcher + reactive 401 fallback regression."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
import respx

from catalyst_center_mcp.auth import CatalystCenterAuth
from catalyst_center_mcp.dispatcher import Dispatcher
from catalyst_center_mcp.loader import OperationSpec, SpecIndex, ToolGroup


def _make_dispatcher(auth: CatalystCenterAuth) -> Dispatcher:
    op = OperationSpec(
        operation_id="getCount",
        action_name="get_count",
        summary="",
        method="get",
        path="/dna/intent/api/v1/network-device/count",
        tag="Devices",
    )
    group = ToolGroup(name="devices", display_tag="Devices", operations=[op])
    index = SpecIndex(
        by_action_name={"get_count": op},
        by_operation_id={"getCount": op},
        groups=[group],
    )
    d = Dispatcher(base_url="https://example.com", auth=auth, verify_ssl=False)
    d.set_index(index)
    return d


@pytest.mark.asyncio
@respx.mock
async def test_proactive_refresh_fires_when_needs_refresh_true():
    auth = CatalystCenterAuth(
        host="example.com", port=443, username="u", password="p", verify_ssl=False
    )
    auth._token = "stale"  # type: ignore[attr-defined]
    auth._expires_at = time.time() + 30  # within margin → proactive refresh

    # Mock the login endpoint and the data endpoint.
    login_route = respx.post("https://example.com:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "fresh", "message": ""})
    )
    data_route = respx.get("https://example.com/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json={"response": 42, "version": "1.0"})
    )

    d = _make_dispatcher(auth)
    result = await d.call("get_count", {})

    assert login_route.called, "expected proactive /auth/token call before GET"
    assert data_route.called
    assert result == {"response": 42, "version": "1.0"}

    # F7: the GET must have used the post-refresh token, not the stale one.
    get_request = data_route.calls.last.request
    assert get_request.headers["X-Auth-Token"] == "fresh", (
        "GET must use the refreshed token, not the pre-refresh 'stale' one"
    )
    # And login must have fired before the GET (order).
    assert login_route.calls.last.request.url.path.endswith("/auth/token")
    await d.close()


@pytest.mark.asyncio
@respx.mock
async def test_no_proactive_refresh_when_token_fresh():
    auth = CatalystCenterAuth(
        host="example.com", port=443, username="u", password="p", verify_ssl=False
    )
    auth._token = "fresh"  # type: ignore[attr-defined]
    auth._expires_at = time.time() + 3600  # far from expiry

    login_route = respx.post("https://example.com:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "newer", "message": ""})
    )
    respx.get("https://example.com/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json={"response": 1, "version": "1.0"})
    )

    d = _make_dispatcher(auth)
    await d.call("get_count", {})
    assert not login_route.called, "should not re-login when token is fresh"
    await d.close()


@pytest.mark.asyncio
@respx.mock
async def test_reactive_401_still_works_when_not_proactively_refreshing():
    """Regression: existing 401 → re-auth → retry path must keep working."""
    auth = CatalystCenterAuth(
        host="example.com", port=443, username="u", password="p", verify_ssl=False
    )
    auth._token = "fresh"  # type: ignore[attr-defined]
    auth._expires_at = time.time() + 3600  # no proactive refresh

    login_route = respx.post("https://example.com:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "rotated", "message": ""})
    )
    # First GET 401, second GET 200.
    data_route = respx.get("https://example.com/dna/intent/api/v1/network-device/count").mock(
        side_effect=[
            httpx.Response(401, json={"message": "Bad token"}),
            httpx.Response(200, json={"response": 7, "version": "1.0"}),
        ]
    )

    d = _make_dispatcher(auth)
    result = await d.call("get_count", {})

    assert login_route.called
    assert data_route.call_count == 2
    assert result == {"response": 7, "version": "1.0"}
    await d.close()


# --- F4: lock must serialise concurrent proactive refreshes ---


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_calls_serialise_refresh():
    """Three concurrent calls with stale token → only ONE re-login, not three."""
    auth = CatalystCenterAuth(
        host="example.com", port=443, username="u", password="p", verify_ssl=False
    )
    auth._token = "stale"  # type: ignore[attr-defined]
    auth._expires_at = time.time() + 30  # within margin

    login_call_count = 0

    async def slow_login(request: httpx.Request) -> httpx.Response:
        nonlocal login_call_count
        login_call_count += 1
        await asyncio.sleep(0.1)  # simulate a slow auth round-trip
        return httpx.Response(200, json={"Token": "fresh", "message": ""})

    login_route = respx.post("https://example.com:443/dna/system/api/v1/auth/token").mock(
        side_effect=slow_login
    )
    data_route = respx.get("https://example.com/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json={"response": 42, "version": "1.0"})
    )

    d = _make_dispatcher(auth)
    results = await asyncio.gather(
        d.call("get_count", {}),
        d.call("get_count", {}),
        d.call("get_count", {}),
    )

    assert login_route.call_count == 1, (
        f"lock should serialise refresh: expected 1 login, got {login_route.call_count}"
    )
    assert login_call_count == 1
    assert data_route.call_count == 3
    for r in results:
        assert r == {"response": 42, "version": "1.0"}
    await d.close()


# --- F5: token-identity-snapshot prevents duplicate reactive re-login ---


@pytest.mark.asyncio
@respx.mock
async def test_two_concurrent_401s_only_relogin_once():
    """Two concurrent calls both hit 401 → snapshot pattern means only one re-login.

    Without the `if self._auth._token == stale_token` check, both tasks would
    re-login serially under the lock, doubling the auth load.
    """
    auth = CatalystCenterAuth(
        host="example.com", port=443, username="u", password="p", verify_ssl=False
    )
    auth._token = "fresh"  # type: ignore[attr-defined]
    auth._expires_at = time.time() + 3600  # no proactive refresh

    # Async handlers with explicit yields force interleaved execution under
    # asyncio.gather — otherwise respx resolves fast paths synchronously and
    # the second task never gets a chance to send its initial 401 GET.
    async def slow_login(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"Token": "rotated", "message": ""})

    login_route = respx.post("https://example.com:443/dna/system/api/v1/auth/token").mock(
        side_effect=slow_login
    )

    # 401 for the stale token, 200 for the rotated token.
    async def get_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)
        if request.headers.get("X-Auth-Token") == "fresh":
            return httpx.Response(401, json={"message": "Bad token"})
        return httpx.Response(200, json={"response": 99, "version": "1.0"})

    data_route = respx.get("https://example.com/dna/intent/api/v1/network-device/count").mock(
        side_effect=get_handler
    )

    d = _make_dispatcher(auth)
    results = await asyncio.gather(
        d.call("get_count", {}),
        d.call("get_count", {}),
    )

    assert login_route.call_count == 1, (
        f"token-identity snapshot should dedupe re-login: expected 1, got {login_route.call_count}"
    )
    # 2 initial 401s (with `fresh`) + 2 retries (with `rotated`) = 4 GETs
    assert data_route.call_count == 4
    for r in results:
        assert r == {"response": 99, "version": "1.0"}
    await d.close()


# --- F6: persistent 401 returns error envelope (not the internal sentinel) ---


@pytest.mark.asyncio
@respx.mock
async def test_persistent_401_returns_error_envelope():
    """If 401 persists after re-auth, surface an error envelope — not `_token_expired`."""
    auth = CatalystCenterAuth(
        host="example.com", port=443, username="u", password="p", verify_ssl=False
    )
    auth._token = "fresh"  # type: ignore[attr-defined]
    auth._expires_at = time.time() + 3600

    respx.post("https://example.com:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "still-bad", "message": ""})
    )
    # Every GET returns 401, even after re-auth.
    respx.get("https://example.com/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(401, json={"message": "Bad token"})
    )

    d = _make_dispatcher(auth)
    result = await d.call("get_count", {})

    assert isinstance(result, dict)
    assert result.get("error") is True
    assert result.get("status_code") == 401
    assert "re-authentication" in result.get("message", "").lower()
    # Internal sentinel must NOT leak to the caller.
    assert "_token_expired" not in result
    await d.close()
