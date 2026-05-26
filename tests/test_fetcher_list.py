"""Tests for fetcher.list_known_versions."""

from __future__ import annotations

from pathlib import Path

from catalyst_center_mcp.fetcher import (
    KNOWN_SPEC_URLS,
    VersionInfo,
    list_known_versions,
)


def test_list_known_versions_marks_uncached(tmp_path: Path) -> None:
    rows = list_known_versions(tmp_path)
    by_version = {r.version: r for r in rows}
    assert set(by_version) == set(KNOWN_SPEC_URLS)
    for r in by_version.values():
        assert isinstance(r, VersionInfo)
        assert r.cached is False
        assert r.extra is False


def test_list_known_versions_marks_cached(tmp_path: Path) -> None:
    v = next(iter(KNOWN_SPEC_URLS))  # any known version
    (tmp_path / v).mkdir()
    (tmp_path / v / "intent_api.json").write_text("{}")
    rows = list_known_versions(tmp_path)
    by_version = {r.version: r for r in rows}
    assert by_version[v].cached is True


def test_list_known_versions_includes_extra_dirs(tmp_path: Path) -> None:
    extra = "9.9.9-unknown"
    (tmp_path / extra).mkdir()
    (tmp_path / extra / "spec.json").write_text("{}")
    rows = list_known_versions(tmp_path)
    by_version = {r.version: r for r in rows}
    assert extra in by_version
    assert by_version[extra].extra is True
    assert by_version[extra].cached is True


def test_list_known_versions_skips_empty_dirs(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    rows = list_known_versions(tmp_path)
    assert "empty" not in {r.version for r in rows}
