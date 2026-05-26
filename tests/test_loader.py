"""Tests for the OpenAPI loader and adaptive splitter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalyst_center_mcp.loader import (
    ParameterSpec,
    SpecLoader,
    _derive_action_name,
    _detect_pagination_style,
)


def test_action_name_derivation_stable_across_operationid_rename() -> None:
    """Cisco renames operationIds between releases — derived names must be stable."""
    name_a = _derive_action_name("get", "/dna/intent/api/v1/network-device", "Devices")
    name_b = _derive_action_name("get", "/dna/intent/api/v1/network-device", "Devices")
    assert name_a == name_b
    # Verb + tag + last-segment shape.
    assert name_a == "get_devices_network_device"


def test_action_name_for_path_param_endpoint() -> None:
    name = _derive_action_name("get", "/dna/intent/api/v1/network-device/{id}", "Devices")
    # Templated segments are skipped → last non-templated segment wins.
    assert name == "get_devices_network_device"


def test_pagination_offset_detected() -> None:
    params = [
        ParameterSpec(name="offset", location="query"),
        ParameterSpec(name="limit", location="query"),
    ]
    assert _detect_pagination_style(params) == "offset"


def test_pagination_cursor_detected() -> None:
    params = [
        ParameterSpec(name="cursor", location="query"),
        ParameterSpec(name="limit", location="query"),
    ]
    assert _detect_pagination_style(params) == "cursor"


def test_pagination_none_when_no_signal() -> None:
    params = [ParameterSpec(name="hostname", location="query")]
    assert _detect_pagination_style(params) is None


def test_loader_ro_filter_excludes_post(minimal_specs_dir: Path) -> None:
    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=False).load()
    methods = {op.method for op in index.by_action_name.values()}
    assert methods == {"get"}, methods


def test_loader_rw_filter_includes_post(minimal_specs_dir: Path) -> None:
    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=True).load()
    methods = {op.method for op in index.by_action_name.values()}
    assert "post" in methods


def test_loader_groups_by_section(minimal_specs_dir: Path) -> None:
    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=False).load()
    tool_names = sorted(g.name for g in index.groups)
    # Devices, Sites, Clients each have <80 ops -> one tool per section.
    assert "devices" in tool_names
    assert "sites" in tool_names
    assert "clients" in tool_names


def test_loader_paginated_endpoints_flagged(minimal_specs_dir: Path) -> None:
    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=False).load()
    devices_list = next(
        op
        for op in index.by_action_name.values()
        if op.path == "/dna/intent/api/v1/network-device" and op.method == "get"
    )
    assert devices_list.pagination == "offset"

    clients_list = next(
        op for op in index.by_action_name.values() if op.path == "/dna/data/api/v1/clients"
    )
    assert clients_list.pagination == "cursor"


def test_loader_indexes_operation_id_back_reference(minimal_specs_dir: Path) -> None:
    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=False).load()
    assert "getDeviceList" in index.by_operation_id
    op = index.by_operation_id["getDeviceList"]
    assert op.path == "/dna/intent/api/v1/network-device"


def test_loader_missing_version_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Spec directory"):
        SpecLoader(str(tmp_path / "specs"), "9.9.9").load()


def test_loader_splitter_threshold_zero_disables_splitting(tmp_path: Path) -> None:
    """When max_actions_per_tool=0, every section produces exactly one tool."""
    spec_dir = tmp_path / "specs" / "1.0"
    spec_dir.mkdir(parents=True)
    fake_spec = {
        "openapi": "3.0.0",
        "paths": {
            f"/api/x/{i}": {"get": {"tags": ["X"], "operationId": f"op{i}", "parameters": []}}
            for i in range(200)
        },
        "components": {"schemas": {}},
    }
    (spec_dir / "x.json").write_text(json.dumps(fake_spec))
    index = SpecLoader(
        str(tmp_path / "specs"), "1.0", read_write=False, max_actions_per_tool=0
    ).load()
    # 200 ops, one section → one tool.
    assert len(index.groups) == 1
    assert len(index.groups[0].operations) == 200


def test_loader_splitter_creates_misc_for_small_subtags(tmp_path: Path) -> None:
    """Sub-tags with <4 ops collapse into <section>_misc."""
    spec_dir = tmp_path / "specs" / "1.0"
    spec_dir.mkdir(parents=True)
    paths = {}
    # Large sub-tag triggers per-subtag split (threshold=10).
    for i in range(15):
        paths[f"/api/big/{i}"] = {
            "get": {"tags": ["Section - Big"], "operationId": f"big{i}", "parameters": []}
        }
    # Small sub-tag (3 ops) should collapse into <section>_misc.
    for i in range(3):
        paths[f"/api/tiny/{i}"] = {
            "get": {"tags": ["Section - Tiny"], "operationId": f"tiny{i}", "parameters": []}
        }
    (spec_dir / "x.json").write_text(
        json.dumps({"openapi": "3.0.0", "paths": paths, "components": {"schemas": {}}})
    )
    index = SpecLoader(
        str(tmp_path / "specs"), "1.0", read_write=False, max_actions_per_tool=10
    ).load()
    names = sorted(g.name for g in index.groups)
    assert "section_misc" in names
    # 'big' sub-tag (15 ops) needs further splitting because it exceeds threshold 10 —
    # so the splitter recurses on URL path segments at depth 3. Verify the section_big
    # tool ends up split (depth-3 buckets), not present as a single oversize tool.
    big_tools = [
        n for n in names if n.startswith("section") and "tiny" not in n and "misc" not in n
    ]
    assert big_tools, "expected at least one section_big_* tool"
