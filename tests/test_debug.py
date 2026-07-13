"""Tests for debug mode — upstream request/response capture (#31).

Covers three surfaces:
  - config: CATALYST_CENTER_MCP_DEBUG* env parsing + defaults
  - dispatcher: capture on error vs all, redaction on/off, request-body shape
  - CLI: --debug / --debug-all-calls / --debug-no-redact precedence
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import httpx2
import pytest
import respx

from catalyst_center_mcp.auth import CatalystCenterAuth
from catalyst_center_mcp.config import DebugConfig, load_config
from catalyst_center_mcp.dispatcher import (
    Dispatcher,
    _cap_body,
    _redact_data,
    _redact_headers,
)
from catalyst_center_mcp.loader import SpecLoader
from catalyst_center_mcp.server import parse_args, resolve_debug_config

_BASE = "https://cc.test:443"

ERROR_BODY = {
    "response": {
        "errorCode": "NCDP10000",
        "message": "Internal server error",
        "detail": "unexpected",
    }
}


def _make_dispatcher(specs_dir: Path, debug: DebugConfig) -> Dispatcher:
    index = SpecLoader(str(specs_dir), "2.3.7.9", read_write=True).load()
    auth = CatalystCenterAuth(
        host="cc.test",
        port=443,
        username="u",
        password="p",
        verify_ssl=False,
    )
    auth._token = "super-secret-jwt"  # type: ignore[attr-defined]
    d = Dispatcher(
        base_url=_BASE,
        auth=auth,
        verify_ssl=False,
        timeout=5.0,
        debug=debug,
    )
    d.set_index(index)
    return d


# ---------------------------------------------------------------------------
# config — env parsing + defaults
# ---------------------------------------------------------------------------


def test_debug_defaults_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "CATALYST_CENTER_MCP_DEBUG",
        "CATALYST_CENTER_MCP_DEBUG_REDACT",
        "CATALYST_CENTER_MCP_DEBUG_CAPTURE",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = load_config(str(tmp_path / "nope.yaml"))
    assert cfg.debug.enabled is False
    assert cfg.debug.redact is True
    assert cfg.debug.capture == "errors"


def test_debug_env_enables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATALYST_CENTER_MCP_DEBUG", "1")
    cfg = load_config(str(tmp_path / "nope.yaml"))
    assert cfg.debug.enabled is True
    assert cfg.debug.redact is True  # untouched default


def test_debug_env_redact_off_and_capture_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CATALYST_CENTER_MCP_DEBUG", "true")
    monkeypatch.setenv("CATALYST_CENTER_MCP_DEBUG_REDACT", "0")
    monkeypatch.setenv("CATALYST_CENTER_MCP_DEBUG_CAPTURE", "all")
    cfg = load_config(str(tmp_path / "nope.yaml"))
    assert cfg.debug.enabled is True
    assert cfg.debug.redact is False
    assert cfg.debug.capture == "all"


def test_debug_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env wins over YAML, mirroring the CATALYST_CENTER_* precedence."""
    cfg_file = tmp_path / "catalyst-center-mcp.yaml"
    cfg_file.write_text("debug:\n  enabled: false\n  capture: errors\n")
    monkeypatch.setenv("CATALYST_CENTER_MCP_DEBUG", "1")
    monkeypatch.setenv("CATALYST_CENTER_MCP_DEBUG_CAPTURE", "all")
    cfg = load_config(str(cfg_file))
    assert cfg.debug.enabled is True
    assert cfg.debug.capture == "all"


def test_debug_yaml_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "CATALYST_CENTER_MCP_DEBUG",
        "CATALYST_CENTER_MCP_DEBUG_REDACT",
        "CATALYST_CENTER_MCP_DEBUG_CAPTURE",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg_file = tmp_path / "catalyst-center-mcp.yaml"
    cfg_file.write_text("debug:\n  enabled: true\n  redact: false\n")
    cfg = load_config(str(cfg_file))
    assert cfg.debug.enabled is True
    assert cfg.debug.redact is False


@pytest.mark.parametrize("value", ["0", "false", "False", "no", "off"])
def test_debug_env_disable_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """The `if value:` forwarding guard treats "0" as truthy, so disabling
    relies on pydantic's bool coercion — pin that it actually disables."""
    monkeypatch.setenv("CATALYST_CENTER_MCP_DEBUG", value)
    cfg = load_config(str(tmp_path / "nope.yaml"))
    assert cfg.debug.enabled is False


