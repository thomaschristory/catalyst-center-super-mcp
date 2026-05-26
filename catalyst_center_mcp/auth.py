"""Catalyst Center upstream authentication.

Single flow: HTTP Basic against POST /dna/system/api/v1/auth/token returns a
JWT used as the X-Auth-Token header on every subsequent request.

v0.1.0 implements reactive refresh only: the dispatcher catches a 401, calls
login() again, and retries the request once. The JWT carries an `exp` claim
(TTL = 3600s on the always-on DevNet sandbox); proactive refresh based on
`exp` can be added in a future release without changing this module's
public surface.

All warnings/log lines route to stderr — stdout is reserved for the MCP
JSON-RPC stream on the default stdio transport.
"""

from __future__ import annotations

import sys

import httpx


class AuthError(RuntimeError):
    """Raised when login fails or header() is requested before login()."""


_TOKEN_PATH = "/dna/system/api/v1/auth/token"


class CatalystCenterAuth:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool = True,
    ) -> None:
        self._base_url = f"https://{host}:{port}"
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._token: str = ""

    async def login(self, client: httpx.AsyncClient) -> None:
        """POST /dna/system/api/v1/auth/token with HTTP Basic, store the JWT."""
        if not self._username or not self._password:
            raise AuthError(
                "Catalyst Center credentials are not set. "
                "Set CATALYST_CENTER_USERNAME and CATALYST_CENTER_PASSWORD in your .env file."
            )

        try:
            response = await client.post(
                f"{self._base_url}{_TOKEN_PATH}",
                auth=(self._username, self._password),
            )
        except httpx.RequestError as exc:
            raise AuthError(f"Cannot reach Catalyst Center at {self._base_url}: {exc}") from exc

        if response.status_code != 200:
            raise AuthError(
                f"Login failed: HTTP {response.status_code}. Response: {response.text[:200]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AuthError(f"Login response was not JSON: {response.text[:200]}") from exc

        token = data.get("Token")
        if not isinstance(token, str) or not token:
            raise AuthError(f"Login response missing 'Token' field. Body keys: {list(data.keys())}")
        self._token = token
        print(f"[auth] Catalyst Center login successful at {self._base_url}", file=sys.stderr)

    def header(self) -> dict[str, str]:
        """Return the X-Auth-Token header for authenticated requests."""
        if not self._token:
            raise AuthError("Not authenticated — call login() first")
        return {"X-Auth-Token": self._token}
