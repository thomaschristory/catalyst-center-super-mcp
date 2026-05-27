"""v0.2.0 live-sandbox smoke probes.

Runs three probes against sandboxdnac.cisco.com to verify the v0.2.0 changes
that respx-only tests can't cover:

1. Disambig fix — call `get_devices_count__network_device` and confirm it
   reaches /dna/intent/api/v1/network-device/count (not the rogue-threats
   endpoint that v0.1.0 silently hit).
2. Fetcher live — point at a fresh tmp dir and confirm pubhub download +
   shape validation + atomic write all work end-to-end.
3. Proactive refresh — force `_expires_at` close to now, make a call, and
   confirm the dispatcher proactively re-logs in (stderr log assertion).

Usage:
    CATALYST_CENTER_USERNAME=devnetuser CATALYST_CENTER_PASSWORD='Cisco123!' \
        uv run python scripts/sandbox_smoke_v0.2.0.py
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
import time
from contextlib import redirect_stderr
from pathlib import Path

import httpx

from catalyst_center_mcp.auth import CatalystCenterAuth
from catalyst_center_mcp.dispatcher import Dispatcher
from catalyst_center_mcp.fetcher import KNOWN_SPEC_URLS, fetch_spec
from catalyst_center_mcp.loader import SpecLoader

HOST = "sandboxdnac.cisco.com"
PORT = 443


def banner(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


async def probe_1_disambig(username: str, password: str) -> dict:
    banner("Probe 1 — disambig fix: get_devices_count__network_device")
    auth = CatalystCenterAuth(
        host=HOST, port=PORT, username=username, password=password, verify_ssl=False
    )
    index = SpecLoader("./specs", "2.3.7.9", read_write=False).load()
    d = Dispatcher(
        base_url=f"https://{HOST}:{PORT}",
        auth=auth,
        verify_ssl=False,
    )
    d.set_index(index)
    await d.connect()
    try:
        op = index.by_action_name.get("get_devices_count__network_device")
        if op is None:
            return {"ok": False, "reason": "action name not found in index"}
        print(f"  resolves to: {op.method.upper()} {op.path}")
        result = await d.call("get_devices_count__network_device", {})
        print(f"  response: {result}")
        ok = (
            isinstance(result, dict)
            and op.path == "/dna/intent/api/v1/network-device/count"
            and "response" in result
        )
        return {"ok": ok, "path": op.path, "response": result}
    finally:
        await d.close()


async def probe_2_fetcher() -> dict:
    banner("Probe 2 — fetcher live: pubhub download + validation")
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "2.3.7.9"
        url = KNOWN_SPEC_URLS["2.3.7.9"]
        print(f"  url: {url}")
        try:
            path = await fetch_spec("2.3.7.9", dest)
            size = path.stat().st_size
            data = json.loads(path.read_bytes())
            has_paths = "paths" in data
            has_openapi = "openapi" in data or "swagger" in data
            print(
                f"  wrote {path.name} ({size:,} bytes), "
                f"openapi/swagger key: {has_openapi}, paths key: {has_paths}, "
                f"path count: {len(data.get('paths', {}))}"
            )
            return {
                "ok": has_paths and has_openapi and size > 1_000_000,
                "size": size,
                "path_count": len(data.get("paths", {})),
            }
        except Exception as exc:  # noqa: BLE001 — surfacing real network error
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


async def probe_3_proactive(username: str, password: str) -> dict:
    banner("Probe 3 — proactive refresh: force needs_refresh() True")
    auth = CatalystCenterAuth(
        host=HOST, port=PORT, username=username, password=password, verify_ssl=False
    )
    index = SpecLoader("./specs", "2.3.7.9", read_write=False).load()
    d = Dispatcher(
        base_url=f"https://{HOST}:{PORT}",
        auth=auth,
        verify_ssl=False,
    )
    d.set_index(index)
    await d.connect()
    initial_token = auth._token  # noqa: SLF001
    initial_exp = auth._expires_at  # noqa: SLF001
    print(f"  initial token suffix: …{initial_token[-12:]}")
    print(f"  initial exp: {initial_exp} ({initial_exp - time.time():+.0f}s)")

    auth._expires_at = time.time() + 30  # noqa: SLF001 — inside margin=120 → refresh

    err_capture = io.StringIO()
    try:
        with redirect_stderr(err_capture):
            result = await d.call("get_devices_count__network_device", {})
    finally:
        await d.close()
    err = err_capture.getvalue()
    refreshed = auth._token  # noqa: SLF001
    proactive_log = "proactive refresh" in err.lower() or "nearing expiry" in err.lower()
    token_rotated = refreshed != initial_token

    print(f"  refreshed token suffix: …{refreshed[-12:]}")
    print(f"  token rotated: {token_rotated}")
    print(f"  proactive log seen: {proactive_log}")
    print(f"  call result OK: {isinstance(result, dict) and 'response' in result}")
    return {
        "ok": proactive_log and token_rotated and isinstance(result, dict),
        "proactive_log_seen": proactive_log,
        "token_rotated": token_rotated,
    }


async def main() -> int:
    username = os.environ.get("CATALYST_CENTER_USERNAME", "devnetuser")
    password = os.environ.get("CATALYST_CENTER_PASSWORD", "Cisco123!")

    results: dict[str, dict] = {}
    try:
        results["disambig"] = await probe_1_disambig(username, password)
    except Exception as exc:  # noqa: BLE001
        results["disambig"] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    try:
        results["fetcher"] = await probe_2_fetcher()
    except Exception as exc:  # noqa: BLE001
        results["fetcher"] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    try:
        results["proactive"] = await probe_3_proactive(username, password)
    except Exception as exc:  # noqa: BLE001
        results["proactive"] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    banner("Summary")
    for name, r in results.items():
        verdict = "PASS" if r.get("ok") else "FAIL"
        print(f"  {name:12s} {verdict}  {r}")

    return 0 if all(r.get("ok") for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
