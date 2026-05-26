"""End-to-end smoke test with respx-mocked Catalyst Center.

Loads the minimal fixture spec, logs in (mocked), registers tools, and
invokes a paginated and an unpaginated action through the dispatcher.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import FastMCP

from catalyst_center_mcp.auth import CatalystCenterAuth
from catalyst_center_mcp.config import PaginationConfig
from catalyst_center_mcp.dispatcher import Dispatcher
from catalyst_center_mcp.loader import SpecLoader
from catalyst_center_mcp.tools import register_tools


@pytest.mark.asyncio
@respx.mock
async def test_end_to_end_against_mocked_sandbox(minimal_specs_dir: Path) -> None:
    respx.post("https://cc.test:443/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "live-token", "message": ""})
    )
    respx.get("https://cc.test:443/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json={"response": 7, "version": "1.0"})
    )
    respx.get("https://cc.test:443/dna/intent/api/v1/network-device").mock(
        side_effect=[
            httpx.Response(200, json={"response": [{"id": "d1"}, {"id": "d2"}], "version": "1.0"}),
            httpx.Response(
                200, json={"response": [{"id": "d3"}], "version": "1.0"}
            ),  # short → stop
        ]
    )

    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=False).load()
    auth = CatalystCenterAuth(
        host="cc.test", port=443, username="u", password="p", verify_ssl=False
    )
    dispatcher = Dispatcher(
        base_url="https://cc.test:443",
        auth=auth,
        verify_ssl=False,
        pagination=PaginationConfig(enabled=True, max_pages=3),
    )
    await dispatcher.connect()
    dispatcher.set_index(index)

    mcp = FastMCP("catalyst-center-mcp-smoke")
    n_tools = register_tools(mcp, index, dispatcher)
    assert n_tools >= 2  # at least Devices + Sites + Clients

    # Unpaginated call (count endpoint → action name "get_devices_count")
    count = await dispatcher.call("get_devices_count", {})
    assert isinstance(count, dict) and count["response"] == 7

    # Paginated call — auto-follow stitches two pages.
    devices = await dispatcher.call("get_devices_network_device", {"limit": 2})
    assert isinstance(devices, dict)
    assert devices["response"] == [{"id": "d1"}, {"id": "d2"}, {"id": "d3"}]
    assert devices["_paginated"]["pages"] == 2
    assert devices["_paginated"]["truncated"] is False

    await dispatcher.close()
