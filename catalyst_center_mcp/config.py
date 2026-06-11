"""Application configuration for catalyst-center-mcp.

Sources, highest priority first:

    1. constructor kwargs (programmatic / CLI overrides applied in server.py)
    2. environment variables (CATALYST_CENTER_HOST, CATALYST_CENTER_PORT,
       CATALYST_CENTER_USERNAME, CATALYST_CENTER_PASSWORD,
       CATALYST_CENTER_VERIFY_SSL)
    3. the YAML config file (optional), with legacy ``${ENV}`` interpolation
    4. built-in defaults (the Cisco DevNet always-on sandbox)

The YAML file is **optional**: exporting the env vars (or putting them in a
``.env``) is enough to run, which is what makes the server work when installed
via ``uv tool install`` and launched by an MCP client (whose working directory
is not the user's project dir, so no YAML is on disk). See issue #26.
"""

from __future__ import annotations

import os
import re
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

# Minimum bearer-token lengths. Below the hard floor we refuse to start;
# between the soft and hard floors we emit a stderr WARNING. 16 base64 chars
# ≈ 96 bits of entropy, enough to resist online brute force when paired with
# rate-limited logging.
_TOKEN_HARD_MIN = 8
_TOKEN_SOFT_MIN = 16

DEFAULT_CONFIG_PATH = "catalyst-center-mcp.yaml"
_LEGACY_CONFIG_PATH = "config.yaml"

_VALID_AUTH_TYPES: frozenset[str] = frozenset({"none", "bearer"})

# Default Catalyst Center retry statuses (kept as a module constant so a YAML
# ``statuses: ~`` falls back here instead of crashing).
_DEFAULT_RETRY_STATUSES: tuple[int, ...] = (502, 503, 504)