# ---------------------------------------------------------------------------
# redaction helpers (unit)
# ---------------------------------------------------------------------------


def test_redact_headers_masks_auth_when_on() -> None:
    headers = {
        "X-Auth-Token": "jwt",
        "Authorization": "Bearer abc",
        "Cookie": "JSESSIONID=1",
        "Content-Type": "application/json",
    }
    out = _redact_headers(headers, redact=True)
    assert out["X-Auth-Token"] == "<redacted>"
    assert out["Authorization"] == "<redacted>"
    assert out["Cookie"] == "<redacted>"
    assert out["Content-Type"] == "application/json"  # non-secret untouched


def test_redact_headers_case_insensitive() -> None:
    out = _redact_headers({"x-auth-token": "jwt"}, redact=True)
    assert out["x-auth-token"] == "<redacted>"


def test_redact_headers_passthrough_when_off() -> None:
    out = _redact_headers({"X-Auth-Token": "jwt"}, redact=False)
    assert out["X-Auth-Token"] == "jwt"


def test_redact_data_masks_credential_keys() -> None:
    obj = {"Token": "live-jwt", "data": [{"sessionId": "s"}], "field": "ok"}
    out = _redact_data(obj, redact=True)
    assert out["Token"] == "<redacted>"
    assert out["data"][0]["sessionId"] == "<redacted>"
    assert out["field"] == "ok"  # non-sensitive passes through


def test_redact_data_passthrough_when_off() -> None:
    obj = {"Token": "live-jwt"}
    assert _redact_data(obj, redact=False) == obj


def test_cap_body_passes_small_payload() -> None:
    small = {"a": 1}
    assert _cap_body(small) is small


# ---------------------------------------------------------------------------
# dispatcher — capture behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_no_debug_key_when_disabled(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=False))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(500, json=ERROR_BODY)
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()
    assert isinstance(result, dict)
    assert result["error"] is True
    assert "debug" not in result


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_debug_captures_on_error(
    minimal_specs_dir: Path,
    capsys: pytest.CaptureFixture[str],
    httpx2_mock: respx.Router,
) -> None:
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(500, json=ERROR_BODY)
    )
    result = await d.call("get_devices_count__network_device", {}, tool_name="devices")
    await d.close()

    assert isinstance(result, dict)
    dbg = result["debug"]
    assert dbg["tool"] == "devices"
    assert dbg["action"] == "get_devices_count__network_device"
    assert dbg["request"]["method"] == "GET"
    assert dbg["request"]["path"] == "/dna/intent/api/v1/network-device/count"
    assert dbg["response"]["status_code"] == 500
    assert dbg["response"]["error_code"] == "NCDP10000"
    assert dbg["response"]["body"] == ERROR_BODY
    assert isinstance(dbg["timing_ms"], float)
    err = capsys.readouterr().err
    assert "[dispatcher][debug]" in err


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_debug_redacts_auth_headers_by_default(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(500, json=ERROR_BODY)
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()

    assert isinstance(result, dict)
    hdrs = result["debug"]["request"]["headers"]
    assert hdrs["X-Auth-Token"] == "<redacted>"
    # The secret must not leak anywhere in the serialized debug object.
    assert "super-secret-jwt" not in json.dumps(result["debug"])


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_debug_no_redact_keeps_token(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True, redact=False))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(500, json=ERROR_BODY)
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()

    assert isinstance(result, dict)
    assert result["debug"]["request"]["headers"]["X-Auth-Token"] == "super-secret-jwt"


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_debug_captures_request_body_shape(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """A POST forwards params straight to the body — debug must show that the
    payload sits at the top level (the request-shape gotcha)."""
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True))
    payload = {"hostname": "switch-1", "type": "Cisco Catalyst"}
    router = httpx2_mock
    router.post(f"{_BASE}/dna/intent/api/v1/network-device").mock(
        return_value=httpx.Response(500, json=ERROR_BODY)
    )
    result = await d.call("post_devices_network_device", dict(payload))
    await d.close()

    assert isinstance(result, dict)
    body = result["debug"]["request"]["body"]
    assert body == payload  # top-level, not nested under "body"


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_capture_errors_skips_successful_call(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True, capture="errors"))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json={"response": 3, "version": "1.0"})
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()
    assert result == {"response": 3, "version": "1.0"}  # untouched, no debug key


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_capture_all_attaches_on_success_dict(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True, capture="all"))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json={"response": 3})
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()
    assert isinstance(result, dict)
    assert result["response"] == 3
    assert result["debug"]["response"]["status_code"] == 200


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_capture_all_leaves_list_success_unwrapped(
    minimal_specs_dir: Path,
    capsys: pytest.CaptureFixture[str],
    httpx2_mock: respx.Router,
) -> None:
    """A list-shaped success can't carry a debug key without reshaping; it is
    returned verbatim and the record goes to stderr only."""
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True, capture="all"))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json=[1, 2, 3])
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()
    assert result == [1, 2, 3]
    assert "[dispatcher][debug]" in capsys.readouterr().err


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_capture_all_still_captures_error_once(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True, capture="all"))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(500, json=ERROR_BODY)
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()
    assert isinstance(result, dict)
    assert result["error"] is True
    assert result["debug"]["response"]["status_code"] == 500


