"""Tests for FastMCP tool registration."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import FastMCP

from catalyst_center_mcp.auth import CatalystCenterAuth
from catalyst_center_mcp.dispatcher import Dispatcher
from catalyst_center_mcp.loader import SpecLoader
from catalyst_center_mcp.tools import register_tools


def _make_setup(specs_dir: Path) -> tuple[FastMCP, Dispatcher]:
    index = SpecLoader(str(specs_dir), "2.3.7.9", read_write=False).load()
    auth = CatalystCenterAuth(host="cc.test", port=443, username="u", password="p")
    auth._token = "t"  # type: ignore[attr-defined]
    d = Dispatcher(base_url="https://cc.test:443", auth=auth, verify_ssl=False)
    d.set_index(index)
    mcp = FastMCP("catalyst-center-mcp-test")
    return mcp, d


@pytest.mark.asyncio
async def test_register_tools_count_matches_groups(minimal_specs_dir: Path) -> None:
    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=False).load()
    mcp, d = _make_setup(minimal_specs_dir)
    count = register_tools(mcp, index, d)
    assert count == len(index.groups)


@pytest.mark.asyncio
async def test_registered_tool_names_match_group_names(minimal_specs_dir: Path) -> None:
    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=False).load()
    mcp, d = _make_setup(minimal_specs_dir)
    register_tools(mcp, index, d)
    registered = {t.name for t in await mcp.list_tools()}
    for group in index.groups:
        assert group.name in registered, f"tool {group.name!r} not registered"


@pytest.mark.asyncio
async def test_tool_description_lists_actions(minimal_specs_dir: Path) -> None:
    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=False).load()
    mcp, d = _make_setup(minimal_specs_dir)
    register_tools(mcp, index, d)
    devices_tool = await mcp.get_tool("devices")
    assert devices_tool is not None
    desc = devices_tool.description or ""
    # An action name from the fixture spec must appear in the description.
    assert "get_devices_network_device" in desc
    assert "Pagination" in desc  # _PAGINATION_HINT present


@pytest.mark.asyncio
async def test_unknown_action_returns_error_envelope(
    minimal_specs_dir: Path,
) -> None:
    """Tool handler should reject unknown actions before reaching the dispatcher."""
    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=False).load()
    mcp, d = _make_setup(minimal_specs_dir)
    register_tools(mcp, index, d)
    devices = await mcp.get_tool("devices")
    assert devices is not None
    # Invoke the underlying function directly. Result is the handler's return value.
    result = await devices.fn(action="nope_not_real", params=None)
    assert isinstance(result, dict)
    assert result.get("error") is True
    assert "nope_not_real" in result["message"]
