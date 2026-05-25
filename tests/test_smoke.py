"""Import smoke test.

Asserts every module in `catalyst_center_mcp` is importable. Catches
accidental syntax errors and missing-symbol bugs in the scaffold during
CI. Does NOT exercise behaviour — bodies are stubs that raise
NotImplementedError when invoked.
"""

from __future__ import annotations

import importlib

EXPECTED_MODULES = [
    "catalyst_center_mcp",
    "catalyst_center_mcp.auth",
    "catalyst_center_mcp.config",
    "catalyst_center_mcp.diff",
    "catalyst_center_mcp.dispatcher",
    "catalyst_center_mcp.fetcher",
    "catalyst_center_mcp.loader",
    "catalyst_center_mcp.pagination",
    "catalyst_center_mcp.server",
    "catalyst_center_mcp.tools",
    "catalyst_center_mcp.transport_auth",
]


def test_all_modules_importable() -> None:
    for name in EXPECTED_MODULES:
        importlib.import_module(name)


def test_version_present() -> None:
    import catalyst_center_mcp

    assert isinstance(catalyst_center_mcp.__version__, str)
    assert catalyst_center_mcp.__version__.count(".") >= 2
