"""Shared pytest fixtures for the catalyst-center-mcp test suite."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

_FIXTURE_SPEC = (
    Path(__file__).parent / "fixtures" / "specs" / "2.3.7.9" / "catalyst-center-min.json"
)


@pytest.fixture
def minimal_specs_dir(tmp_path: Path) -> Path:
    """A specs/ directory containing a minimal Catalyst Center-shaped 2.3.7.9 spec."""
    dest = tmp_path / "specs" / "2.3.7.9"
    dest.mkdir(parents=True)
    shutil.copy(_FIXTURE_SPEC, dest / "catalyst-center-min.json")
    return tmp_path / "specs"


@pytest.fixture
def minimal_spec_dict() -> dict:
    """The raw fixture spec as a Python dict — for unit tests that don't need disk I/O."""
    return json.loads(_FIXTURE_SPEC.read_text())
