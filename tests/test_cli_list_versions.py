"""Tests for the `list-versions` CLI subcommand."""

from __future__ import annotations

from pathlib import Path

import pytest

from catalyst_center_mcp.cli.list_versions import run_list_versions
from catalyst_center_mcp.fetcher import KNOWN_SPEC_URLS


def _config_yaml(tmp_path: Path) -> Path:
    cfg = tmp_path / "catalyst-center-mcp.yaml"
    cfg.write_text(
        "catalyst_center:\n  host: localhost\n"
        f"catalyst_center_mcp:\n  specs_dir: {tmp_path / 'specs'}\n"
    )
    return cfg


def test_list_versions_prints_two_sections(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _config_yaml(tmp_path)
    rc = run_list_versions(["--config", str(cfg)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Known versions" in out
    assert "on disk" in out.lower()
    for v in KNOWN_SPEC_URLS:
        assert v in out


def test_list_versions_marks_cached(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v = next(iter(KNOWN_SPEC_URLS))
    specs = tmp_path / "specs"
    (specs / v).mkdir(parents=True)
    (specs / v / "intent.json").write_text("{}")
    cfg = _config_yaml(tmp_path)
    rc = run_list_versions(["--config", str(cfg)])
    assert rc == 0
    out = capsys.readouterr().out
    # The version line for v should mention "cached".
    cached_line = next(
        line for line in out.splitlines() if v in line and "cached" in line
    )
    assert cached_line  # truthy


def test_list_versions_lists_extra_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    specs = tmp_path / "specs"
    (specs / "9.9.9-custom").mkdir(parents=True)
    (specs / "9.9.9-custom" / "x.json").write_text("{}")
    cfg = _config_yaml(tmp_path)
    rc = run_list_versions(["--config", str(cfg)])
    out = capsys.readouterr().out
    assert "9.9.9-custom" in out
    assert rc == 0


def test_list_versions_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Block any outgoing HTTP — list-versions must be offline.
    import httpx

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("list-versions must not make HTTP calls")

    monkeypatch.setattr(httpx, "get", _boom)
    monkeypatch.setattr(httpx.Client, "request", _boom)
    cfg = _config_yaml(tmp_path)
    rc = run_list_versions(["--config", str(cfg)])
    assert rc == 0