# ---------------------------------------------------------------------------
# body / query credential scrubbing (#31 — headers aren't enough)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_debug_scrubs_token_returning_response_body(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """Catalyst Center's auth endpoint returns a live token in the BODY as
    {"Token": "..."}; redaction must mask it, not just the auth headers."""
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True, capture="all"))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(200, json={"Token": "LIVE-JWT-TOKEN"})
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()

    assert isinstance(result, dict)
    assert result["Token"] == "LIVE-JWT-TOKEN"  # real payload untouched
    # ...but the captured copy in debug must be scrubbed, and the secret must not
    # appear anywhere in the serialized debug object.
    assert result["debug"]["response"]["body"]["Token"] == "<redacted>"
    assert "LIVE-JWT-TOKEN" not in json.dumps(result["debug"])


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_debug_redaction_is_scoped_to_capture_not_data_plane(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """Redaction scope is the *debug capture*, not the primary result body.

    The server proxies Catalyst Center: the raw response body is the data the
    caller requested and is returned untouched. Only the shareable `debug` copy
    of that exchange is scrubbed. This pins that boundary so a future change
    doesn't silently start mangling the data plane (or stop scrubbing)."""
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(500, json={"Token": "LIVE-TOKEN", "code": "X"})
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()

    assert isinstance(result, dict)
    assert result["body"]["Token"] == "LIVE-TOKEN"  # data plane: untouched
    assert result["debug"]["response"]["body"]["Token"] == "<redacted>"  # capture: scrubbed


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_debug_caps_oversized_body(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    big = {"blob": "x" * 50_000}
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(500, json=big)
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()

    body = result["debug"]["response"]["body"]
    assert body["_truncated"] is True
    assert body["_original_chars"] > 20_000


# ---------------------------------------------------------------------------
# Set-Cookie response-header redaction (response-only leak surface)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_debug_redacts_response_set_cookie(
    minimal_specs_dir: Path,
    capsys: pytest.CaptureFixture[str],
    httpx2_mock: respx.Router,
) -> None:
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(
            500, json=ERROR_BODY, headers={"Set-Cookie": "JSESSIONID=leakme; Path=/"}
        )
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()

    assert isinstance(result, dict)
    resp_headers = result["debug"]["response"]["headers"]
    # httpx lowercases header names; the value must be masked either way.
    assert resp_headers.get("set-cookie", resp_headers.get("Set-Cookie")) == "<redacted>"
    # the cookie must not leak into the result OR the stderr log
    assert "leakme" not in json.dumps(result["debug"])
    assert "leakme" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# transport-level failure (httpx2.RequestError) capture path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_debug_captures_request_error(
    minimal_specs_dir: Path,
    capsys: pytest.CaptureFixture[str],
    httpx2_mock: respx.Router,
) -> None:
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True))
    router = httpx2_mock
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        side_effect=httpx2.ConnectError("connection refused")
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()

    assert isinstance(result, dict)
    assert result["error"] is True
    dbg = result["debug"]
    assert "connection refused" in dbg["request_error"]
    assert "response" not in dbg  # no response was received
    assert dbg["request"]["method"] == "GET"
    assert "[dispatcher][debug]" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# persistent 401 (after re-auth) capture path (#31)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_debug_captures_persistent_401_after_reauth(
    minimal_specs_dir: Path,
    capsys: pytest.CaptureFixture[str],
    httpx2_mock: respx.Router,
) -> None:
    """A 401 that survives a transparent re-auth is the single error class users
    most need to debug (bad creds / token endpoint rejecting them). It must
    carry a debug record and emit a stderr line, like every other HTTP error —
    the first (transparent) 401 round is still NOT captured."""
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True))
    auth_401 = {"response": {"errorCode": "INVALID_CREDENTIALS"}}
    router = httpx2_mock
    # re-auth succeeds so the dispatcher proceeds to the retried round...
    router.post(f"{_BASE}/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "fresh-but-still-rejected"})
    )
    # ...but the data endpoint keeps returning 401 (persistent rejection).
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(401, json=auth_401)
    )
    result = await d.call("get_devices_count__network_device", {}, tool_name="devices")
    await d.close()

    assert isinstance(result, dict)
    assert result["error"] is True
    assert result["status_code"] == 401
    dbg = result["debug"]
    assert dbg["tool"] == "devices"
    assert dbg["response"]["status_code"] == 401
    assert dbg["response"]["error_code"] == "INVALID_CREDENTIALS"
    # exactly one debug line for the retried round — not the transparent first.
    err = capsys.readouterr().err
    assert err.count("[dispatcher][debug]") == 1


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_persistent_401_no_debug_key_when_disabled(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """OFF-is-unchanged: with debug disabled the persistent-401 envelope is the
    plain error, with no debug key and no capture work."""
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=False))
    router = httpx2_mock
    router.post(f"{_BASE}/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "fresh"})
    )
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(401, json={"x": 1})
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()

    assert isinstance(result, dict)
    assert result["error"] is True
    assert result["status_code"] == 401
    assert "debug" not in result


