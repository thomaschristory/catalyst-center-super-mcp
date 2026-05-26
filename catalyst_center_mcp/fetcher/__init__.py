"""Download Catalyst Center OpenAPI specs from Cisco DevNet pubhub.

URLs are hardcoded per known version. Unknown versions raise
SpecVersionUnknownError with an actionable message pointing the user at
https://developer.cisco.com/docs/dna-center/ and to KNOWN_SPEC_URLS so
they can add a new entry.

The server invokes this at startup when
catalyst_center_mcp.auto_fetch is true and the version directory is empty.

Security note — TLS verification:
    The downloads target pubhub.devnetcloud.com, a public HTTPS CDN. This
    fetcher ALWAYS verifies TLS (`verify=True`) regardless of what the
    Catalyst Center config says about `verify_ssl`. Catalyst Center
    deployments often use self-signed certs, but that property has no
    bearing on whether we trust a public CDN — disabling verification
    here would open a MITM vector to inject a malicious spec.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import httpx

# Source URLs sourced from the v0.1.0 commit messages that bundled the
# existing specs (commits 531e3eb and 6466dd4). Update by appending a new
# entry when a new Catalyst Center version is needed.
KNOWN_SPEC_URLS: dict[str, str] = {
    "2.3.7.9": "https://pubhub.devnetcloud.com/media/cisco-catalyst-center-api-2-3-7-9/docs/8b234339-c3e3-3557-ad9b-57b9789cd681/intent_api_2_3_7_9.json",
    "3.1.3": "https://pubhub.devnetcloud.com/media/cisco-catalyst-center-api-3-1-3/docs/d41c7da7-f399-330a-bd19-886309e55849/intent_api_3_1_3.json",
}


class SpecVersionUnknownError(RuntimeError):
    """Raised when fetch_spec is asked for a version not in KNOWN_SPEC_URLS."""


class SpecContentInvalidError(RuntimeError):
    """Raised when the downloaded body parses as JSON but isn't an OpenAPI/Swagger spec."""


def _url_filename(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def _validate_spec_shape(parsed: object, url: str, raw: bytes) -> None:
    """Ensure parsed JSON looks like an OpenAPI 3.x or Swagger 2.0 document.

    Raises SpecContentInvalidError otherwise. We do NOT validate the full
    schema — only enough to catch pubhub error envelopes (e.g. a 200 OK
    JSON `{"error": "rate-limited"}`) that would otherwise fail far away
    inside SpecLoader.
    """
    snippet = raw[:200].decode("utf-8", errors="replace")
    if not isinstance(parsed, dict):
        raise SpecContentInvalidError(
            f"Downloaded body from {url} parsed as JSON but is not a dict "
            f"(got {type(parsed).__name__}). First 200 chars: {snippet!r}. "
            f"Check whether pubhub rotated the URL."
        )
    if "openapi" not in parsed and "swagger" not in parsed:
        raise SpecContentInvalidError(
            f"Downloaded body from {url} is JSON but has no 'openapi' or "
            f"'swagger' top-level key. First 200 chars: {snippet!r}. "
            f"Check whether pubhub rotated the URL."
        )
    if "paths" not in parsed:
        raise SpecContentInvalidError(
            f"Downloaded body from {url} is JSON but has no 'paths' top-level "
            f"key. First 200 chars: {snippet!r}. "
            f"Check whether pubhub rotated the URL."
        )


async def fetch_spec(
    version: str,
    dest_dir: Path,
    *,
    client: httpx.AsyncClient | None = None,
) -> Path:
    """Download the Catalyst Center OpenAPI spec for `version` into `dest_dir`.

    Returns the path of the written JSON file. Raises SpecVersionUnknownError
    for unknown versions, SpecContentInvalidError if pubhub returned 200 but
    not an OpenAPI document, or propagates httpx errors. No partial file is
    left behind on any failure.

    TLS verification is always on. See module docstring.
    """
    url = KNOWN_SPEC_URLS.get(version)
    if url is None:
        supported = ", ".join(sorted(KNOWN_SPEC_URLS))
        raise SpecVersionUnknownError(
            f"No known download URL for Catalyst Center version '{version}'. "
            f"Supported: {supported}. "
            f"To add a new version, find its download URL at "
            f"https://developer.cisco.com/docs/dna-center/ and append it to "
            f"catalyst_center_mcp/fetcher/__init__.py:KNOWN_SPEC_URLS."
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / _url_filename(url)
    tmp = final.with_suffix(final.suffix + ".tmp")

    owns_client = client is None
    if client is None:
        # verify=True always — pubhub is a public CDN, MITM risk doesn't
        # depend on Catalyst Center's cert trust.
        # follow_redirects=True — pubhub may serve via CDN with 302s.
        client = httpx.AsyncClient(verify=True, timeout=120.0, follow_redirects=True)

    try:
        print(f"[fetcher] Downloading {url}", file=sys.stderr)
        try:
            response = await client.get(url)
            response.raise_for_status()
            tmp.write_bytes(response.content)
            parsed = json.loads(tmp.read_bytes())
            _validate_spec_shape(parsed, url, response.content)
        except Exception:
            # Any failure (HTTP, JSON parse, shape, OSError) → wipe temp file.
            # missing_ok + suppressed OSError so cleanup never masks the real error.
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            raise
        tmp.rename(final)
        print(f"[fetcher] Wrote {final} ({final.stat().st_size} bytes)", file=sys.stderr)
        return final
    finally:
        if owns_client:
            await client.aclose()
