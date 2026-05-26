"""Download Catalyst Center OpenAPI specs from Cisco DevNet pubhub.

URLs are hardcoded per known version. Unknown versions raise
SpecVersionUnknownError with an actionable message pointing the user at
https://developer.cisco.com/docs/dna-center/ and to KNOWN_SPEC_URLS so
they can add a new entry.

The server invokes this at startup when
catalyst_center_mcp.auto_fetch is true and the version directory is empty.
"""

from __future__ import annotations

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


def _url_filename(url: str) -> str:
    return url.rsplit("/", 1)[-1]


async def fetch_spec(
    version: str,
    dest_dir: Path,
    *,
    verify_ssl: bool = True,
    client: httpx.AsyncClient | None = None,
) -> Path:
    """Download the Catalyst Center OpenAPI spec for `version` into `dest_dir`.

    Returns the path of the written JSON file. Raises SpecVersionUnknownError
    for unknown versions. Network errors propagate. No partial file is left
    behind on failure.
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
        client = httpx.AsyncClient(verify=verify_ssl, timeout=120.0)

    try:
        print(f"[fetcher] Downloading {url}", file=sys.stderr)
        try:
            response = await client.get(url)
            response.raise_for_status()
            tmp.write_bytes(response.content)
            # Validate JSON before declaring success.
            json.loads(tmp.read_bytes())
        except (httpx.HTTPError, json.JSONDecodeError):
            if tmp.exists():
                tmp.unlink()
            raise
        tmp.rename(final)
        print(f"[fetcher] Wrote {final} ({final.stat().st_size} bytes)", file=sys.stderr)
        return final
    finally:
        if owns_client:
            await client.aclose()
