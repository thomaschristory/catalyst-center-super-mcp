"""Tests for HTTP transport bearer auth and bind-safety."""

from __future__ import annotations

from typing import Any

import pytest

from catalyst_center_mcp.transport_auth import (
    BearerAuthMiddleware,
    decide_bind,
)


def test_loopback_never_demoted() -> None:
    host, warnings = decide_bind("127.0.0.1", "none", insecure_ok=False)
    assert host == "127.0.0.1" and warnings == []


def test_localhost_never_demoted() -> None:
    host, warnings = decide_bind("localhost", "none", insecure_ok=False)
    assert host == "localhost" and warnings == []


def test_public_with_bearer_allowed() -> None:
    host, warnings = decide_bind("0.0.0.0", "bearer", insecure_ok=False)
    assert host == "0.0.0.0" and warnings == []


def test_public_with_none_demoted() -> None:
    host, warnings = decide_bind("0.0.0.0", "none", insecure_ok=False)
    assert host == "127.0.0.1"
    assert any("refusing to bind" in w for w in warnings)
    assert any("--insecure-allow-public" in w for w in warnings)


def test_public_with_none_and_insecure_flag_allowed() -> None:
    host, warnings = decide_bind("0.0.0.0", "none", insecure_ok=True)
    assert host == "0.0.0.0" and warnings == []


def test_bearer_middleware_rejects_empty_token_config() -> None:
    async def _stub(scope: Any, receive: Any, send: Any) -> None:
        return None

    with pytest.raises(ValueError, match="non-empty"):
        BearerAuthMiddleware(app=_stub, expected_token="")


async def _passthrough_app(scope: dict, receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _make_scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "path": "/messages",
        "client": ("1.2.3.4", 12345),
        "headers": headers or [],
    }


async def _collect_send() -> tuple[list[dict], Any]:
    messages: list[dict] = []

    async def send(msg: dict) -> None:
        messages.append(msg)

    return messages, send


@pytest.mark.asyncio
async def test_missing_auth_header_rejected() -> None:
    mw = BearerAuthMiddleware(_passthrough_app, expected_token="t" * 16)
    messages, send = await _collect_send()

    async def receive() -> dict:
        return {"type": "http.request"}

    await mw(_make_scope(), receive, send)
    assert messages[0]["status"] == 401
    challenge = dict(messages[0]["headers"])[b"www-authenticate"]
    assert b'realm="catalyst-center"' in challenge


@pytest.mark.asyncio
async def test_wrong_token_rejected() -> None:
    mw = BearerAuthMiddleware(_passthrough_app, expected_token="t" * 16)
    messages, send = await _collect_send()

    async def receive() -> dict:
        return {"type": "http.request"}

    scope = _make_scope([(b"authorization", b"Bearer not-the-right-token")])
    await mw(scope, receive, send)
    assert messages[0]["status"] == 401


@pytest.mark.asyncio
async def test_correct_token_passes_through() -> None:
    mw = BearerAuthMiddleware(_passthrough_app, expected_token="t" * 16)
    messages, send = await _collect_send()

    async def receive() -> dict:
        return {"type": "http.request"}

    scope = _make_scope([(b"authorization", ("Bearer " + "t" * 16).encode())])
    await mw(scope, receive, send)
    assert messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_non_http_scope_passes_through_unchecked() -> None:
    """Lifespan / websocket frames must not be rejected by the auth middleware."""
    mw = BearerAuthMiddleware(_passthrough_app, expected_token="t" * 16)
    messages, send = await _collect_send()

    async def receive() -> dict:
        return {"type": "lifespan.startup"}

    scope = {"type": "lifespan"}
    await mw(scope, receive, send)
    # Passthrough app sends a 200 — middleware did not intercept.
    assert messages[0]["status"] == 200
