"""Tests for the `fetch` CLI subcommand."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from catalyst_center_mcp.cli.fetch import run_fetch
from catalyst_center_mcp.fetcher import KNOWN_SPEC_URLS


def _minimal_config_yaml(tmp_path: Path) -> Path:
    cfg = tmp_path / "catalyst-center-mcp.yaml"
    cfg.write_text(
        "catalyst_center:\n  host: localhost\n"
        f"catalyst_center_mcp:\n  specs_dir: {tmp_path / 'specs'}\n"
    )
    return cfg


def test_fetch_unknown_version_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _minimal_config_yaml(tmp_path)
    rc = run_fetch(["9.9.9-bogus", "--config", str(cfg)])
    assert rc != 0
    captured = capsys.readouterr()
    assert "No known download URL" in captured.err or "Unknown" in captured.err


@respx.mock
def test_fetch_known_version_writes_file(tmp_path: Path) -> None:
    version = "2.3.7.9"
    url = KNOWN_SPEC_URLS[version]
    body = b'{"openapi": "3.0.0", "paths": {}, "info": {"title": "x", "version": "1"}}'
    respx.get(url).mock(return_value=httpx.Response(200, content=body))
    cfg = _minimal_config_yaml(tmp_path)
    rc = run_fetch([version, "--config", str(cfg)])
    assert rc == 0
    # Spec lands under specs_dir/<version>/.
    files = list((tmp_path / "specs" / version).glob("*.json"))
    assert len(files) == 1


@respx.mock
def test_fetch_all_known_iterates(tmp_path: Path) -> None:
    body = b'{"openapi": "3.0.0", "paths": {}, "info": {"title": "x", "version": "1"}}'
    for url in KNOWN_SPEC_URLS.values():
        respx.get(url).mock(return_value=httpx.Response(200, content=body))
    cfg = _minimal_config_yaml(tmp_path)
    rc = run_fetch(["--all-known", "--config", str(cfg)])
    assert rc == 0
    for v in KNOWN_SPEC_URLS:
        assert any((tmp_path / "specs" / v).glob("*.json"))


def test_fetch_requires_version_or_all_known(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _minimal_config_yaml(tmp_path)
    with pytest.raises(SystemExit):
        run_fetch(["--config", str(cfg)])


def test_fetch_version_and_all_known_mutually_exclusive(
    tmp_path: Path,
) -> None:
    cfg = _minimal_config_yaml(tmp_path)
    with pytest.raises(SystemExit):
        run_fetch(["2.3.7.9", "--all-known", "--config", str(cfg)])
