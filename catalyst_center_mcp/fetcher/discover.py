"""Discover Catalyst Center spec versions by scraping DevNet's docs index.

The DevNet docs page at ``https://developer.cisco.com/docs/dna-center/`` lists
spec versions and their pubhub download URLs. We extract them via a single
regex over the raw HTML rather than executing JS, mirroring the sdwan project's
discover.py approach.

If the page changes shape (zero matches), ``parse_discovery_html`` raises
``DiscoveryError`` so the failure is loud rather than silent.

Known limitation (recon 2026-05-27):
    The live DevNet landing page is largely a JS SPA. The static HTML
    typically contains only the *current* spec's slug
    (``cisco-catalyst-center-api-<ver>``) and UUID, often without the full
    ``intent_api_<ver>.json`` filename. In practice the regex below may
    match zero URLs against the live page, which intentionally raises
    ``DiscoveryError``. The maintainer should then inspect the page
    manually and update ``KNOWN_SPEC_URLS`` in
    ``catalyst_center_mcp/fetcher/__init__.py``. The regex IS exercised by
    a synthetic-HTML test suite so the parser stays correct should DevNet
    publish a static, fully-linked index in future.

Network usage:
    ``discover_versions()`` makes one HTTPS request to ``DEVNET_INDEX_URL``.
    TLS verification is always on — DevNet is a public CDN, MITM risk
    doesn't depend on any Catalyst Center config.
"""

from __future__ import annotations

import re
from typing import Final

import httpx

DEVNET_INDEX_URL: Final[str] = "https://developer.cisco.com/docs/dna-center/"


class DiscoveryError(RuntimeError):
    """Raised when the DevNet page contains no extractable spec links."""


# Matches: https://pubhub.devnetcloud.com/media/cisco-catalyst-center-api-<ver>/docs/<uuid>/intent_api_<ver-snake>.json
# UUID format here is 8-4-4-4-12 hex.
_SPEC_URL_RE: Final[re.Pattern[str]] = re.compile(
    r"https://pubhub\.devnetcloud\.com/media/cisco-catalyst-center-api-"
    r"(?P<slug>[0-9a-zA-Z\-]+)"
    r"/docs/"
    r"(?P<uuid>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"/intent_api_[0-9a-zA-Z_]+\.json"
)


def _slug_to_version(slug: str) -> str:
    """``2-3-7-9`` -> ``2.3.7.9``."""
    return slug.replace("-", ".")


def parse_discovery_html(html: str) -> dict[str, str]:
    """Extract ``{version: url}`` from DevNet's docs HTML.

    Raises ``DiscoveryError`` when no matches are found — the strongest
    signal the SPA shape has changed.
    """
    out: dict[str, str] = {}
    for match in _SPEC_URL_RE.finditer(html):
        version = _slug_to_version(match.group("slug"))
        # Keep the first occurrence per version (the page may repeat links).
        out.setdefault(version, match.group(0))
    if not out:
        raise DiscoveryError(
            f"Found no spec links matching the pubhub URL pattern on the DevNet page. "
            f"The page's HTML shape may have changed, or DevNet is now a pure JS SPA "
            f"with no static spec links. Inspect {DEVNET_INDEX_URL} manually and "
            f"update KNOWN_SPEC_URLS in catalyst_center_mcp/fetcher/__init__.py."
        )
    return out


def discover_versions(*, client: httpx.Client | None = None) -> dict[str, str]:
    """Fetch DevNet's docs index page and return ``{version: pubhub_url}``.

    Does NOT mutate ``KNOWN_SPEC_URLS``. Always verifies TLS.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client(verify=True, timeout=30.0, follow_redirects=True)
    try:
        response = client.get(DEVNET_INDEX_URL)
        response.raise_for_status()
        return parse_discovery_html(response.text)
    finally:
        if owns_client:
            client.close()
