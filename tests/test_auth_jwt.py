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
