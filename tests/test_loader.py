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
    _parse_request_body,
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
    """Demonstrates two collapse points:
    - sub-tag with <4 ops collapses into <section>_misc at the section level
    - path-split discriminators with >=4 ops survive as <section>_<subtag>_<disc> tools
    """
    spec_dir = tmp_path / "specs" / "1.0"
    spec_dir.mkdir(parents=True)
    paths: dict[str, dict] = {}

    # 'Big' sub-tag: 15 ops across 3 depth-3 buckets (5 each) — exceeds threshold 10
    # so the splitter recurses to path depth 3 and emits one tool per discriminator.
    for discriminator in ("cats", "dogs", "birds"):
        for i in range(5):
            paths[f"/api/big/{discriminator}/{i}"] = {
                "get": {
                    "tags": ["Section - Big"],
                    "operationId": f"big_{discriminator}_{i}",
                    "parameters": [],
                }
            }

    # 'Tiny' sub-tag: 3 ops < MISC_BUCKET_THRESHOLD (4) — collapses to <section>_misc.
    for i in range(3):
        paths[f"/api/tiny/{i}"] = {
            "get": {
                "tags": ["Section - Tiny"],
                "operationId": f"tiny{i}",
                "parameters": [],
            }
        }

    (spec_dir / "x.json").write_text(
        json.dumps({"openapi": "3.0.0", "paths": paths, "components": {"schemas": {}}})
    )
    index = SpecLoader(
        str(tmp_path / "specs"), "1.0", read_write=False, max_actions_per_tool=10
    ).load()
    names = sorted(g.name for g in index.groups)

    # Small sub-tag should collapse to <section>_misc.
    assert "section_misc" in names, names

    # Big sub-tag should have been path-split into per-discriminator tools.
    big_tools = sorted(n for n in names if n.startswith("section_big_") and not n.endswith("_misc"))
    assert big_tools == ["section_big_birds", "section_big_cats", "section_big_dogs"], big_tools


# ---------------------------------------------------------------------------
# Request-body field extraction (#32)
# ---------------------------------------------------------------------------


def test_parse_request_body_resolves_ref_to_top_level_fields() -> None:
    """A $ref'd body schema is resolved so its top-level fields and required
    flags surface for the tool description."""
    schemas = {
        "DevicePayload": {
            "type": "object",
            "required": ["ipAddress"],
            "properties": {
                "ipAddress": {"type": "string", "description": "Mgmt IP"},
                "snmpVersion": {"type": "string"},
                "extra": {"$ref": "#/components/schemas/Other"},
            },
        }
    }
    operation = {
        "requestBody": {
            "description": "Device payload",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/DevicePayload"}}
            },
        }
    }
    has_body, desc, fields = _parse_request_body(operation, schemas)
    assert has_body is True
    assert desc == "Device payload"
    by_name = {f.name: f for f in fields}
    assert set(by_name) == {"ipAddress", "snmpVersion", "extra"}
    assert by_name["ipAddress"].required is True
    assert by_name["snmpVersion"].required is False
    assert by_name["snmpVersion"].type == "string"
    assert by_name["extra"].type == "object"  # $ref-valued prop renders as object
    assert by_name["ipAddress"].description == "Mgmt IP"


def test_parse_request_body_bare_object_yields_no_fields() -> None:
    """Some Catalyst Center bodies are bare {"type": "object"} in the spec — we
    must not invent fields, so the list stays empty but has_body is still True."""
    operation = {"requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}}}
    has_body, _desc, fields = _parse_request_body(operation, {})
    assert has_body is True
    assert fields == []


def test_parse_request_body_absent() -> None:
    has_body, desc, fields = _parse_request_body({}, {})
    assert has_body is False
    assert desc == ""
    assert fields == []


def test_parse_request_body_unresolvable_ref_degrades_to_empty() -> None:
    """A $ref with no matching component yields no fields rather than raising."""
    operation = {
        "requestBody": {
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Missing"}}}
        }
    }
    has_body, _desc, fields = _parse_request_body(operation, {})
    assert has_body is True
    assert fields == []


def test_parse_request_body_merges_allof_and_nested_ref() -> None:
    """Composed bodies are allOf:[{$ref Base}, {properties: real fields}].
    Both the $ref'd base and the inline member must contribute fields."""
    schemas = {
        "Base": {"type": "object", "properties": {"id": {"type": "string"}}},
        "Composed": {
            "allOf": [
                {"$ref": "#/components/schemas/Base"},
                {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "count": {"type": "integer"},
                    },
                },
            ]
        },
    }
    operation = {
        "requestBody": {
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Composed"}}}
        }
    }
    _has, _desc, fields = _parse_request_body(operation, schemas)
    by_name = {f.name: f for f in fields}
    assert set(by_name) == {"id", "name", "count"}
    assert by_name["name"].required is True
    assert by_name["id"].required is False


