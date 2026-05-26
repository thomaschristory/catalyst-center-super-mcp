"""JWT decode + expires_in + needs_refresh tests for auth.py."""

from __future__ import annotations

import base64
import json
import time

from catalyst_center_mcp.auth import _decode_jwt_payload


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
