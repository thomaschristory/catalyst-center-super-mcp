"""Tests for fetcher.discover.discover_versions and HTML parsing.

The live DevNet page is largely a JS SPA and may not contain full pubhub URLs
at all (see module docstring in catalyst_center_mcp/fetcher/discover.py). The
synthetic HTML below mirrors the IDEAL static shape so the parser stays
correctly tested even when the live page is unreachable from CI.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from catalyst_center_mcp.fetcher.discover import (
    DEVNET_INDEX_URL,
    DiscoveryError,
    discover_versions,
    parse_discovery_html,
)

# Synthetic HTML mirroring the IDEAL fully-static shape: a JS object literal
# (or anchor) inside the page containing complete pubhub spec URLs.
SAMPLE_HTML = """
<html><body>
<script>
var webJson = {
  links: [
    {"label": "2.3.7.9", "url": "https://pubhub.devnetcloud.com/media/cisco-catalyst-center-api-2-3-7-9/docs/8b234339-c3e3-3557-ad9b-57b9789cd681/intent_api_2_3_7_9.json"},
    {"label": "3.1.3",   "url": "https://pubhub.devnetcloud.com/media/cisco-catalyst-center-api-3-1-3/docs/d41c7da7-f399-330a-bd19-886309e55849/intent_api_3_1_3.json"},
    {"label": "3.2.0",   "url": "https://pubhub.devnetcloud.com/media/cisco-catalyst-center-api-3-2-0/docs/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/intent_api_3_2_0.json"}
  ]
};
</script>
</body></html>
"""


def test_parse_extracts_tuples() -> None:
    result = parse_discovery_html(SAMPLE_HTML)
    assert result["2.3.7.9"].endswith("intent_api_2_3_7_9.json")
    assert result["3.1.3"].endswith("intent_api_3_1_3.json")
    assert result["3.2.0"].endswith("intent_api_3_2_0.json")


def test_parse_no_matches_raises() -> None:
    with pytest.raises(DiscoveryError, match="no spec links"):
        parse_discovery_html("<html>nothing relevant</html>")


@respx.mock
def test_discover_versions_uses_devnet_url() -> None:
    respx.get(DEVNET_INDEX_URL).mock(return_value=httpx.Response(200, text=SAMPLE_HTML))
    result = discover_versions()
    assert "2.3.7.9" in result
    assert "3.1.3" in result
    assert "3.2.0" in result
