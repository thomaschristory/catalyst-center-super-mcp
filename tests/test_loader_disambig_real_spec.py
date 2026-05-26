"""Cross-tool disambiguation against the bundled real 2.3.7.9 spec."""

from __future__ import annotations

import pytest

from catalyst_center_mcp.loader import SpecLoader


@pytest.fixture(scope="module")
def real_index():
    return SpecLoader("./specs", "2.3.7.9", read_write=False).load()


def test_no_bare_get_devices_count(real_index):
    """The bare `get_devices_count` (which resolved to rogue-threats in v0.1.0) must be gone."""
    assert "get_devices_count" not in real_index.by_action_name


def test_network_device_count_reachable_under_disambiguated_name(real_index):
    """The actual device-count endpoint is reachable under a path-disambiguated name."""
    target_path = "/dna/intent/api/v1/network-device/count"
    matching = [n for n, op in real_index.by_action_name.items() if op.path == target_path]
    assert len(matching) == 1, f"expected 1 action for {target_path}, got {matching}"
    assert matching[0].startswith("get_devices_count__"), matching[0]


def test_all_nine_devices_count_ops_reachable(real_index):
    """All 9 colliding count endpoints under the Devices tag are individually reachable."""
    count_actions = {
        n: op
        for n, op in real_index.by_action_name.items()
        if n.startswith("get_devices_count__") and op.path.endswith("/count")
    }
    paths = {op.path for op in count_actions.values()}
    expected = {
        "/dna/intent/api/v1/security/threats/rogue/allowed-list/count",
        "/dna/intent/api/v1/interface/count",
        "/dna/intent/api/v1/healthScoreDefinitions/count",
        "/dna/intent/api/v1/interface/network-device/{deviceId}/count",
        "/dna/intent/api/v1/networkDeviceMaintenanceSchedules/count",
        "/dna/intent/api/v1/network-device/count",
        "/dna/intent/api/v1/network-device/config/count",
        "/dna/intent/api/v1/network-device/module/count",
        "/dna/intent/api/v1/networkDevices/count",
    }
    assert expected.issubset(paths), expected - paths
