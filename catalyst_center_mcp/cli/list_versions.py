"""`catalyst-center-mcp list-versions` subcommand: enumerate known + on-disk specs."""

from __future__ import annotations

import argparse
from pathlib import Path

from catalyst_center_mcp.config import (
    DEFAULT_CONFIG_PATH,
    AppConfig,
    load_config,
    resolve_config_path,
)
from catalyst_center_mcp.fetcher import KNOWN_SPEC_URLS, list_known_versions


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catalyst-center-mcp list-versions",
        description="List spec versions known to this build and any cached on disk.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help=f"path to the config file (default: ./{DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--specs-dir",
        default=None,
        help="override catalyst_center_mcp.specs_dir from the config file",
    )
    return parser


def _load_config_or_default(config_arg: str | None) -> AppConfig:
    explicit = config_arg is not None
    resolved, _ = resolve_config_path(config_arg or DEFAULT_CONFIG_PATH, explicit=explicit)
    try:
        return load_config(resolved)
    except FileNotFoundError:
        return AppConfig()


def run_list_versions(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    config = _load_config_or_default(args.config)
    specs_dir = Path(args.specs_dir or config.catalyst_center_mcp.specs_dir)

    print("Known versions (hardcoded in KNOWN_SPEC_URLS):")
    for v in sorted(KNOWN_SPEC_URLS):
        print(f"  {v}")

    print()
    print(f"Versions on disk under {specs_dir}/:")
    rows = list_known_versions(specs_dir)
    if not rows:
        print("  (none)")
    else:
        width = max(len(r.version) for r in rows)
        for r in rows:
            tag_parts = []
            if r.cached:
                tag_parts.append("cached")
            if r.extra:
                tag_parts.append("extra")
            tag = ", ".join(tag_parts) if tag_parts else "-"
            print(f"  {r.version:<{width}}  ({tag})")

    return 0
