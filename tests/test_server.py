"""Tests for the CLI entry point."""

from __future__ import annotations

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
