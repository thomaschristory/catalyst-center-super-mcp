"""Tests for the version diff utility."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalyst_center_mcp.diff import diff_versions, print_diff


def _write_spec(specs_root: Path, version: str, paths: dict) -> None:
    out = specs_root / version
    out.mkdir(parents=True)
    (out / "spec.json").write_text(
        json.dumps({"openapi": "3.0.0", "paths": paths, "components": {"schemas": {}}})
    )


def test_identical_specs_empty_diff(tmp_path: Path) -> None:
    paths = {
        "/dna/intent/api/v1/x": {"get": {"tags": ["X"], "operationId": "getX", "parameters": []}}
    }
    _write_spec(tmp_path / "specs", "a", paths)
    _write_spec(tmp_path / "specs", "b", paths)
    diff = diff_versions(str(tmp_path / "specs"), "a", "b", read_write=True)
    assert diff.added == [] and diff.removed == [] and diff.changed == []
    assert diff.old_version == "a" and diff.new_version == "b"


def test_added_op_in_b(tmp_path: Path) -> None:
    paths_a = {
        "/dna/intent/api/v1/x": {"get": {"tags": ["X"], "operationId": "getX", "parameters": []}}
    }
    paths_b = {
        **paths_a,
        "/dna/intent/api/v1/y": {"get": {"tags": ["Y"], "operationId": "getY", "parameters": []}},
    }
    _write_spec(tmp_path / "specs", "a", paths_a)
    _write_spec(tmp_path / "specs", "b", paths_b)
    diff = diff_versions(str(tmp_path / "specs"), "a", "b", read_write=True)
    assert any(op.operation_id == "getY" for op in diff.added)
    assert diff.removed == []


def test_removed_op_in_b(tmp_path: Path) -> None:
    paths_a = {
        "/dna/intent/api/v1/x": {"get": {"tags": ["X"], "operationId": "getX", "parameters": []}},
        "/dna/intent/api/v1/y": {"get": {"tags": ["Y"], "operationId": "getY", "parameters": []}},
    }
    paths_b = {
        "/dna/intent/api/v1/x": {"get": {"tags": ["X"], "operationId": "getX", "parameters": []}}
    }
    _write_spec(tmp_path / "specs", "a", paths_a)
    _write_spec(tmp_path / "specs", "b", paths_b)
    diff = diff_versions(str(tmp_path / "specs"), "a", "b", read_write=True)
    assert any(op.operation_id == "getY" for op in diff.removed)


def test_parameter_drift_flagged(tmp_path: Path) -> None:
    """Same operationId, different param list, must show up in `changed`."""
    paths_a = {
        "/dna/intent/api/v1/x": {
            "get": {
                "tags": ["X"],
                "operationId": "getX",
                "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer"}}],
            }
        }
    }
    paths_b = {
        "/dna/intent/api/v1/x": {
            "get": {
                "tags": ["X"],
                "operationId": "getX",
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                    {"name": "family", "in": "query", "schema": {"type": "string"}},
                ],
            }
        }
    }
    _write_spec(tmp_path / "specs", "a", paths_a)
    _write_spec(tmp_path / "specs", "b", paths_b)
    diff = diff_versions(str(tmp_path / "specs"), "a", "b", read_write=True)
    op_diff = next(c for c in diff.changed if c.operation_id == "getX")
    added_param_names = [p.name for p in op_diff.param_diffs if p.change == "added"]
    assert "family" in added_param_names


def test_print_diff_runs_without_crash(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    paths = {
        "/dna/intent/api/v1/x": {"get": {"tags": ["X"], "operationId": "getX", "parameters": []}}
    }
    _write_spec(tmp_path / "specs", "a", paths)
    _write_spec(tmp_path / "specs", "b", paths)
    diff = diff_versions(str(tmp_path / "specs"), "a", "b", read_write=True)
    print_diff(diff)
    captured = capsys.readouterr()
    assert "a" in captured.out and "b" in captured.out
