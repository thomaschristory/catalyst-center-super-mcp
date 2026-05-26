"""Proactive JWT refresh in the dispatcher + reactive 401 fallback regression."""

from __future__ import annotations

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
