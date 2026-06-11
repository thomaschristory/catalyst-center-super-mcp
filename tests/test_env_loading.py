"""Tests for `.env` discovery (#26).

python-dotenv's bare ``load_dotenv()`` searches upward from the *module's*
directory (site-packages once installed), so a project-dir ``.env`` is never
found. ``_load_env`` searches the cwd and next to ``--config`` instead.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from catalyst_center_mcp.server import _load_env


def test_load_env_finds_cwd_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CATALYST_CENTER_USERNAME", raising=False)
    (tmp_path / ".env").write_text("CATALYST_CENTER_USERNAME=fileuser\n")
    monkeypatch.chdir(tmp_path)
    _load_env(None)
    assert os.environ["CATALYST_CENTER_USERNAME"] == "fileuser"


def test_exported_var_wins_over_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An exported shell variable must take precedence over the .env (override=False)."""
    monkeypatch.setenv("CATALYST_CENTER_USERNAME", "exported")
    (tmp_path / ".env").write_text("CATALYST_CENTER_USERNAME=fileuser\n")
    monkeypatch.chdir(tmp_path)
    _load_env(None)
    assert os.environ["CATALYST_CENTER_USERNAME"] == "exported"


def test_load_env_finds_dotenv_next_to_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A .env beside an out-of-tree --config file is discovered."""
    monkeypatch.delenv("CATALYST_CENTER_PASSWORD", raising=False)
    cfg_dir = tmp_path / "elsewhere"
    cfg_dir.mkdir()
    (cfg_dir / ".env").write_text("CATALYST_CENTER_PASSWORD=besideconfig\n")
    # Run from an unrelated empty dir so the cwd search doesn't find this .env.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.chdir(run_dir)
    _load_env(str(cfg_dir / "catalyst-center-mcp.yaml"))
    assert os.environ["CATALYST_CENTER_PASSWORD"] == "besideconfig"
