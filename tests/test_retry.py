"""Retry-policy tests for the dispatcher.

Extracted from test_dispatcher.py in v0.3.0 to keep retry concerns isolated.
"""

from __future__ import annotations

import asyncio
import random
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
    auth._token = "pre-set-token"  # type: ignore[attr-defined]
    d = Dispatcher(
        base_url="https://cc.test:443",
        auth=auth,
        verify_ssl=False,
        timeout=5.0,
        pagination=PaginationConfig(),
        retry=retry,
    )
    d.set_index(index)
    return d


@pytest.fixture
def _instant_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


@pytest.fixture
def _recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture sleep durations without actually sleeping."""
    recorded: list[float] = []

    async def _record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _record)
    return recorded


@pytest.mark.asyncio
@respx.mock
async def test_retry_recovers_after_503(minimal_specs_dir: Path, _instant_sleep: None) -> None:
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
    result = await d.call("get_devices_count__network_device", {})
    await d.close()
    assert result == {"response": 1, "version": "1.0"}


@pytest.mark.asyncio
@respx.mock
async def test_retry_mutating_disabled_by_default(
    minimal_specs_dir: Path, _instant_sleep: None
) -> None:
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
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_jitter_bounded_half_to_full(
    minimal_specs_dir: Path, _recorded_sleeps: list[float]
) -> None:
    """The actual sleep falls in [base/2, base] for attempt 0 (uncapped)."""
    d = _make_dispatcher(
        minimal_specs_dir,
        retry=RetryConfig(
            max_attempts=4,
            statuses=(503,),
            backoff_base=1.0,
            backoff_cap=100.0,  # well above base * 2**3 = 8.0
        ),
    )
    # Drive 100 samples through the private helper with attempt=0.
    random.seed(0)
    for _ in range(100):
        await d._sleep_backoff(0)  # type: ignore[attr-defined]
    await d.close()
    assert len(_recorded_sleeps) == 100
    # base=1, attempt=0 → raw=1.0, half=0.5, delay ∈ [0.5, 1.0].
    assert all(0.5 <= s <= 1.0 for s in _recorded_sleeps)
    # Distribution check: we should see both halves of the band exercised.
    assert min(_recorded_sleeps) < 0.6
    assert max(_recorded_sleeps) > 0.9


@pytest.mark.asyncio
async def test_backoff_cap_actually_caps(
    minimal_specs_dir: Path, _recorded_sleeps: list[float]
) -> None:
    """No matter the attempt number, sleep never exceeds backoff_cap."""
    d = _make_dispatcher(
        minimal_specs_dir,
        retry=RetryConfig(
            max_attempts=10,
            statuses=(503,),
            backoff_base=1.0,
            backoff_cap=0.01,  # tiny cap
        ),
    )
    random.seed(42)
    for attempt in range(8):
        await d._sleep_backoff(attempt)  # type: ignore[attr-defined]
    await d.close()
    assert _recorded_sleeps  # at least one entry
    for s in _recorded_sleeps:
        assert s <= 0.01


@pytest.mark.asyncio
@respx.mock
async def test_network_exception_retried_on_get(
    minimal_specs_dir: Path, _instant_sleep: None
) -> None:
    route = respx.get("https://cc.test:443/dna/intent/api/v1/network-device/count").mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.Response(200, json={"response": 2, "version": "1.0"}),
        ]
    )
    d = _make_dispatcher(
        minimal_specs_dir,
        retry=RetryConfig(max_attempts=3, statuses=(503,), backoff_base=0.0),
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()
    assert result == {"response": 2, "version": "1.0"}
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_network_exception_not_retried_on_post_without_retry_mutating(
    minimal_specs_dir: Path, _instant_sleep: None
) -> None:
    route = respx.post("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        side_effect=httpx.ConnectError("boom"),
    )
    d = _make_dispatcher(
        minimal_specs_dir,
        read_write=True,
        retry=RetryConfig(max_attempts=3, statuses=(503,), retry_mutating=False),
    )
    result = await d.call("post_devices_network_device", {"hostname": "r1"})
    await d.close()
    assert isinstance(result, dict) and result.get("error") is True
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_network_exception_retried_on_post_with_retry_mutating(
    minimal_specs_dir: Path, _instant_sleep: None
) -> None:
    route = respx.post("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.Response(200, json={"response": {"taskId": "t1"}, "version": "1.0"}),
        ]
    )
    d = _make_dispatcher(
        minimal_specs_dir,
        read_write=True,
        retry=RetryConfig(max_attempts=3, statuses=(503,), retry_mutating=True),
    )
    result = await d.call("post_devices_network_device", {"hostname": "r1"})
    await d.close()
    assert result.get("response", {}).get("taskId") == "t1"
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_retry_exhaustion_returns_error_envelope(
    minimal_specs_dir: Path, _instant_sleep: None
) -> None:
    route = respx.get("https://cc.test:443/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(503, text="still busy"),
    )
    d = _make_dispatcher(
        minimal_specs_dir,
        retry=RetryConfig(max_attempts=3, statuses=(503,), backoff_base=0.0),
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()
    assert isinstance(result, dict)
    assert result.get("error") is True
    assert result.get("status_code") == 503
    assert route.call_count == 3  # max_attempts honoured