def resolve_config_path(path: str, *, explicit: bool) -> tuple[str, bool]:
    """Resolve the effective config path, honoring the v0.3.0 rename.

    Returns ``(effective_path, used_legacy)``. When ``explicit`` is True the
    user passed ``--config`` so we return ``path`` unchanged and never fall
    back to the legacy name. When ``explicit`` is False (default path) and
    ``catalyst-center-mcp.yaml`` is absent but ``config.yaml`` exists, we
    return the legacy name and emit a one-line stderr DEPRECATION warning.

    TODO(v0.5.0): remove the legacy fallback. The deprecation warning has
    been live since v0.3.0; users have had minor cycles to rename their file.
    """
    if explicit:
        return path, False
    if Path(path).exists():
        if path == DEFAULT_CONFIG_PATH and Path(_LEGACY_CONFIG_PATH).exists():
            # Both files coexist — pick the new one but flag the ambiguity so
            # the user knows which is being used and how to silence the notice.
            print(
                f"[config] NOTE: both '{DEFAULT_CONFIG_PATH}' and "
                f"'{_LEGACY_CONFIG_PATH}' are present;\n"
                f"using '{DEFAULT_CONFIG_PATH}'. Delete '{_LEGACY_CONFIG_PATH}' "
                f"to silence this notice.",
                file=sys.stderr,
            )
        return path, False
    legacy = Path(_LEGACY_CONFIG_PATH)
    if legacy.exists():
        # stderr-only; stdio MCP uses stdout for JSON-RPC.
        print(
            f"[config] DEPRECATION: '{_LEGACY_CONFIG_PATH}' is the v0.2.0 default; "
            f"rename to '{DEFAULT_CONFIG_PATH}' before v0.5.0. "
            f"  mv {_LEGACY_CONFIG_PATH} {DEFAULT_CONFIG_PATH}",
            file=sys.stderr,
        )
        return _LEGACY_CONFIG_PATH, True
    return path, False


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class _Base(BaseModel):
    """Shared base: drop YAML ``null`` values so model defaults apply."""

    @model_validator(mode="before")
    @classmethod
    def _drop_nones(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


class RetryConfig(_Base):
    """Retry policy for transient HTTP failures from Catalyst Center."""

    max_attempts: int = 3  # total attempts including the first try
    statuses: tuple[int, ...] = _DEFAULT_RETRY_STATUSES
    backoff_base: float = 0.5  # seconds; first backoff is base * 2**0
    backoff_cap: float = 8.0  # upper bound on a single backoff
    retry_mutating: bool = False  # by default, only GET is retried

    @model_validator(mode="before")
    @classmethod
    def _statuses_none_to_default(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("statuses") is None:
            data = {k: v for k, v in data.items() if k != "statuses"}
        return data


class CatalystCenterConfig(_Base):
    # Defaults point at the Cisco DevNet always-on Catalyst Center sandbox, so
    # the server runs out of the box once credentials are supplied via env.
    host: str = "sandboxdnac.cisco.com"
    port: int = 443
    verify_ssl: bool = True
    username: str = ""
    password: str = ""
    timeout: float = 30.0  # seconds per HTTP request
    retries: RetryConfig = Field(default_factory=RetryConfig)

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}"


class PaginationConfig(_Base):
    enabled: bool = True
    max_pages: int = 5
    page_size: int | None = None


class CatalystCenterMcpConfig(_Base):
    specs_dir: str = "./specs"
    active_version: str = "2.3.7.9"
    max_actions_per_tool: int = 80  # 0 disables splitting (one tool per section)
    pagination: PaginationConfig = Field(default_factory=PaginationConfig)
    auto_fetch: bool = False


class TransportAuthConfig(_Base):
    """Authentication for the HTTP transports (SSE, streamable-http).

    type='none' — no auth (only safe on loopback or behind a trusted proxy).
    type='bearer' — require `Authorization: Bearer <token>` on every request.
    """

    type: Literal["none", "bearer"] = "none"
    token: str = ""


class TransportConfig(_Base):
    mode: str = "stdio"  # stdio | sse | streamable-http
    host: str = "127.0.0.1"
    port: int = 8000
    auth: TransportAuthConfig = Field(default_factory=TransportAuthConfig)


# ---------------------------------------------------------------------------
# Settings sources
# ---------------------------------------------------------------------------

# YAML data for the current load_config() call. A ContextVar keeps load_config
# re-entrant and thread-safe without leaking the path into module state.
_yaml_data: ContextVar[dict[str, Any] | None] = ContextVar("_yaml_data", default=None)


class _YamlSource(PydanticBaseSettingsSource):
    """Feeds the (already interpolated) YAML dict into the settings model."""

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(_yaml_data.get() or {})


class _CatalystCenterEnvSource(PydanticBaseSettingsSource):
    """Maps the documented flat env vars onto ``catalyst_center.*``.

    These take precedence over the YAML file so credentials/host can be
    overridden per-environment without editing the file (or with no file)."""

    _MAP: ClassVar[dict[str, str]] = {
        "CATALYST_CENTER_HOST": "host",
        "CATALYST_CENTER_PORT": "port",
        "CATALYST_CENTER_USERNAME": "username",
        "CATALYST_CENTER_PASSWORD": "password",
        "CATALYST_CENTER_VERIFY_SSL": "verify_ssl",
    }

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        catalyst_center: dict[str, Any] = {}
        for env_name, field in self._MAP.items():
            value = os.environ.get(env_name)
            if value:  # ignore unset and empty — let YAML/defaults stand
                catalyst_center[field] = value  # pydantic coerces str -> int/bool
        return {"catalyst_center": catalyst_center} if catalyst_center else {}


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    catalyst_center: CatalystCenterConfig = Field(default_factory=CatalystCenterConfig)
    catalyst_center_mcp: CatalystCenterMcpConfig = Field(default_factory=CatalystCenterMcpConfig)
    transport: TransportConfig = Field(default_factory=TransportConfig)

    @model_validator(mode="before")
    @classmethod
    def _drop_none_sections(cls, data: Any) -> Any:
        # A bare YAML section (e.g. `catalyst_center:` with nothing under it)
        # parses to None; drop it so the section's defaults apply.
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Priority: init kwargs > flat CATALYST_CENTER_* env > YAML file > defaults.
        return (
            init_settings,
            _CatalystCenterEnvSource(settings_cls),
            _YamlSource(settings_cls),
        )


# ---------------------------------------------------------------------------
# Env var interpolation (legacy ${VAR} support inside YAML values)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _validate_transport_auth(transport: TransportConfig) -> None:
    auth_type = transport.auth.type
    token = transport.auth.token

    if auth_type not in _VALID_AUTH_TYPES:  # pragma: no cover - Literal guards this
        raise ValueError(
            f"unknown transport.auth.type: {auth_type!r}. "
            f"Choose one of {sorted(_VALID_AUTH_TYPES)}."
        )
    if auth_type == "bearer" and not token:
        raise ValueError(
            "transport.auth.type=bearer requires a non-empty transport.auth.token "
            "(set ${CATALYST_CENTER_MCP_TOKEN} or equivalent, or check the env var is exported)."
        )
    if auth_type == "bearer" and len(token) < _TOKEN_HARD_MIN:
        raise ValueError(
            f"transport.auth.token is too short ({len(token)} chars); "
            f"require at least {_TOKEN_HARD_MIN} characters. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    if auth_type == "bearer" and len(token) < _TOKEN_SOFT_MIN:
        print(
            f"[config] WARNING: transport.auth.token is shorter than "
            f"{_TOKEN_SOFT_MIN} chars — recommend regenerating with "
            'python -c "import secrets; print(secrets.token_urlsafe(32))"',
            file=sys.stderr,
        )
    if auth_type == "none" and token:
        raise ValueError(
            "token configured but transport.auth.type=none — "
            "set type: bearer to enable it, or remove the token."
        )


def load_config(path: str = DEFAULT_CONFIG_PATH, *, required: bool = False) -> AppConfig:
    """Build the application config.

    The YAML file is optional. If it is absent and ``required`` is False, the
    config is assembled from environment variables and defaults. Pass
    ``required=True`` (server.py does this when ``--config`` is given
    explicitly) to error on a missing file the user asked for.

    Precedence: CLI/init > CATALYST_CENTER_* env > YAML > defaults.
    """
    config_path = Path(path)
    raw: dict[str, Any] = {}

    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = _interpolate_dict(loaded)
    elif required:
        raise FileNotFoundError(f"Config file not found: {path}")

    token = _yaml_data.set(raw)
    try:
        config = AppConfig()
    finally:
        _yaml_data.reset(token)

    _validate_transport_auth(config.transport)
    return config
