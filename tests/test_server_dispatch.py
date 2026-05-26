"""Verify server.main() dispatches subcommands without launching the MCP server."""

from __future__ import annotations

import pytest

from catalyst_center_mcp import server


def test_main_dispatches_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, list[str]] = {}

    def _fake_run_fetch(argv: list[str]) -> int:
        called["argv"] = argv
        return 0

    monkeypatch.setattr("catalyst_center_mcp.cli.fetch.run_fetch", _fake_run_fetch)
    rc = server.main(["fetch", "--all-known"])
    assert rc == 0
    assert called["argv"] == ["--all-known"]


def test_main_dispatches_list_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, list[str]] = {}

    def _fake(argv: list[str]) -> int:
        called["argv"] = argv
        return 0

    monkeypatch.setattr("catalyst_center_mcp.cli.list_versions.run_list_versions", _fake)
    rc = server.main(["list-versions"])
    assert rc == 0
    assert called["argv"] == []


def test_main_passes_subcommand_args(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, list[str]] = {}

    def _fake(argv: list[str]) -> int:
        called["argv"] = argv
        return 0

    monkeypatch.setattr("catalyst_center_mcp.cli.fetch.run_fetch", _fake)
    rc = server.main(["fetch", "2.3.7.9", "--specs-dir", "/tmp/x"])
    assert rc == 0
    assert called["argv"] == ["2.3.7.9", "--specs-dir", "/tmp/x"]


def test_main_does_not_dispatch_diff_to_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--diff` must hit run_diff, NOT a subcommand."""
    monkeypatch.setattr(
        "catalyst_center_mcp.cli.fetch.run_fetch",
        lambda _argv: (_ for _ in ()).throw(AssertionError("must not dispatch fetch")),
    )
    monkeypatch.setattr(
        "catalyst_center_mcp.cli.list_versions.run_list_versions",
        lambda _argv: (_ for _ in ()).throw(AssertionError("must not dispatch list-versions")),
    )
    monkeypatch.setattr(
        "catalyst_center_mcp.server.run_diff",
        lambda _specs, _old, _new: 0,
    )
    rc = server.main(["--diff", "2.3.7.9", "3.1.3"])
    assert rc == 0
