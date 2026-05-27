"""Tests for the CLI entry point."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest


def test_default_args_are_stdio() -> None:
    from catalyst_center_mcp.server import parse_args

    args = parse_args([])
    assert args.transport is None  # falls back to config
    assert args.read_write is False


def test_read_write_flag() -> None:
    from catalyst_center_mcp.server import parse_args

    args = parse_args(["--read-write"])
    assert args.read_write is True


def test_transport_flag() -> None:
    from catalyst_center_mcp.server import parse_args

    args = parse_args(["--transport", "sse"])
    assert args.transport == "sse"


def test_invalid_transport_rejected() -> None:
    from catalyst_center_mcp.server import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--transport", "carrier-pigeon"])


def test_diff_subcommand_args_present() -> None:
    from catalyst_center_mcp.server import parse_args

    args = parse_args(["--diff", "2.3.7.9", "3.1.3"])
    assert args.diff == ["2.3.7.9", "3.1.3"]


def test_max_actions_per_tool_override() -> None:
    from catalyst_center_mcp.server import parse_args

    args = parse_args(["--max-actions-per-tool", "50"])
    assert args.max_actions_per_tool == 50


def test_version_override() -> None:
    from catalyst_center_mcp.server import parse_args

    args = parse_args(["--version", "3.1.3"])
    assert args.version == "3.1.3"


def test_config_flag() -> None:
    from catalyst_center_mcp.server import parse_args

    args = parse_args(["--config", "/tmp/cc.yaml"])
    assert args.config == "/tmp/cc.yaml"


def test_main_diff_exits_zero(tmp_path: Path) -> None:
    """`--diff a b` should print a report and exit 0 without starting the server."""
    from catalyst_center_mcp import server

    specs = tmp_path / "specs"
    for v in ("a", "b"):
        (specs / v).mkdir(parents=True)
        (specs / v / "s.json").write_text(
            json.dumps(
                {
                    "openapi": "3.0.0",
                    "paths": {
                        "/dna/x": {"get": {"tags": ["X"], "operationId": "getX", "parameters": []}}
                    },
                    "components": {"schemas": {}},
                }
            )
        )
    config = tmp_path / "config.yaml"
    config.write_text(
        "catalyst_center:\n  host: localhost\n"
        f"catalyst_center_mcp:\n  specs_dir: {specs}\n  active_version: a\n"
    )
    rc = server.main(["--config", str(config), "--diff", "a", "b"])
    assert rc == 0


def test_parse_args_default_config_is_none() -> None:
    """The argparse default for --config must be None so explicit detection works."""
    from catalyst_center_mcp.server import parse_args

    args = parse_args([])
    assert args.config is None


def test_main_legacy_fallback_warns_on_stderr_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    minimal_specs_dir: Path,
) -> None:
    """A bare main() invocation in a cwd with only config.yaml uses the legacy file
    and emits DEPRECATION to stderr, NOT stdout (stdio MCP JSON-RPC channel safety)."""
    from catalyst_center_mcp import server

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        f"catalyst_center:\n  host: localhost\n"
        f"catalyst_center_mcp:\n  specs_dir: {minimal_specs_dir}\n  active_version: '2.3.7.9'\n"
    )
    rc = server.main(["--diff", "2.3.7.9", "2.3.7.9"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "DEPRECATION" in captured.err
    assert "DEPRECATION" not in captured.out


def test_main_explicit_missing_config_does_not_use_legacy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    minimal_specs_dir: Path,
) -> None:
    """Passing --config to a missing path must NOT fall back to config.yaml, even
    if config.yaml is present in cwd."""
    from catalyst_center_mcp import server

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        f"catalyst_center:\n  host: localhost\n"
        f"catalyst_center_mcp:\n  specs_dir: {minimal_specs_dir}\n  active_version: '2.3.7.9'\n"
    )
    # Explicit but-missing --config: resolver must return it unchanged.
    # _load_config_or_default then falls back to AppConfig defaults whose
    # specs_dir is "./specs" (not present here), so run_diff may raise
    # FileNotFoundError. We only care that the legacy DEPRECATION shim
    # did NOT fire — that is the observable contract being tested.
    with contextlib.suppress(FileNotFoundError):
        server.main(["--config", str(tmp_path / "nope.yaml"), "--diff", "2.3.7.9", "2.3.7.9"])
    captured = capsys.readouterr()
    assert "DEPRECATION" not in captured.err
