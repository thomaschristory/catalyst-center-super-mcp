"""Cross-tool action-name disambiguation tests against the synthetic fixture."""

from __future__ import annotations

from catalyst_center_mcp.loader import (
    OperationSpec,
    SpecLoader,
    ToolGroup,
    _disambiguate_cross_tool,
)


def _mk_op(method: str, path: str, tag: str, action_name: str) -> OperationSpec:
    """Build a minimal OperationSpec for disambig unit tests."""
    return OperationSpec(
        operation_id=f"{method}_{path}",
        action_name=action_name,
        summary="",
        method=method,
        path=path,
        tag=tag,
    )


def test_two_way_collision_disambiguates(minimal_specs_dir):
    """Both colliding /Devices/count ops must rename — no bare 'get_devices_count'."""
    index = SpecLoader(str(minimal_specs_dir), "2.3.7.9", read_write=False).load()
    names = set(index.by_action_name)

    # Both paths must be reachable under disambiguated names.
    paths_by_name = {n: op.path for n, op in index.by_action_name.items()}
    assert "/dna/intent/api/v1/network-device/count" in paths_by_name.values()
    assert "/dna/intent/api/v1/security/rogues/count" in paths_by_name.values()

    # The bare colliding name must NOT survive — no winner-takes-all.
    assert "get_devices_count" not in names

    # Both should have __ in their action_name (the discriminator separator).
    count_names = [n for n in names if n.startswith("get_devices") and "_count" in n]
    assert count_names, "expected get_devices_count* actions"
    assert len(count_names) >= 2, (
        f"expected >= 2 disambiguated get_devices_count* actions, got {count_names}"
    )
    assert all("__" in n for n in count_names)


def test_v01_unique_names_preserved():
    """Action names that were already unique in v0.1.0 must survive v0.2.0 AND
    still point at the same (method, path) endpoint.

    The snapshot is a list of ``[name, method, path]`` triples generated from
    v0.1.0 main. A surviving name that silently rerouted to a different op
    would be just as bad as a missing one — both must be caught.
    """
    import json
    import re
    from pathlib import Path

    snap_raw = json.loads(Path("tests/fixtures/v0.1.0_action_names.json").read_text())
    # snap_raw: list[list[str, str, str]]  -> dict[name, (method, path)]
    snap_map: dict[str, tuple[str, str]] = {n: (m, p) for n, m, p in snap_raw}
    snap_set = set(snap_map)

    new_index = SpecLoader("./specs", "2.3.7.9", read_write=False).load().by_action_name
    new_map = {n: (op.method, op.path) for n, op in new_index.items()}

    # A name X is "unique in v0.1.0" iff:
    #   1. X is in the snapshot
    #   2. no X_2, X_3, ... is in the snapshot (X wasn't the bare-name winner)
    #   3. X itself isn't a _N collision artifact (stripping a trailing _N
    #      doesn't yield another name already in the snapshot)
    _N_SUFFIX = re.compile(r"^(.*)_(\d+)$")

    def was_unique(name: str) -> bool:
        if name not in snap_set:
            return False
        if any(f"{name}_{i}" in snap_set for i in range(2, 50)):
            return False
        m = _N_SUFFIX.match(name)
        return not (m and m.group(1) in snap_set)

    unique_in_v01 = {n for n in snap_set if was_unique(n)}
    missing = unique_in_v01 - set(new_map)
    assert not missing, f"{len(missing)} v0.1.0-unique names lost in v0.2.0: {sorted(missing)[:10]}"

    # Stronger check: surviving unique names must still map to the same op.
    rerouted = {n: (snap_map[n], new_map[n]) for n in unique_in_v01 if snap_map[n] != new_map[n]}
    assert not rerouted, (
        f"{len(rerouted)} v0.1.0-unique names silently rerouted to a different op: "
        f"{dict(list(rerouted.items())[:5])}"
    )


def test_pass2_cross_api_family_collision():
    """Pass 2 (strip_api_prefix=False) must fire when two ops share an
    otherwise-identical path tail across different API families
    (intent vs. data). Both ops must remain reachable under distinct names
    that bake the family into the discriminator.
    """
    op_intent = _mk_op("get", "/dna/intent/api/v1/foo/count", "Devices", "get_devices_count")
    op_data = _mk_op("get", "/dna/data/api/v1/foo/count", "Devices", "get_devices_count")
    group = ToolGroup(name="devices", display_tag="Devices", operations=[op_intent, op_data])

    _disambiguate_cross_tool([group])

    names = {op.action_name for op in group.operations}
    assert len(names) == 2, f"expected 2 distinct names, got {names}"
    # Both names must carry the family discriminator from pass 2.
    paths_by_name = {op.action_name: op.path for op in group.operations}
    intent_name = next(n for n, p in paths_by_name.items() if p == op_intent.path)
    data_name = next(n for n, p in paths_by_name.items() if p == op_data.path)
    assert "intent" in intent_name, intent_name
    assert "data" in data_name, data_name
    # Pure bare name must be gone — no winner-takes-all.
    assert "get_devices_count" not in names


def test_numeric_tiebreaker_for_identical_discriminators():
    """Force a residual collision after both passes — pure-templated paths in
    the same API family produce identical pass-1 ("root") and pass-2
    ("dna_intent_api_v1") discriminators. The numeric ``__N`` tiebreaker must
    fire deterministically, ordered by (method, path).
    """
    op_a = _mk_op("get", "/dna/intent/api/v1/{a}/{b}", "Devices", "get_devices_root")
    op_c = _mk_op("get", "/dna/intent/api/v1/{c}/{d}", "Devices", "get_devices_root")
    # Pass them to disambig in reversed (method, path) order to prove the
    # internal sort — not iteration order — controls __N assignment.
    group = ToolGroup(name="devices", display_tag="Devices", operations=[op_c, op_a])

    _disambiguate_cross_tool([group])

    names = {op.action_name for op in group.operations}
    assert len(names) == 2, f"expected 2 distinct names, got {names}"
    # One name must carry the __2 numeric tiebreaker.
    numeric = [n for n in names if n.endswith("__2")]
    assert len(numeric) == 1, f"expected exactly one __2 tiebreaker, got {names}"

    # Stable ordering: sorted by (method, path), so the {a}/{b} op (lex < {c}/{d})
    # gets the bare candidate (no __2) and {c}/{d} gets __2.
    by_path = {op.path: op.action_name for op in group.operations}
    assert by_path["/dna/intent/api/v1/{a}/{b}"].endswith("dna_intent_api_v1"), by_path
    assert by_path["/dna/intent/api/v1/{c}/{d}"].endswith("__2"), by_path
