"""Cross-tool action-name disambiguation tests against the synthetic fixture."""

from __future__ import annotations

from catalyst_center_mcp.loader import SpecLoader


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
    count_names = [n for n in names if "_count" in n]
    assert all("__" in n for n in count_names if n.startswith("get_devices"))


def test_v01_unique_names_preserved():
    """Action names that were already unique in v0.1.0 must survive v0.2.0 unchanged."""
    import json
    from pathlib import Path

    snap = json.loads(Path("tests/fixtures/v0.1.0_action_names.json").read_text())
    snap_set = set(snap)
    new = set(SpecLoader("./specs", "2.3.7.9", read_write=False).load().by_action_name)

    # Any v0.1.0 name that had NO suffix variant in v0.1.0 was unique → must still exist.
    # A name X is "unique in v0.1.0" iff:
    #   1. X is in the snapshot
    #   2. no X_2, X_3, ... is in the snapshot (X wasn't the bare-name winner)
    #   3. X itself isn't a _N collision artifact (i.e. stripping a trailing _N
    #      doesn't yield another name already in the snapshot)
    import re

    _N_SUFFIX = re.compile(r"^(.*)_(\d+)$")

    def was_unique(name: str) -> bool:
        if name not in snap_set:
            return False
        if any(f"{name}_{i}" in snap_set for i in range(2, 50)):
            return False
        m = _N_SUFFIX.match(name)
        if m and m.group(1) in snap_set:
            # name is itself a _N variant of another snapshot entry → was a collision.
            return False
        return True

    unique_in_v01 = {n for n in snap_set if was_unique(n)}
    missing = unique_in_v01 - new
    assert not missing, f"{len(missing)} v0.1.0-unique names lost in v0.2.0: {sorted(missing)[:10]}"
