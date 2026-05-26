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
