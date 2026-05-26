"""Server startup wiring: fetch_spec is called iff auto_fetch && version dir empty."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_fetch_skipped_when_version_dir_has_json(tmp_path: Path):
    """Real-world default: specs already present → no fetch."""
    from catalyst_center_mcp import server  # noqa: WPS433 (local import for patching)

    version_dir = tmp_path / "2.3.7.9"
    version_dir.mkdir()
    (version_dir / "spec.json").write_text("{}")

    with patch.object(server, "fetch_spec", new=AsyncMock()) as mock_fetch:
        await server._maybe_auto_fetch(
            auto_fetch=True,
            specs_dir=tmp_path,
            version="2.3.7.9",
            verify_ssl=True,
        )
        mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_fires_when_version_dir_empty(tmp_path: Path):
    from catalyst_center_mcp import server

    with patch.object(server, "fetch_spec", new=AsyncMock()) as mock_fetch:
        await server._maybe_auto_fetch(
            auto_fetch=True,
            specs_dir=tmp_path,
            version="2.3.7.9",
            verify_ssl=False,
        )
        mock_fetch.assert_awaited_once()
        args, kwargs = mock_fetch.call_args
        assert args[0] == "2.3.7.9"
        assert args[1] == tmp_path / "2.3.7.9"
        assert kwargs.get("verify_ssl") is False


@pytest.mark.asyncio
async def test_fetch_skipped_when_auto_fetch_disabled(tmp_path: Path):
    from catalyst_center_mcp import server

    with patch.object(server, "fetch_spec", new=AsyncMock()) as mock_fetch:
        await server._maybe_auto_fetch(
            auto_fetch=False,
            specs_dir=tmp_path,
            version="2.3.7.9",
            verify_ssl=True,
        )
        mock_fetch.assert_not_called()
