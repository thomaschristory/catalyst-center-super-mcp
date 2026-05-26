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


@respx.mock
def test_fetch_all_known_continues_after_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When one version fails mid-loop, --all-known still attempts the rest."""
    versions = list(KNOWN_SPEC_URLS)
    assert len(versions) >= 2, "test assumes 2+ known versions"
    body = b'{"openapi":"3.0.0","paths":{},"info":{"title":"x","version":"1"}}'
    # First succeeds, second fails, any others succeed.
    respx.get(KNOWN_SPEC_URLS[versions[0]]).mock(return_value=httpx.Response(200, content=body))
    respx.get(KNOWN_SPEC_URLS[versions[1]]).mock(return_value=httpx.Response(503))
    for v in versions[2:]:
        respx.get(KNOWN_SPEC_URLS[v]).mock(return_value=httpx.Response(200, content=body))
    cfg = _minimal_config_yaml(tmp_path)
    rc = run_fetch(["--all-known", "--config", str(cfg)])
    assert rc == 1
    err = capsys.readouterr().err
    assert f"OK  {versions[0]}" in err
    assert f"FAIL {versions[1]}" in err
    # First version's spec landed on disk despite later failure.
    assert any((tmp_path / "specs" / versions[0]).glob("*.json"))


@respx.mock
def test_fetch_specs_dir_flag_overrides_config(tmp_path: Path) -> None:
    """The --specs-dir flag wins over config.catalyst_center_mcp.specs_dir."""
    config_specs = tmp_path / "from_config"
    flag_specs = tmp_path / "from_flag"
    cfg = tmp_path / "catalyst-center-mcp.yaml"
    cfg.write_text(
        f"catalyst_center:\n  host: localhost\n"
        f"catalyst_center_mcp:\n  specs_dir: {config_specs}\n"
    )
    v = "2.3.7.9"
    body = b'{"openapi":"3.0.0","paths":{},"info":{"title":"x","version":"1"}}'
    respx.get(KNOWN_SPEC_URLS[v]).mock(return_value=httpx.Response(200, content=body))
    rc = run_fetch([v, "--config", str(cfg), "--specs-dir", str(flag_specs)])
    assert rc == 0
    assert any((flag_specs / v).glob("*.json"))
    assert not config_specs.exists()


def test_fetch_explicit_config_typo_errors_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """If --config points at a missing file, exit non-zero with a clear message
    rather than silently falling back to defaults."""
    with pytest.raises(SystemExit) as exc:
        run_fetch(["2.3.7.9", "--config", str(tmp_path / "nope.yaml")])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "not found" in err
