"""FastMCP server entry point for Catalyst Center Super MCP.

`main()` is the `[project.scripts]` target declared in pyproject.toml. It wires
together config loading, spec loading, upstream auth, dispatcher, tool
registration, and transport selection (stdio / sse / streamable-http).

All non-MCP log lines route to stderr — stdout is reserved for the JSON-RPC
stream when running on stdio transport.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Literal, cast

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.middleware import Middleware

from . import __version__
from .auth import CatalystCenterAuth
from .config import AppConfig, load_config
from .diff import diff_versions, print_diff
from .dispatcher import Dispatcher
from .fetcher import (
    SpecContentInvalidError,
    SpecVersionUnknownError,
    fetch_spec,
)
from .loader import SpecLoader
from .tools import register_tools
from .transport_auth import BearerAuthMiddleware, decide_bind

_VALID_TRANSPORTS: frozenset[str] = frozenset({"stdio", "sse", "streamable-http"})
TransportMode = Literal["stdio", "sse", "streamable-http"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="catalyst-center-mcp",
        description=(
            "FastMCP server for Cisco Catalyst Center, dynamically generated from the OpenAPI spec."
        ),
    )
    parser.add_argument("--config", default="config.yaml", help="path to config.yaml")
    parser.add_argument(
        "--transport",
        choices=sorted(_VALID_TRANSPORTS),
        default=None,
        help="override transport.mode from config.yaml",
    )
    parser.add_argument("--host", default=None, help="override transport.host")
    parser.add_argument("--port", type=int, default=None, help="override transport.port")
    parser.add_argument(
        "--read-write",
        action="store_true",
        help="register POST/PUT/DELETE/PATCH endpoints (read-only by default)",
    )
    parser.add_argument(
        "--version",
        dest="version",
        default=None,
        help="override catalyst_center_mcp.active_version",
    )
    parser.add_argument(
        "--max-actions-per-tool",
        type=int,
        default=None,
        help="override the adaptive splitter cap (0 disables splitting)",
    )
    parser.add_argument(
        "--insecure-allow-public",
        action="store_true",
        help="permit binding 0.0.0.0 with transport.auth.type=none (NOT recommended)",
    )
    parser.add_argument(
        "--diff",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=None,
        help="diff two spec versions and exit",
    )
    parser.add_argument(
        "--show-version",
        action="version",
        version=f"catalyst-center-mcp {__version__}",
    )
    return parser.parse_args(argv)


def _load_config_or_default(config_path: str) -> AppConfig:
    try:
        return load_config(config_path)
    except FileNotFoundError:
        print(f"[server] {config_path} not found — falling back to defaults", file=sys.stderr)
        return AppConfig()


def run_diff(specs_dir: str, old_version: str, new_version: str) -> int:
    diff = diff_versions(specs_dir, old_version, new_version, read_write=True)
    print_diff(diff)
    return 0


async def _maybe_auto_fetch(
    *,
    auto_fetch: bool,
    specs_dir: Path,
    version: str,
) -> None:
    """Download the spec for `version` into `specs_dir/<version>/` if needed.

    Skips when `auto_fetch` is false or when the version directory already
    contains at least one `*.json` file. When auto_fetch is disabled and
    the dir is empty, emits a stderr warning pointing at the knob.

    Fetch failures (unknown version, invalid content, network) are wrapped
    in a RuntimeError with an actionable `[startup]` prefix so users get a
    clean error rather than a stack trace.
    """
    version_dir = specs_dir / version
    has_specs = version_dir.exists() and any(version_dir.glob("*.json"))
    if not auto_fetch:
        if not has_specs:
            print(
                f"[server] WARNING: auto_fetch is disabled and "
                f"{version_dir}/ has no JSON files. Either set "
                f"auto_fetch: true in config.yaml, or download the spec "
                f"manually from Cisco DevNet to that directory.",
                file=sys.stderr,
            )
        return
    if has_specs:
        return
    print(
        f"[server] auto_fetch enabled — downloading spec for {version}",
        file=sys.stderr,
    )
    try:
        await fetch_spec(version, version_dir)
    except (SpecVersionUnknownError, SpecContentInvalidError, httpx.HTTPError) as exc:
        raise RuntimeError(
            f"[startup] auto-fetch failed for version {version}: {exc}. "
            f"Set auto_fetch: false in config.yaml and place the spec "
            f"manually under {version_dir}/, or fix the upstream issue."
        ) from exc


async def _connect_and_register(
    args: argparse.Namespace,
) -> tuple[FastMCP, Dispatcher, TransportMode, str, int, list[Middleware]]:
    load_dotenv()
    config = _load_config_or_default(args.config)

    version = args.version or config.catalyst_center_mcp.active_version
    transport = args.transport or config.transport.mode
    if transport not in _VALID_TRANSPORTS:
        raise ValueError(
            f"Unsupported transport: {transport!r}. Choose one of {sorted(_VALID_TRANSPORTS)}."
        )
    transport_mode = cast(TransportMode, transport)
    host = args.host or config.transport.host
    port = args.port or config.transport.port
    read_write = args.read_write
    max_actions = (
        args.max_actions_per_tool
        if args.max_actions_per_tool is not None
        else config.catalyst_center_mcp.max_actions_per_tool
    )

    middleware_list: list[Middleware] = []
    if transport_mode != "stdio":
        effective_host, warnings = decide_bind(
            host=host,
            auth_type=config.transport.auth.type,
            insecure_ok=args.insecure_allow_public,
        )
        for line in warnings:
            print(f"[server] WARNING: {line}", file=sys.stderr)
        host = effective_host
        if config.transport.auth.type == "bearer":
            middleware_list.append(
                Middleware(BearerAuthMiddleware, expected_token=config.transport.auth.token)
            )

    print(
        f"[server] Catalyst Center Super MCP v{__version__} — "
        f"version={version}, RO={'no' if read_write else 'yes'}, transport={transport_mode}",
        file=sys.stderr,
    )

    await _maybe_auto_fetch(
        auto_fetch=config.catalyst_center_mcp.auto_fetch,
        specs_dir=Path(config.catalyst_center_mcp.specs_dir),
        version=version,
    )

    index = SpecLoader(
        config.catalyst_center_mcp.specs_dir,
        version,
        read_write=read_write,
        max_actions_per_tool=max_actions,
    ).load()

    auth = CatalystCenterAuth(
        host=config.catalyst_center.host,
        port=config.catalyst_center.port,
        username=config.catalyst_center.username,
        password=config.catalyst_center.password,
        verify_ssl=config.catalyst_center.verify_ssl,
    )
    dispatcher = Dispatcher(
        base_url=config.catalyst_center.base_url,
        auth=auth,
        verify_ssl=config.catalyst_center.verify_ssl,
        timeout=config.catalyst_center.timeout,
        pagination=config.catalyst_center_mcp.pagination,
        retry=config.catalyst_center.retries,
    )
    await dispatcher.connect()
    dispatcher.set_index(index)

    mcp = FastMCP("catalyst-center-mcp")
    register_tools(mcp, index, dispatcher)
    return mcp, dispatcher, transport_mode, host, port, middleware_list


def build_and_run(args: argparse.Namespace) -> int:
    mcp, dispatcher, transport_mode, host, port, middleware = asyncio.run(
        _connect_and_register(args)
    )
    try:
        if transport_mode == "stdio":
            mcp.run()
        else:
            mcp.run(
                transport=transport_mode,
                host=host,
                port=port,
                middleware=middleware,
            )
    finally:
        asyncio.run(dispatcher.close())
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.diff:
        config = _load_config_or_default(args.config)
        old, new = args.diff
        return run_diff(config.catalyst_center_mcp.specs_dir, old, new)

    return build_and_run(args)


if __name__ == "__main__":
    sys.exit(main())
