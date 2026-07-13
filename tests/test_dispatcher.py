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
async def test_get_with_query_params(minimal_specs_dir: Path, httpx2_mock: respx.Router) -> None:
    route = httpx2_mock.get("https://cc.test:443/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json={"response": 4, "version": "1.0"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call("get_devices_count__network_device", {})
    await d.close()
    assert result == {"response": 4, "version": "1.0"}
    assert route.called


@pytest.mark.asyncio
async def test_path_param_substituted(minimal_specs_dir: Path, httpx2_mock: respx.Router) -> None:
    httpx2_mock.get("https://cc.test:443/dna/intent/api/v1/network-device/abc-123").mock(
        return_value=httpx.Response(200, json={"response": {"id": "abc-123"}, "version": "1.0"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call(
        "get_devices_network_device__dna_intent_api_v1_network_device__2", {"id": "abc-123"}
    )
    await d.close()
    assert result["response"]["id"] == "abc-123"


@pytest.mark.asyncio
async def test_path_param_normal_values_unchanged(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """A UUID or dotted IP path param must reach the wire unescaped (#28)."""
    for value in ("abc-123-DEF_456.7~8", "10.0.0.1"):
        route = httpx2_mock.get(
            f"https://cc.test:443/dna/intent/api/v1/network-device/{value}"
        ).mock(return_value=httpx.Response(200, json={"response": {"id": value}}))
        d = _make_dispatcher(minimal_specs_dir)
        await d.call(
            "get_devices_network_device__dna_intent_api_v1_network_device__2",
            {"id": value},
        )
        await d.close()
        # quote(safe='') leaves alphanumerics and -._~ untouched, so the path
        # segment is byte-identical to the supplied value.
        assert route.called
        assert route.calls[0].request.url.raw_path.decode().endswith(f"/network-device/{value}")


@pytest.mark.asyncio
async def test_path_param_injection_is_percent_encoded(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """A path param with '/', '..', '?', '#' must be percent-encoded so it
    cannot escape its URL segment (path-injection hardening, #28)."""
    malicious = "../../admin/secret?x=1#frag/"
    # The whole value lands percent-encoded inside the {id} segment. The route
    # below is the ONLY URL respx will answer; if the value escaped the segment
    # (e.g. resolved '..' or split on '?'), this request would not match and the
    # call would fail instead of returning 200.
    route = httpx2_mock.get(
        "https://cc.test:443/dna/intent/api/v1/network-device/"
        "..%2F..%2Fadmin%2Fsecret%3Fx%3D1%23frag%2F"
    ).mock(return_value=httpx.Response(200, json={"response": {}}))
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call(
        "get_devices_network_device__dna_intent_api_v1_network_device__2",
        {"id": malicious},
    )
    await d.close()
    assert route.called
    assert not (isinstance(result, dict) and result.get("error"))
    sent = route.calls[0].request.url.raw_path.decode()
    # No structural metacharacters survive raw in the outgoing path: '?' and '#'
    # were percent-encoded, and every '/' inside the value became '%2F' so the
    # value stays inside its single segment (no traversal, no query/fragment).
    assert "?" not in sent
    assert "#" not in sent
    assert "%2F" in sent  # the slashes were encoded
    assert sent.endswith("..%2F..%2Fadmin%2Fsecret%3Fx%3D1%23frag%2F")


@pytest.mark.asyncio
async def test_missing_path_param_returns_error(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call("get_devices_network_device__dna_intent_api_v1_network_device__2", {})
    await d.close()
    assert isinstance(result, dict)
    assert result.get("error") is True
    assert "id" in result["message"]


@pytest.mark.asyncio
async def test_post_body_routing(minimal_specs_dir: Path, httpx2_mock: respx.Router) -> None:
    route = httpx2_mock.post("https://cc.test:443/dna/intent/api/v1/network-device").mock(
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
async def test_x_auth_token_header_sent(minimal_specs_dir: Path, httpx2_mock: respx.Router) -> None:
    route = httpx2_mock.get("https://cc.test:443/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json={"response": 4, "version": "1.0"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    await d.call("get_devices_count__network_device", {})
    await d.close()
    assert route.calls[0].request.headers["X-Auth-Token"] == "pre-set-token"


@pytest.mark.asyncio
async def test_401_triggers_reauth_and_retry(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """On 401, dispatcher re-runs login() and retries the call once."""
    httpx2_mock.post("https://cc.test:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "refreshed", "message": ""})
    )
    count_route = httpx2_mock.get(
        "https://cc.test:443/dna/intent/api/v1/network-device/count"
    ).mock(
        side_effect=[
            httpx.Response(401, json={"error": "expired"}),
            httpx.Response(200, json={"response": 7, "version": "1.0"}),
        ]
    )
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call("get_devices_count__network_device", {})
    await d.close()
    assert result == {"response": 7, "version": "1.0"}
    assert count_route.call_count == 2
    # Second call must use the refreshed token.
    assert count_route.calls[1].request.headers["X-Auth-Token"] == "refreshed"


@pytest.mark.asyncio
async def test_persistent_401_returns_error(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """If a second 401 follows re-auth, return an error envelope, don't infinite-loop."""
    httpx2_mock.post("https://cc.test:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "fresh", "message": ""})
    )
    httpx2_mock.get("https://cc.test:443/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(401, json={"error": "still expired"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    result = await d.call("get_devices_count__network_device", {})
    await d.close()
    assert isinstance(result, dict)
    assert result.get("error") is True
    assert result["status_code"] == 401


@pytest.mark.asyncio
async def test_reserved_params_stripped(minimal_specs_dir: Path, httpx2_mock: respx.Router) -> None:
    """`_max_pages`, `_page_size`, `_auto_follow` must not appear on the wire."""
    route = httpx2_mock.get("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        return_value=httpx.Response(200, json={"response": [], "version": "1.0"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    await d.call(
        "get_devices_network_device__dna_intent_api_v1_network_device",
        {"_max_pages": 2, "_page_size": 50, "_auto_follow": False, "hostname": "r1"},
    )
    await d.close()
    qs = dict(route.calls[0].request.url.params)
    assert "_max_pages" not in qs and "_page_size" not in qs and "_auto_follow" not in qs
    assert qs.get("hostname") == "r1"


@pytest.mark.asyncio
async def test_auto_follow_off_short_circuits_pagination(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    route = httpx2_mock.get("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        return_value=httpx.Response(200, json={"response": list(range(50)), "version": "1.0"})
    )
    d = _make_dispatcher(minimal_specs_dir)
    # Even though the server returns a full page (which would normally trigger
    # auto-follow), _auto_follow=False forces single-page mode.
    result = await d.call(
        "get_devices_network_device__dna_intent_api_v1_network_device",
        {"limit": 50, "_auto_follow": False},
    )
    await d.close()
    assert route.call_count == 1
    # Single-page passthrough — no _paginated wrapping.
    assert "_paginated" not in result
    assert result["response"] == list(range(50))


@pytest.mark.asyncio
async def test_auto_follow_stitches_paginated_endpoint(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    httpx2_mock.get("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        side_effect=[
            httpx.Response(200, json={"response": [1, 2, 3], "version": "1.0"}),
            httpx.Response(200, json={"response": [4], "version": "1.0"}),  # short -> stop
        ]
    )
    d = _make_dispatcher(minimal_specs_dir, pagination=PaginationConfig(enabled=True, max_pages=3))
    result = await d.call(
        "get_devices_network_device__dna_intent_api_v1_network_device", {"limit": 3}
    )
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


# ---------------------------------------------------------------------------
# POST body: top-level convention + defensive `body`-wrapper unwrap (#32)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_unwraps_lone_body_wrapper(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """A caller that nested the whole payload under a lone `body` key (the shape
    the old `body: object` schema implied) must not double-wrap: the dispatcher
    unwraps it so the API sees the fields at the top level (#32)."""
    route = httpx2_mock.post("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    d = _make_dispatcher(minimal_specs_dir)
    await d.call("post_devices_network_device", {"body": {"name": "edge-1"}})
    await d.close()

    body = route.calls.last.request.content.decode()
    assert '"name"' in body and "edge-1" in body
    # The literal `body` wrapper must NOT reach the API.
    assert '"body"' not in body


@pytest.mark.asyncio
async def test_dispatcher_keeps_body_field_alongside_others(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """Only a *lone* `body` key is unwrapped. A genuine field named `body` next to
    other fields is forwarded verbatim — we don't guess it's a wrapper."""
    route = httpx2_mock.post("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    d = _make_dispatcher(minimal_specs_dir)
    await d.call("post_devices_network_device", {"body": "literal", "name": "edge-1"})
    await d.close()

    body = route.calls.last.request.content.decode()
    assert '"body"' in body and "literal" in body
    assert "edge-1" in body


@pytest.mark.asyncio
async def test_dispatcher_unwraps_lone_body_wrapper_non_dict(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """The lone-`body` unwrap covers non-dict payloads too (e.g. an array body
    nested under `body`) — otherwise the double-wrap persists (#32)."""
    import json as _json

    route = httpx2_mock.post("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    d = _make_dispatcher(minimal_specs_dir)
    await d.call("post_devices_network_device", {"body": [{"x": 1}, {"x": 2}]})
    await d.close()

    sent = _json.loads(route.calls.last.request.content.decode())
    assert sent == [{"x": 1}, {"x": 2}]  # array forwarded, not {"body": [...]}
