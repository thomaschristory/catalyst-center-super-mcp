"""Tests for the dispatcher."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from catalyst_center_mcp.auth import CatalystCenterAuth
from catalyst_center_mcp.config import PaginationConfig, RetryConfig
from catalyst_center_mcp.dispatcher import Dispatcher
from catalyst_center_mcp.loader import SpecLoader


def _make_dispatcher(
    minimal_specs_dir: Path,
    *,
    read_write: bool = True,
    pagination: PaginationConfig | None = None,
    retry: RetryConfig | None = None,
) -> Dispatcher:
    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=read_write).load()
    auth = CatalystCenterAuth(
        host="cc.test",
        port=443,
        username="u",
        password="p",
        verify_ssl=False,
    )
    auth._token = "pre-set-token"  # type: ignore[attr-defined]  # bypass login in unit tests
    d = Dispatcher(
        base_url="https://cc.test:443",
        auth=auth,
        verify_ssl=False,
        timeout=5.0,
        pagination=pagination or PaginationConfig(),
        retry=retry,
    )
    d.set_index(index)
    return d


@pytest.fixture(autouse=True)
def _instant_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real backoff sleeps so retry tests run fast."""
    import asyncio

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


@pytest.mark.asyncio
@respx.mock
async def test_get_with_query_params(minimal_specs_dir: Path) -> None:
    route = respx.get("https://cc.test:443/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json={"response": 4, "version": "1.0"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call("get_devices_count", {})
    await d.close()
    assert result == {"response": 4, "version": "1.0"}
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_path_param_substituted(minimal_specs_dir: Path) -> None:
    respx.get("https://cc.test:443/dna/intent/api/v1/network-device/abc-123").mock(
        return_value=httpx.Response(200, json={"response": {"id": "abc-123"}, "version": "1.0"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call("get_devices_network_device_2", {"id": "abc-123"})
    await d.close()
    assert result["response"]["id"] == "abc-123"


@pytest.mark.asyncio
@respx.mock
async def test_missing_path_param_returns_error(minimal_specs_dir: Path) -> None:
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call("get_devices_network_device_2", {})
    await d.close()
    assert isinstance(result, dict)
    assert result.get("error") is True
    assert "id" in result["message"]


@pytest.mark.asyncio
@respx.mock
async def test_post_body_routing(minimal_specs_dir: Path) -> None:
    route = respx.post("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        return_value=httpx.Response(200, json={"response": {"taskId": "t1"}, "version": "1.0"})
    )
    d = _make_dispatcher(minimal_specs_dir, read_write=True)
    result = await d.call(
        "post_devices_network_device",
        {"hostname": "router-1", "ip": "10.0.0.1"},
    )
    await d.close()
    sent_body = route.calls[0].request.content
    assert b"router-1" in sent_body
    assert b"10.0.0.1" in sent_body
    assert result["response"]["taskId"] == "t1"


@pytest.mark.asyncio
@respx.mock
async def test_x_auth_token_header_sent(minimal_specs_dir: Path) -> None:
    route = respx.get("https://cc.test:443/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json={"response": 4, "version": "1.0"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    await d.call("get_devices_count", {})
    await d.close()
    assert route.calls[0].request.headers["X-Auth-Token"] == "pre-set-token"


@pytest.mark.asyncio
@respx.mock
async def test_401_triggers_reauth_and_retry(minimal_specs_dir: Path) -> None:
    """On 401, dispatcher re-runs login() and retries the call once."""
    respx.post("https://cc.test:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "refreshed", "message": ""})
    )
    count_route = respx.get("https://cc.test:443/dna/intent/api/v1/network-device/count").mock(
        side_effect=[
            httpx.Response(401, json={"error": "expired"}),
            httpx.Response(200, json={"response": 7, "version": "1.0"}),
        ]
    )
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call("get_devices_count", {})
    await d.close()
    assert result == {"response": 7, "version": "1.0"}
    assert count_route.call_count == 2
    # Second call must use the refreshed token.
    assert count_route.calls[1].request.headers["X-Auth-Token"] == "refreshed"


@pytest.mark.asyncio
@respx.mock
async def test_persistent_401_returns_error(minimal_specs_dir: Path) -> None:
    """If a second 401 follows re-auth, return an error envelope, don't infinite-loop."""
    respx.post("https://cc.test:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "fresh", "message": ""})
    )
    respx.get("https://cc.test:443/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(401, json={"error": "still expired"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call("get_devices_count", {})
    await d.close()
    assert isinstance(result, dict)
    assert result.get("error") is True
    assert result["status_code"] == 401


@pytest.mark.asyncio
@respx.mock
async def test_retry_recovers_after_503(minimal_specs_dir: Path) -> None:
    respx.get("https://cc.test:443/dna/intent/api/v1/network-device/count").mock(
        side_effect=[
            httpx.Response(503, text="busy"),
            httpx.Response(200, json={"response": 1, "version": "1.0"}),
        ]
    )
    d = _make_dispatcher(
        minimal_specs_dir,
        retry=RetryConfig(max_attempts=3, statuses=(503,), backoff_base=0.0),
    )
    result = await d.call("get_devices_count", {})
    await d.close()
    assert result == {"response": 1, "version": "1.0"}


@pytest.mark.asyncio
@respx.mock
async def test_retry_mutating_disabled_by_default(minimal_specs_dir: Path) -> None:
    route = respx.post("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        return_value=httpx.Response(503, text="busy")
    )
    d = _make_dispatcher(
        minimal_specs_dir,
        read_write=True,
        retry=RetryConfig(max_attempts=3, statuses=(503,), retry_mutating=False),
    )
    result = await d.call("post_devices_network_device", {"hostname": "r1"})
    await d.close()
    assert isinstance(result, dict) and result.get("error") is True
    # POST must not be retried.
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_reserved_params_stripped(minimal_specs_dir: Path) -> None:
    """`_max_pages`, `_page_size`, `_auto_follow` must not appear on the wire."""
    route = respx.get("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        return_value=httpx.Response(200, json={"response": [], "version": "1.0"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    await d.call(
        "get_devices_network_device",
        {"_max_pages": 2, "_page_size": 50, "_auto_follow": False, "hostname": "r1"},
    )
    await d.close()
    qs = dict(route.calls[0].request.url.params)
    assert "_max_pages" not in qs and "_page_size" not in qs and "_auto_follow" not in qs
    assert qs.get("hostname") == "r1"


@pytest.mark.asyncio
@respx.mock
async def test_auto_follow_off_short_circuits_pagination(minimal_specs_dir: Path) -> None:
    route = respx.get("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        return_value=httpx.Response(200, json={"response": list(range(50)), "version": "1.0"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    # Even though the server returns a full page (which would normally trigger
    # auto-follow), _auto_follow=False forces single-page mode.
    result = await d.call("get_devices_network_device", {"limit": 50, "_auto_follow": False})
    await d.close()
    assert route.call_count == 1
    # Single-page passthrough — no _paginated wrapping.
    assert "_paginated" not in result
    assert result["response"] == list(range(50))


@pytest.mark.asyncio
@respx.mock
async def test_auto_follow_stitches_paginated_endpoint(minimal_specs_dir: Path) -> None:
    respx.get("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        side_effect=[
            httpx.Response(200, json={"response": [1, 2, 3], "version": "1.0"}),
            httpx.Response(200, json={"response": [4], "version": "1.0"}),  # short -> stop
        ]
    )
    d = _make_dispatcher(minimal_specs_dir, pagination=PaginationConfig(enabled=True, max_pages=3))
    result = await d.call("get_devices_network_device", {"limit": 3})
    await d.close()
    assert result["response"] == [1, 2, 3, 4]
    assert result["_paginated"]["pages"] == 2
    assert result["_paginated"]["truncated"] is False


@pytest.mark.asyncio
async def test_unknown_action_returns_error(minimal_specs_dir: Path) -> None:
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call("nope_not_real", {})
    await d.close()
    assert isinstance(result, dict) and result.get("error") is True
