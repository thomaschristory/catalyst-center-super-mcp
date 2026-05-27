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
import sys
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

# Valid slugs look like 2-3-7-9 or 3-1-3: 2..4 dot-separated numeric segments.
_VERSION_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"^\d+(-\d+){1,3}$")


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
        slug = match.group("slug")
        if not _VERSION_SLUG_RE.fullmatch(slug):
            print(
                f"[discover] WARNING: skipping non-version slug {slug!r}",
                file=sys.stderr,
            )
            continue
        version = _slug_to_version(slug)
        existing = out.get(version)
        if existing is None:
            out[version] = match.group(0)
        elif existing != match.group(0):
            print(
                f"[discover] WARNING: duplicate URLs for version {version!r} "
                f"(keeping first: {existing}, ignoring: {match.group(0)})",
                file=sys.stderr,
            )
    if not out:
        raise DiscoveryError(
            f"Found no spec links matching the pubhub URL pattern on the DevNet page. "
            f"The page's HTML shape may have changed. Inspect "
            f"{DEVNET_INDEX_URL} manually and update the regex in "
            f"catalyst_center_mcp/fetcher/discover.py."
        )
    return out


def discover_versions() -> dict[str, str]:
    """Fetch DevNet's docs index page and return ``{version: pubhub_url}``.

    Does NOT mutate ``KNOWN_SPEC_URLS``. Always verifies TLS — the helper owns
    its httpx.Client and never accepts a caller-supplied one (preventing
    accidental ``verify=False`` misuse).
    """
    with httpx.Client(verify=True, timeout=30.0, follow_redirects=True) as client:
        response = client.get(DEVNET_INDEX_URL)
        response.raise_for_status()
        if str(response.url).rstrip("/") != DEVNET_INDEX_URL.rstrip("/"):
            print(
                f"[discover] WARNING: followed redirect to {response.url} "
                f"(expected {DEVNET_INDEX_URL}). Auth wall? Page moved?",
                file=sys.stderr,
            )
        return parse_discovery_html(response.text)
