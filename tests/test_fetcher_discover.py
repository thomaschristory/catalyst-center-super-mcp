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


def test_parse_skips_non_version_slugs(capsys: pytest.CaptureFixture[str]) -> None:
    """Slugs that aren't '\\d+(-\\d+){1,3}' are skipped with a stderr WARNING."""
    bogus = (
        '<a href="https://pubhub.devnetcloud.com/media/cisco-catalyst-center-api-LATEST'
        '/docs/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/intent_api_LATEST.json"></a>'
    )
    with pytest.raises(DiscoveryError):
        parse_discovery_html(bogus)
    captured = capsys.readouterr()
    assert "non-version slug" in captured.err
    assert "LATEST" in captured.err


def test_parse_rejects_non_uuid_path() -> None:
    """A path component that isn't a UUID-8-4-4-4-12 hex must not match."""
    bad = (
        '<a href="https://pubhub.devnetcloud.com/media/cisco-catalyst-center-api-9-9-9-9'
        '/docs/not-a-uuid-here/intent_api_9_9_9_9.json"></a>'
    )
    with pytest.raises(DiscoveryError):
        parse_discovery_html(bad)


def test_parse_first_occurrence_wins_on_duplicate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """If the page lists the same version twice with different UUIDs, keep the first."""
    url1 = (
        "https://pubhub.devnetcloud.com/media/cisco-catalyst-center-api-3-1-3/docs/"
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/intent_api_3_1_3.json"
    )
    url2 = (
        "https://pubhub.devnetcloud.com/media/cisco-catalyst-center-api-3-1-3/docs/"
        "11111111-2222-3333-4444-555555555555/intent_api_3_1_3.json"
    )
    result = parse_discovery_html(f'<a href="{url1}"></a><a href="{url2}"></a>')
    assert result["3.1.3"] == url1
    captured = capsys.readouterr()
    assert "duplicate URLs for version" in captured.err


@respx.mock
def test_discover_versions_200_with_garbage_html_raises() -> None:
    """An HTTP 200 with no matching URLs propagates DiscoveryError (not silent empty dict)."""
    respx.get(DEVNET_INDEX_URL).mock(return_value=httpx.Response(200, text="<html>spa</html>"))
    with pytest.raises(DiscoveryError):
        discover_versions()