@pytest.mark.asyncio
@pytest.mark.httpx2(assert_all_called=True)
async def test_persistent_401_debug_redacts_response_token(
    minimal_specs_dir: Path, httpx2_mock: respx.Router
) -> None:
    """The captured persistent-401 record is redacted like every other path — a
    token echoed in the 401 body must not leak into the shareable debug copy."""
    d = _make_dispatcher(minimal_specs_dir, DebugConfig(enabled=True))
    router = httpx2_mock
    router.post(f"{_BASE}/dna/system/api/v1/auth/token").mock(
        return_value=httpx.Response(200, json={"Token": "fresh"})
    )
    router.get(f"{_BASE}/dna/intent/api/v1/network-device/count").mock(
        return_value=httpx.Response(401, json={"Token": "LEAKED-401-TOKEN"})
    )
    result = await d.call("get_devices_count__network_device", {})
    await d.close()

    assert isinstance(result, dict)
    assert result["debug"]["response"]["body"]["Token"] == "<redacted>"
    assert result["debug"]["request"]["headers"]["X-Auth-Token"] == "<redacted>"
    assert "LEAKED-401-TOKEN" not in json.dumps(result["debug"])


# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------


def test_cli_debug_flags_default_none() -> None:
    args = parse_args([])
    assert args.debug is None
    assert args.debug_all_calls is None
    assert args.debug_no_redact is None


def test_cli_debug_flags_set() -> None:
    args = parse_args(["--debug", "--debug-all-calls", "--debug-no-redact"])
    assert args.debug is True
    assert args.debug_all_calls is True
    assert args.debug_no_redact is True


# ---------------------------------------------------------------------------
# CLI-over-config merge (resolve_debug_config) — the None-default invariant
# ---------------------------------------------------------------------------


def test_resolve_debug_unset_flags_preserve_config() -> None:
    base = DebugConfig(enabled=True, capture="all", redact=False)
    out = resolve_debug_config(base, debug=None, all_calls=None, no_redact=None)
    assert out == base  # all-None must not override env/YAML state


def test_resolve_debug_flag_enables_without_touching_other_fields() -> None:
    base = DebugConfig(enabled=False, capture="all", redact=True)
    out = resolve_debug_config(base, debug=True, all_calls=None, no_redact=None)
    assert out.enabled is True
    assert out.capture == "all"  # untouched
    assert out.redact is True


def test_resolve_debug_all_and_no_redact_flags() -> None:
    base = DebugConfig(enabled=True)
    out = resolve_debug_config(base, debug=None, all_calls=True, no_redact=True)
    assert out.capture == "all"
    assert out.redact is False
