"""Loads catalyst-center-mcp.yaml (or legacy config.yaml) and resolves ${ENV_VAR} interpolation."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import yaml

# Minimum bearer-token lengths. Below the hard floor we refuse to start;
# between the soft and hard floors we emit a stderr WARNING. 16 base64 chars
# ≈ 96 bits of entropy, enough to resist online brute force when paired with
# rate-limited logging.
_TOKEN_HARD_MIN = 8
_TOKEN_SOFT_MIN = 16

DEFAULT_CONFIG_PATH = "catalyst-center-mcp.yaml"
_LEGACY_CONFIG_PATH = "config.yaml"


def resolve_config_path(path: str, *, explicit: bool) -> tuple[str, bool]:
    """Resolve the effective config path, honoring the v0.3.0 rename.

    Returns ``(effective_path, used_legacy)``. When ``explicit`` is True the
    user passed ``--config`` so we return ``path`` unchanged and never fall
    back to the legacy name. When ``explicit`` is False (default path) and
    ``catalyst-center-mcp.yaml`` is absent but ``config.yaml`` exists, we
    return the legacy name and emit a one-line stderr DEPRECATION warning.

    TODO(v0.4.0): remove the legacy fallback. The deprecation warning has
    been live since v0.3.0; users have one minor cycle to rename their file.
    """
    if explicit:
        return path, False
    if Path(path).exists():
        return path, False
    legacy = Path(_LEGACY_CONFIG_PATH)
    if legacy.exists():
        # stderr-only; stdio MCP uses stdout for JSON-RPC.
        print(
            f"[config] DEPRECATION: '{_LEGACY_CONFIG_PATH}' is the v0.2.0 default; "
            f"rename to '{DEFAULT_CONFIG_PATH}' before v0.4.0. "
            f"  mv {_LEGACY_CONFIG_PATH} {DEFAULT_CONFIG_PATH}",
            file=sys.stderr,
        )
        return _LEGACY_CONFIG_PATH, True
    return path, False


@dataclass
class RetryConfig:
    """Retry policy for transient HTTP failures from Catalyst Center."""

    max_attempts: int = 3  # total attempts including the first try
    statuses: tuple[int, ...] = (502, 503, 504)
    backoff_base: float = 0.5  # seconds; first backoff is base * 2**0
    backoff_cap: float = 8.0  # upper bound on a single backoff
    retry_mutating: bool = False  # by default, only GET is retried


@dataclass
class CatalystCenterConfig:
    host: str
    port: int = 443
    verify_ssl: bool = True
    username: str = ""
    password: str = ""
    timeout: float = 30.0  # seconds per HTTP request
    retries: RetryConfig = field(default_factory=RetryConfig)

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}"


@dataclass
class PaginationConfig:
    enabled: bool = True
    max_pages: int = 5
    page_size: int | None = None


@dataclass
class CatalystCenterMcpConfig:
    specs_dir: str = "./specs"
    active_version: str = "2.3.7.9"
    max_actions_per_tool: int = 80  # 0 disables splitting (one tool per section)
    pagination: PaginationConfig = field(default_factory=PaginationConfig)
    auto_fetch: bool = False


_VALID_AUTH_TYPES: frozenset[str] = frozenset({"none", "bearer"})


@dataclass
class TransportAuthConfig:
    """Authentication for the HTTP transports (SSE, streamable-http).

    type='none' — no auth (only safe on loopback or behind a trusted proxy).
    type='bearer' — require `Authorization: Bearer <token>` on every request.
    """

    type: Literal["none", "bearer"] = "none"
    token: str = ""


@dataclass
class TransportConfig:
    mode: str = "stdio"  # stdio | sse | streamable-http
    host: str = "127.0.0.1"
    port: int = 8000
    auth: TransportAuthConfig = field(default_factory=TransportAuthConfig)


@dataclass
class AppConfig:
    catalyst_center: CatalystCenterConfig = field(
        default_factory=lambda: CatalystCenterConfig(host="")
    )
    catalyst_center_mcp: CatalystCenterMcpConfig = field(default_factory=CatalystCenterMcpConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)


_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _interpolate(value: str) -> str:
    """Substitute ${VAR} from os.environ; missing → empty string + stderr WARNING (stdout would corrupt stdio MCP JSON-RPC stream)."""

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        result = os.environ.get(var_name, "")
        if not result:
            print(f"[config] WARNING: env var '{var_name}' is not set", file=sys.stderr)
        return result

    return _ENV_RE.sub(replacer, value)


def _interpolate_dict(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _interpolate_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate_dict(i) for i in obj]
    if isinstance(obj, str):
        return _interpolate(obj)
    return obj


def load_config(path: str = "config.yaml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = yaml.safe_load(config_path.read_text()) or {}
    raw = _interpolate_dict(raw)

    cc_raw = raw.get("catalyst_center", {}) or {}
    mcp_raw = raw.get("catalyst_center_mcp", {}) or {}
    transport_raw = raw.get("transport", {}) or {}

    retries_raw = cc_raw.get("retries", {}) or {}
    retry_defaults = RetryConfig()
    statuses_raw = retries_raw.get("statuses") or list(retry_defaults.statuses)
    retries = RetryConfig(
        max_attempts=int(retries_raw.get("max_attempts", retry_defaults.max_attempts)),
        statuses=tuple(int(s) for s in statuses_raw),
        backoff_base=float(retries_raw.get("backoff_base", retry_defaults.backoff_base)),
        backoff_cap=float(retries_raw.get("backoff_cap", retry_defaults.backoff_cap)),
        retry_mutating=bool(retries_raw.get("retry_mutating", retry_defaults.retry_mutating)),
    )

    catalyst_center = CatalystCenterConfig(
        host=cc_raw.get("host", ""),
        port=int(cc_raw.get("port", 443)),
        verify_ssl=bool(cc_raw.get("verify_ssl", True)),
        username=cc_raw.get("username", ""),
        password=cc_raw.get("password", ""),
        timeout=float(cc_raw.get("timeout", 30.0)),
        retries=retries,
    )

    pagination_raw = mcp_raw.get("pagination", {}) or {}
    pagination = PaginationConfig(
        enabled=bool(pagination_raw.get("enabled", True)),
        max_pages=int(pagination_raw.get("max_pages", 5)),
        page_size=(
            int(pagination_raw["page_size"])
            if pagination_raw.get("page_size") is not None
            else None
        ),
    )

    catalyst_center_mcp = CatalystCenterMcpConfig(
        specs_dir=mcp_raw.get("specs_dir", "./specs"),
        active_version=str(mcp_raw.get("active_version", "2.3.7.9")),
        max_actions_per_tool=int(mcp_raw.get("max_actions_per_tool", 80)),
        pagination=pagination,
        auto_fetch=bool(mcp_raw.get("auto_fetch", False)),
    )

    auth_raw = transport_raw.get("auth", {}) or {}
    auth_type_str = str(auth_raw.get("type", "none"))
    auth_token = str(auth_raw.get("token", ""))

    if auth_type_str not in _VALID_AUTH_TYPES:
        raise ValueError(
            f"unknown transport.auth.type: {auth_type_str!r}. "
            f"Choose one of {sorted(_VALID_AUTH_TYPES)}."
        )
    auth_type: Literal["none", "bearer"] = cast(Literal["none", "bearer"], auth_type_str)

    if auth_type == "bearer" and not auth_token:
        raise ValueError(
            "transport.auth.type=bearer requires a non-empty transport.auth.token "
            "(set ${CATALYST_CENTER_MCP_TOKEN} or equivalent, or check the env var is exported)."
        )
    if auth_type == "bearer" and len(auth_token) < _TOKEN_HARD_MIN:
        raise ValueError(
            f"transport.auth.token is too short ({len(auth_token)} chars); "
            f"require at least {_TOKEN_HARD_MIN} characters. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    if auth_type == "bearer" and len(auth_token) < _TOKEN_SOFT_MIN:
        print(
            f"[config] WARNING: transport.auth.token is shorter than "
            f"{_TOKEN_SOFT_MIN} chars — recommend regenerating with "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"',
            file=sys.stderr,
        )
    if auth_type_str == "none" and auth_token:
        raise ValueError(
            "token configured but transport.auth.type=none — "
            "set type: bearer to enable it, or remove the token."
        )

    transport = TransportConfig(
        mode=transport_raw.get("mode", "stdio"),
        host=transport_raw.get("host", "127.0.0.1"),
        port=int(transport_raw.get("port", 8000)),
        auth=TransportAuthConfig(type=auth_type, token=auth_token),
    )

    return AppConfig(
        catalyst_center=catalyst_center,
        catalyst_center_mcp=catalyst_center_mcp,
        transport=transport,
    )
