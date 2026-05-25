"""Shared pytest fixtures.

The `minimal_spec` fixture is a placeholder — it returns nothing until
`loader.py` has a real implementation. Tests that need it should skip
for now.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def minimal_spec() -> dict:
    pytest.skip("minimal_spec fixture not yet implemented — scaffold only")
