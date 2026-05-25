"""Runtime configuration loaded from config.yaml + env-var interpolation.

Mirrors the sdwan AppConfig structure, swapping VManageConfig →
CatalystCenterConfig and dropping the use_jwt dual-mode flag (Catalyst
Center has a single auth flow).

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetryConfig:
    pass


@dataclass
class PaginationConfig:
    pass


@dataclass
class CatalystCenterConfig:
    pass


@dataclass
class CatalystCenterMcpConfig:
    pass


@dataclass
class TransportAuthConfig:
    pass


@dataclass
class TransportConfig:
    pass


@dataclass
class AppConfig:
    pass


def load_config(path: str = "config.yaml") -> AppConfig:
    raise NotImplementedError("scaffold only — implement per design doc")
