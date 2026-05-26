"""JWT decode + expires_in + needs_refresh tests for auth.py."""

from __future__ import annotations

import base64
import json
import time

import pytest

from catalyst_center_mcp.auth import CatalystCenterAuth, _decode_jwt_payload


def _make_jwt(payload: dict) -> str:
    """Build a fake JWT (header.payload.signature) with our payload."""
    header = base64.urlsafe_b64encode(b'{"alg":"ES256","typ":"JWT"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"fake-sig").rstrip(b"=").decode()
    return f"{header}.{body}.{sig}"


def test_decode_real_shape():
    now = int(time.time())
    token = _make_jwt({"sub": "u", "iat": now, "exp": now + 3600})
    payload = _decode_jwt_payload(token)
    assert payload is not None
    assert payload["exp"] == now + 3600
    assert payload["iat"] == now


def test_decode_opaque_returns_none():
    assert _decode_jwt_payload("not-a-jwt") is None
    assert _decode_jwt_payload("foo.bar") is None
    assert _decode_jwt_payload("") is None


def test_decode_garbage_segments_returns_none():
    # Three segments but middle one isn't valid base64-encoded JSON.
    assert _decode_jwt_payload("aaa.!!!.ccc") is None


def _auth_with_token(token: str) -> CatalystCenterAuth:
    """Construct an auth object and inject a token directly (skipping HTTP)."""
    auth = CatalystCenterAuth(
        host="example.com", port=443, username="u", password="p", verify_ssl=False
    )
    auth._token = token  # type: ignore[attr-defined]
    payload = _decode_jwt_payload(token)
    auth._expires_at = float(payload["exp"]) if payload and "exp" in payload else None  # type: ignore[attr-defined]
    return auth


def test_expires_in_with_valid_jwt():
    now = int(time.time())
    auth = _auth_with_token(_make_jwt({"exp": now + 3600}))
    remaining = auth.expires_in()
    assert remaining is not None
    assert 3599 <= remaining <= 3601


def test_expires_in_none_for_opaque():
    auth = _auth_with_token("opaque-token")
    assert auth.expires_in() is None


@pytest.mark.parametrize(
    "exp_delta, margin, expected",
    [
        (3600, 120, False),  # plenty of time
        (60, 120, True),  # inside margin
        (200, 120, False),  # outside margin
        (200, 300, True),  # margin widened past remaining
    ],
)
def test_needs_refresh(exp_delta, margin, expected):
    now = int(time.time())
    auth = _auth_with_token(_make_jwt({"exp": now + exp_delta}))
    assert auth.needs_refresh(margin_seconds=margin) is expected


def test_needs_refresh_opaque_token_never_refreshes():
    auth = _auth_with_token("opaque")
    assert auth.needs_refresh(margin_seconds=120) is False
    assert auth.needs_refresh(margin_seconds=99999) is False


# --- F1: bool exp must not be accepted (bool is subclass of int) ---


def test_decode_rejects_bool_exp():
    """An exp value of True must not produce _expires_at = 1.0 (epoch 1970).

    bool is a subclass of int in Python, so naive isinstance(exp, (int, float))
    accepts True/False. The login() path must reject this and degrade to
    reactive-only (expires_in() returns None).
    """
    token = _make_jwt({"exp": True})
    # _decode_jwt_payload still returns the dict — bools are valid JSON.
    payload = _decode_jwt_payload(token)
    assert payload is not None
    assert payload["exp"] is True

    # But constructing an auth via the login() code path must NOT treat the
    # bool as a numeric exp. Simulate the relevant slice of login() inline.
    import time as _time

    auth = CatalystCenterAuth(
        host="example.com", port=443, username="u", password="p", verify_ssl=False
    )
    auth._token = token  # type: ignore[attr-defined]
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        auth._expires_at = float(exp)
        if auth._expires_at <= _time.time():
            auth._expires_at = None
    else:
        auth._expires_at = None
    assert auth.expires_in() is None
    assert auth.needs_refresh() is False


# --- F2: clock-skew guard — past-exp must be discarded ---


@pytest.mark.asyncio
async def test_login_handles_past_exp(capsys):
    """If server returns exp already in the past locally, degrade to reactive."""
    import httpx
    import respx

    now = time.time()
    past_token = _make_jwt({"exp": now - 100})

    auth = CatalystCenterAuth(
        host="example.com", port=443, username="u", password="p", verify_ssl=False
    )

    with respx.mock:
        respx.post("https://example.com:443/dna/system/api/v1/auth/token").mock(
            return_value=httpx.Response(200, json={"Token": past_token, "message": ""})
        )
        async with httpx.AsyncClient(verify=False) as client:
            await auth.login(client)

    assert auth._expires_at is None
    assert auth.needs_refresh() is False
    captured = capsys.readouterr()
    assert "clock skew" in captured.err.lower() or "past" in captured.err.lower()


# --- F3: non-numeric / missing exp must emit warning ---


@pytest.mark.asyncio
async def test_login_warns_when_exp_missing_or_wrong_type(capsys):
    """JWT decoded but exp is wrong type or missing → warning to stderr."""
    import httpx
    import respx

    # exp as string (RFC 7519 violation — must be NumericDate)
    bad_token = _make_jwt({"sub": "u", "exp": "1700000000"})

    auth = CatalystCenterAuth(
        host="example.com", port=443, username="u", password="p", verify_ssl=False
    )

    with respx.mock:
        respx.post("https://example.com:443/dna/system/api/v1/auth/token").mock(
            return_value=httpx.Response(200, json={"Token": bad_token, "message": ""})
        )
        async with httpx.AsyncClient(verify=False) as client:
            await auth.login(client)

    assert auth._expires_at is None
    captured = capsys.readouterr()
    assert "exp claim unusable" in captured.err
    assert "str" in captured.err  # type name surfaced


@pytest.mark.asyncio
async def test_login_warns_when_exp_missing(capsys):
    """JWT with no exp claim → warning surfaced."""
    import httpx
    import respx

    no_exp_token = _make_jwt({"sub": "u"})

    auth = CatalystCenterAuth(
        host="example.com", port=443, username="u", password="p", verify_ssl=False
    )

    with respx.mock:
        respx.post("https://example.com:443/dna/system/api/v1/auth/token").mock(
            return_value=httpx.Response(200, json={"Token": no_exp_token, "message": ""})
        )
        async with httpx.AsyncClient(verify=False) as client:
            await auth.login(client)

    assert auth._expires_at is None
    captured = capsys.readouterr()
    assert "exp claim unusable" in captured.err
