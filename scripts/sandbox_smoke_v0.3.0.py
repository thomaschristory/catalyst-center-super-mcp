"""v0.3.0 live-sandbox smoke probes.

Runs five probes against sandboxdnac.cisco.com to verify v0.3.0 changes plus
v0.2.0 regression coverage:

Regressions from v0.2.0:
1. Disambig fix — call `get_devices_count__network_device` and confirm it
   reaches /dna/intent/api/v1/network-device/count.
2. Fetcher live — point at a fresh tmp dir and confirm pubhub download +
   shape validation + atomic write all work end-to-end.
3. Proactive refresh — force `_expires_at` close to now, make a call, and
   confirm the dispatcher proactively re-logs in.

New in v0.3.0:
4. `fetch` CLI subcommand — invoke `catalyst-center-mcp fetch 2.3.7.9
   --specs-dir <tmp>` as a subprocess and confirm a spec JSON file lands
   on disk.
5. `discover-versions` CLI subcommand — invoke against the real DevNet
   page. Expected outcome (per postmortem): exit 2 with DiscoveryError
   because the page is JS-only. The probe passes if the exit code matches
   the documented experimental behavior.

Usage:
    CATALYST_CENTER_USERNAME=devnetuser CATALYST_CENTER_PASSWORD='Cisco123!' \
        uv run python scripts/sandbox_smoke_v0.3.0.py
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stderr
from pathlib import Path

from catalyst_center_mcp.auth import CatalystCenterAuth
from catalyst_center_mcp.dispatcher import Dispatcher
from catalyst_center_mcp.fetcher import KNOWN_SPEC_URLS, fetch_spec
from catalyst_center_mcp.loader import SpecLoader

HOST = "sandboxdnac.cisco.com"
PORT = 443


def banner(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


async def probe_1_disambig(username: str, password: str) -> dict:
    banner("Probe 1 — disambig regression: get_devices_count__network_device")
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
        return {"ok": ok, "path": op.path}
    finally:
        await d.close()


async def probe_2_fetcher() -> dict:
    banner("Probe 2 — fetcher regression: pubhub download + validation")
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
                f"paths: {len(data.get('paths', {}))}"
            )
            return {
                "ok": has_paths and has_openapi and size > 1_000_000,
                "size": size,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


async def probe_3_proactive(username: str, password: str) -> dict:
    banner("Probe 3 — proactive-refresh regression: force needs_refresh() True")
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

    print(f"  token rotated: {token_rotated}, proactive log seen: {proactive_log}")
    return {
        "ok": proactive_log and token_rotated and isinstance(result, dict),
        "token_rotated": token_rotated,
        "proactive_log": proactive_log,
    }


def probe_4_fetch_cli() -> dict:
    banner("Probe 4 — fetch CLI subcommand against real pubhub")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proc = subprocess.run(
                [
                    "uv", "run", "catalyst-center-mcp",
                    "fetch", "2.3.7.9", "--specs-dir", tmp,
                ],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            print(f"  exit={proc.returncode}")
            print(f"  stderr tail: {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else '(empty)'}")
            files = list((Path(tmp) / "2.3.7.9").glob("*.json"))
            ok = proc.returncode == 0 and len(files) == 1 and files[0].stat().st_size > 1_000_000
            print(f"  files: {[f.name for f in files]}")
            return {
                "ok": ok,
                "exit": proc.returncode,
                "file_count": len(files),
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "reason": "subprocess timeout"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def probe_5_discover_versions() -> dict:
    banner("Probe 5 — discover-versions CLI against real DevNet")
    try:
        proc = subprocess.run(
            ["uv", "run", "catalyst-center-mcp", "discover-versions"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        print(f"  exit={proc.returncode}")
        print(f"  stderr tail: {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else '(empty)'}")
        # Per postmortem: DevNet is JS-only, so exit 2 (DiscoveryError) is the
        # documented experimental outcome. If exit becomes 0 (DevNet republished
        # static markup), that's a positive surprise worth investigating.
        ok = proc.returncode in (0, 2)
        return {
            "ok": ok,
            "exit": proc.returncode,
            "note": "exit 2 expected (JS SPA)" if proc.returncode == 2 else "exit 0 — DevNet may have changed",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "subprocess timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


async def main() -> int:
    username = os.environ.get("CATALYST_CENTER_USERNAME", "devnetuser")
    password = os.environ.get("CATALYST_CENTER_PASSWORD", "Cisco123!")

    results: dict[str, dict] = {}
    for name, coro in [
        ("disambig", probe_1_disambig(username, password)),
        ("fetcher", probe_2_fetcher()),
        ("proactive", probe_3_proactive(username, password)),
    ]:
        try:
            results[name] = await coro
        except Exception as exc:  # noqa: BLE001
            results[name] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    results["fetch_cli"] = probe_4_fetch_cli()
    results["discover_cli"] = probe_5_discover_versions()

    banner("Summary")
    for name, r in results.items():
        verdict = "PASS" if r.get("ok") else "FAIL"
        print(f"  {name:14s} {verdict}  {r}")

    return 0 if all(r.get("ok") for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
