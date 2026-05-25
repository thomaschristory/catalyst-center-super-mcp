"""OpenAPI spec loader and adaptive tool splitter.

Verbatim port of sdwan's loader: section → sub-tag → URL path depth 3/4/5,
buckets with <4 ops collapsed into `<parent>_misc`. Action names derived
from (method, path, tag), not the spec's operationId. Pagination style
detected at load time from parameter names.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParameterSpec:
    pass


@dataclass
class OperationSpec:
    pass


@dataclass
class ToolGroup:
    pass


@dataclass
class SpecIndex:
    pass


class SpecLoader:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("scaffold only — implement per design doc")

    def load(self) -> SpecIndex:
        raise NotImplementedError("scaffold only — implement per design doc")
