"""Tests for the YAML config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from catalyst_center_mcp.config import (  # noqa: F401  (verify all public symbols are exported)
    DEFAULT_CONFIG_PATH,
    AppConfig,
    CatalystCenterConfig,
    CatalystCenterMcpConfig,
    PaginationConfig,
    RetryConfig,
    TransportAuthConfig,
    TransportConfig,
    load_config,
    resolve_config_path,
)

VALID_YAML = """\
catalyst_center:
  host: ${CC_HOST}
  port: 443
  verify_ssl: false
  username: ${CC_USER}
  password: ${CC_PASS}
  timeout: 15.0
  retries:
    max_attempts: 5
    statuses: [502, 504]
    backoff_base: 0.25
    backoff_cap: 4.0
    retry_mutating: true

catalyst_center_mcp:
  specs_dir: ./specs
  active_version: "2.3.7.9"
  max_actions_per_tool: 80
  auto_fetch: false
  pagination:
    enabled: true
    max_pages: 3
    page_size: 50

transport:
  mode: sse
  host: 0.0.0.0
  port: 9000
  auth:
    type: bearer
    token: ${TOKEN}
"""


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CC_HOST", "cc.example.com")
    monkeypatch.setenv("CC_USER", "devnetuser")
    monkeypatch.setenv("CC_PASS", "Cisco123!")
    monkeypatch.setenv("TOKEN", "super-secret-token-32chars-min!!")
    path = tmp_path / "config.yaml"
    path.write_text(VALID_YAML)
    return path


def test_load_full_config(config_file: Path) -> None:
    cfg = load_config(str(config_file))
    assert isinstance(cfg, AppConfig)
    assert cfg.catalyst_center.host == "cc.example.com"
    assert cfg.catalyst_center.port == 443
    assert cfg.catalyst_center.username == "devnetuser"
    assert cfg.catalyst_center.password == "Cisco123!"
    assert cfg.catalyst_center.timeout == 15.0
    assert cfg.catalyst_center.base_url == "https://cc.example.com:443"
    assert cfg.catalyst_center.retries.max_attempts == 5
    assert cfg.catalyst_center.retries.statuses == (502, 504)
    assert cfg.catalyst_center.retries.retry_mutating is True
    assert cfg.catalyst_center_mcp.active_version == "2.3.7.9"
    assert cfg.catalyst_center_mcp.max_actions_per_tool == 80
    assert cfg.catalyst_center_mcp.auto_fetch is False
    assert cfg.catalyst_center_mcp.pagination.max_pages == 3
    assert cfg.catalyst_center_mcp.pagination.page_size == 50
    assert cfg.transport.mode == "sse"
    assert cfg.transport.host == "0.0.0.0"
    assert cfg.transport.port == 9000
    assert cfg.transport.auth.type == "bearer"
    assert cfg.transport.auth.token == "super-secret-token-32chars-min!!"


def test_defaults_applied_for_minimal_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("catalyst_center:\n  host: localhost\n")
    cfg = load_config(str(path))
    assert cfg.catalyst_center.port == 443
    assert cfg.catalyst_center.verify_ssl is True  # CC is HTTPS-only; verify by default
    assert cfg.catalyst_center.timeout == 30.0
    assert cfg.catalyst_center_mcp.active_version == "2.3.7.9"
    assert cfg.catalyst_center_mcp.max_actions_per_tool == 80
    assert cfg.catalyst_center_mcp.pagination.max_pages == 5
    assert cfg.transport.mode == "stdio"
    assert cfg.transport.auth.type == "none"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.yaml"))


def test_missing_env_var_substitutes_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
    path = tmp_path / "config.yaml"
    path.write_text("catalyst_center:\n  host: localhost\n  username: ${DOES_NOT_EXIST}\n")
    cfg = load_config(str(path))
    assert cfg.catalyst_center.username == ""
    captured = capsys.readouterr()
    assert "DOES_NOT_EXIST" in captured.err
    assert "WARNING" in captured.err


def test_bearer_requires_token(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "catalyst_center:\n  host: localhost\n"
        "transport:\n  auth:\n    type: bearer\n    token: ''\n"
    )
    with pytest.raises(ValueError, match="bearer requires a non-empty"):
        load_config(str(path))


def test_bearer_short_token_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "catalyst_center:\n  host: localhost\n"
        "transport:\n  auth:\n    type: bearer\n    token: 'abc123'\n"  # 6 chars < 8
    )
    with pytest.raises(ValueError, match="too short"):
        load_config(str(path))


def test_bearer_soft_min_warning(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "catalyst_center:\n  host: localhost\n"
        "transport:\n  auth:\n    type: bearer\n    token: 'abcdefgh1234'\n"  # 12 < 16
    )
    load_config(str(path))
    captured = capsys.readouterr()
    assert "shorter than 16" in captured.err


def test_unknown_auth_type_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("catalyst_center:\n  host: localhost\ntransport:\n  auth:\n    type: oauth2\n")
    with pytest.raises(ValueError, match=r"unknown transport\.auth\.type"):
        load_config(str(path))


def test_token_without_bearer_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "catalyst_center:\n  host: localhost\n"
        "transport:\n  auth:\n    type: none\n    token: 'something'\n"
    )
    with pytest.raises(ValueError, match="type=none"):
        load_config(str(path))


def test_dataclasses_are_independent_instances() -> None:
    """Mutating one AppConfig's nested defaults must not bleed into another."""
    a = AppConfig()
    b = AppConfig()
    a.catalyst_center.retries.statuses = (599,)
    assert b.catalyst_center.retries.statuses == (502, 503, 504)


def test_default_config_path_constant() -> None:
    assert DEFAULT_CONFIG_PATH == "catalyst-center-mcp.yaml"


def test_resolve_returns_new_name_when_explicit(tmp_path: Path) -> None:
    explicit = tmp_path / "custom.yaml"
    explicit.write_text("catalyst_center:\n  host: x\n")
    # explicit=True simulates the user passing --config.
    resolved, used_legacy = resolve_config_path(str(explicit), explicit=True)
    assert resolved == str(explicit)
    assert used_legacy is False


def test_resolve_prefers_new_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / DEFAULT_CONFIG_PATH).write_text("catalyst_center:\n  host: x\n")
    (tmp_path / "config.yaml").write_text("catalyst_center:\n  host: y\n")
    resolved, used_legacy = resolve_config_path(DEFAULT_CONFIG_PATH, explicit=False)
    assert resolved == DEFAULT_CONFIG_PATH
    assert used_legacy is False
    captured = capsys.readouterr()
    assert "NOTE" in captured.err
    assert "both" in captured.err
    assert DEFAULT_CONFIG_PATH in captured.err
    assert "config.yaml" in captured.err


def test_resolve_falls_back_to_legacy_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("catalyst_center:\n  host: x\n")
    resolved, used_legacy = resolve_config_path(DEFAULT_CONFIG_PATH, explicit=False)
    assert resolved == "config.yaml"
    assert used_legacy is True
    captured = capsys.readouterr()
    assert "DEPRECATION" in captured.err
    assert "catalyst-center-mcp.yaml" in captured.err
    assert "v0.4.0" in captured.err


def test_resolve_no_fallback_when_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If --config was passed explicitly, never fall back to the legacy name."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text("catalyst_center:\n  host: x\n")
    # User passed an explicit but-missing path — return it unchanged so the
    # normal FileNotFoundError flow fires downstream.
    resolved, used_legacy = resolve_config_path("missing.yaml", explicit=True)
    assert resolved == "missing.yaml"
    assert used_legacy is False
