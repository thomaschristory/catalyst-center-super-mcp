"""Server startup wiring: fetch_spec is called iff auto_fetch && version dir empty."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from catalyst_center_mcp.fetcher import (
    SpecContentInvalidError,
    SpecVersionUnknownError,
)


@pytest.mark.asyncio
async def test_fetch_skipped_when_version_dir_has_json(tmp_path: Path):
    """Real-world default: specs already present → no fetch."""
    from catalyst_center_mcp import server

    version_dir = tmp_path / "2.3.7.9"
    version_dir.mkdir()
    (version_dir / "spec.json").write_text("{}")

    with patch.object(server, "fetch_spec", new=AsyncMock()) as mock_fetch:
        await server._maybe_auto_fetch(
            auto_fetch=True,
            specs_dir=tmp_path,
            version="2.3.7.9",
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
        )
        mock_fetch.assert_awaited_once()
        args, kwargs = mock_fetch.call_args
        assert args[0] == "2.3.7.9"
        assert args[1] == tmp_path / "2.3.7.9"
        # verify_ssl no longer part of fetch_spec API.
        assert "verify_ssl" not in kwargs


@pytest.mark.asyncio
async def test_fetch_skipped_when_auto_fetch_disabled(tmp_path: Path, capsys):
    from catalyst_center_mcp import server

    with patch.object(server, "fetch_spec", new=AsyncMock()) as mock_fetch:
        await server._maybe_auto_fetch(
            auto_fetch=False,
            specs_dir=tmp_path,
            version="2.3.7.9",
        )
        mock_fetch.assert_not_called()
    # F7: warning emitted because version dir is missing/empty.
    captured = capsys.readouterr()
    assert "auto_fetch is disabled" in captured.err
    assert "2.3.7.9" in captured.err


@pytest.mark.asyncio
async def test_fetch_skipped_when_auto_fetch_disabled_but_specs_present(tmp_path: Path, capsys):
    """No warning when auto_fetch is off but specs are already in place."""
    from catalyst_center_mcp import server

    version_dir = tmp_path / "2.3.7.9"
    version_dir.mkdir()
    (version_dir / "spec.json").write_text("{}")

    with patch.object(server, "fetch_spec", new=AsyncMock()) as mock_fetch:
        await server._maybe_auto_fetch(
            auto_fetch=False,
            specs_dir=tmp_path,
            version="2.3.7.9",
        )
        mock_fetch.assert_not_called()
    captured = capsys.readouterr()
    assert "auto_fetch is disabled" not in captured.err


@pytest.mark.asyncio
async def test_unknown_version_wrapped_at_startup(tmp_path: Path):
    """F6: SpecVersionUnknownError surfaces as a clean RuntimeError, not a stack trace."""
    from catalyst_center_mcp import server

    boom = SpecVersionUnknownError("unknown version foo")
    with (
        patch.object(server, "fetch_spec", new=AsyncMock(side_effect=boom)),
        pytest.raises(RuntimeError) as exc_info,
    ):
        await server._maybe_auto_fetch(
            auto_fetch=True,
            specs_dir=tmp_path,
            version="2.3.7.9",
        )
    msg = str(exc_info.value)
    assert "[startup] auto-fetch failed" in msg
    assert "2.3.7.9" in msg
    assert "auto_fetch: false" in msg
    # Original exception chained.
    assert exc_info.value.__cause__ is boom


@pytest.mark.asyncio
async def test_invalid_content_wrapped_at_startup(tmp_path: Path):
    """F6: SpecContentInvalidError also gets clean wrapping."""
    from catalyst_center_mcp import server

    boom = SpecContentInvalidError("body was rate-limit JSON")
    with (
        patch.object(server, "fetch_spec", new=AsyncMock(side_effect=boom)),
        pytest.raises(RuntimeError) as exc_info,
    ):
        await server._maybe_auto_fetch(
            auto_fetch=True,
            specs_dir=tmp_path,
            version="2.3.7.9",
        )
    assert "[startup] auto-fetch failed" in str(exc_info.value)
    assert exc_info.value.__cause__ is boom


@pytest.mark.asyncio
async def test_network_error_wrapped_at_startup(tmp_path: Path):
    """F6: httpx errors also wrapped."""
    from catalyst_center_mcp import server

    boom = httpx.ConnectError("connection refused")
    with (
        patch.object(server, "fetch_spec", new=AsyncMock(side_effect=boom)),
        pytest.raises(RuntimeError) as exc_info,
    ):
        await server._maybe_auto_fetch(
            auto_fetch=True,
            specs_dir=tmp_path,
            version="2.3.7.9",
        )
    assert "[startup] auto-fetch failed" in str(exc_info.value)
    assert exc_info.value.__cause__ is boom


@pytest.mark.asyncio
async def test_skip_glob_matches_stray_json_file(tmp_path: Path):
    """F8: a 0-byte stray .json makes auto_fetch silently skip.

    Documents the known behaviour. The user-facing fix is F6 — SpecLoader
    will fail and that failure gets wrapped at startup with an actionable
    message.
    """
    from catalyst_center_mcp import server

    version_dir = tmp_path / "2.3.7.9"
    version_dir.mkdir()
    (version_dir / "stray.json").write_bytes(b"")  # 0 bytes, not even valid JSON

    with patch.object(server, "fetch_spec", new=AsyncMock()) as mock_fetch:
        await server._maybe_auto_fetch(
            auto_fetch=True,
            specs_dir=tmp_path,
            version="2.3.7.9",
        )
        mock_fetch.assert_not_called()