def test_parse_request_body_cycle_guarded() -> None:
    """A $ref that points back to an ancestor must not infinite-loop."""
    schemas = {
        "Loop": {
            "type": "object",
            "properties": {"self": {"$ref": "#/components/schemas/Loop"}, "x": {"type": "string"}},
            "allOf": [{"$ref": "#/components/schemas/Loop"}],
        }
    }
    operation = {
        "requestBody": {
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Loop"}}}
        }
    }
    _has, _desc, fields = _parse_request_body(operation, schemas)
    # Terminates; top-level fields collected once.
    assert {f.name for f in fields} == {"self", "x"}


def test_parse_request_body_falls_back_to_star_star_media() -> None:
    """Some bodies are declared only under */* — still extract fields."""
    operation = {
        "requestBody": {
            "content": {
                "*/*": {"schema": {"type": "object", "properties": {"x": {"type": "string"}}}}
            }
        }
    }
    _has, _desc, fields = _parse_request_body(operation, {})
    assert [f.name for f in fields] == ["x"]


@pytest.mark.parametrize(
    "operation",
    [
        {"requestBody": None},
        {"requestBody": "nonsense"},
        {"requestBody": {"content": "nonsense"}},
        {"requestBody": {"content": {"application/json": {"schema": "nonsense"}}}},
        {
            "requestBody": {
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Missing"}}
                }
            }
        },
    ],
)
def test_parse_request_body_degrades_on_malformed_spec(operation: dict) -> None:
    """A malformed requestBody must degrade to has_body=True, no fields — never
    raise (which would abort the whole loader at startup) (#32)."""
    has_body, _desc, fields = _parse_request_body(operation, {})
    assert has_body is True
    assert fields == []


def test_resolve_ref_truthy_non_dict_target_degrades() -> None:
    """A component stored as a truthy non-dict must not crash field extraction."""
    operation = {
        "requestBody": {
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/X"}}}
        }
    }
    has_body, _desc, fields = _parse_request_body(operation, {"X": "notadict"})
    assert has_body is True
    assert fields == []


def test_loader_populates_body_fields_end_to_end(tmp_path: Path) -> None:
    """body_fields flow through SpecLoader onto the OperationSpec for a real op."""
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/dna/intent/api/v1/thing": {
                "post": {
                    "tags": ["Things"],
                    "summary": "Create a thing",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name"],
                                    "properties": {
                                        "name": {"type": "string"},
                                        "size": {"type": "integer"},
                                    },
                                }
                            }
                        }
                    },
                }
            }
        },
        "components": {"schemas": {}},
    }
    version_dir = tmp_path / "specs" / "9.9.9"
    version_dir.mkdir(parents=True)
    (version_dir / "spec.json").write_text(json.dumps(spec))
    idx = SpecLoader(str(tmp_path / "specs"), "9.9.9", read_write=True).load()
    op = next(iter(idx.by_action_name.values()))
    assert op.has_body is True
    by_name = {f.name: f for f in op.body_fields}
    assert set(by_name) == {"name", "size"}
    assert by_name["name"].required is True


def test_parse_request_body_deep_inline_allof_does_not_recurse_crash() -> None:
    """A deep but cycle-free inline allOf ladder (no $ref, so seen_refs never
    engages) must not raise RecursionError — which is a RuntimeError the loader
    does not catch and would abort the whole startup (#32)."""
    schema: dict = {"type": "object", "properties": {"leaf": {"type": "string"}}}
    for _ in range(5000):
        schema = {"allOf": [schema]}
    operation = {"requestBody": {"content": {"application/json": {"schema": schema}}}}
    # Must terminate cleanly. The deeply-buried `leaf` is beyond the depth cap,
    # so the field list is empty — but has_body stays True and nothing raises.
    has_body, _desc, fields = _parse_request_body(operation, {})
    assert has_body is True
    assert fields == []


def test_parse_request_body_deep_distinct_ref_chain_does_not_recurse_crash() -> None:
    """A deep chain of *distinct* $refs (allOf:[{$ref: next}] ladder) is cycle-free,
    so the seen_refs guard never trips. The depth bound must still stop it before
    RecursionError aborts the loader (#32)."""
    schemas: dict = {}
    for i in range(800):
        schemas[f"Lvl{i}"] = {"allOf": [{"$ref": f"#/components/schemas/Lvl{i + 1}"}]}
    schemas["Lvl800"] = {"type": "object", "properties": {"leaf": {"type": "string"}}}
    operation = {
        "requestBody": {
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Lvl0"}}}
        }
    }
    has_body, _desc, fields = _parse_request_body(operation, schemas)
    assert has_body is True
    assert fields == []


def test_parse_request_body_shallow_chain_below_cap_still_resolves() -> None:
    """A chain shorter than the depth cap still resolves fully — the bound only
    trims pathologically deep schemas, not normal composed bodies (#32)."""
    schemas = {
        "A": {"allOf": [{"$ref": "#/components/schemas/B"}]},
        "B": {"allOf": [{"$ref": "#/components/schemas/C"}]},
        "C": {"type": "object", "properties": {"leaf": {"type": "string"}}},
    }
    operation = {
        "requestBody": {
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/A"}}}
        }
    }
    _has, _desc, fields = _parse_request_body(operation, schemas)
    assert [f.name for f in fields] == ["leaf"]
