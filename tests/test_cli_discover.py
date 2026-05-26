"""Tests for the `discover-versions` CLI subcommand."""

from __future__ import annotations

import httpx
import pytest
import respx

from catalyst_center_mcp.cli.discover import run_discover_versions
from catalyst_center_mcp.fetcher import KNOWN_SPEC_URLS
from catalyst_center_mcp.fetcher.discover import DEVNET_INDEX_URL


def _html_with(versions: dict[str, str]) -> str:
    """Build a synthetic HTML body containing pubhub URLs for each version.

    Each URL is rendered with a fake-but-shape-valid UUID and matching
    intent_api filename so the parser regex matches.
    """
    lines = []
    for v, url in versions.items():
        lines.append(f'<a href="{url}">{v}</a>')
    return "<html><body>" + "\n".join(lines) + "</body></html>"


def _synth_url(version: str) -> str:
    """Build a synthetic pubhub URL for `version` matching the regex."""
    slug = version.replace(".", "-")
    snake = version.replace(".", "_")
    return (
        f"https://pubhub.devnetcloud.com/media/cisco-catalyst-center-api-{slug}"
        f"/docs/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/intent_api_{snake}.json"
    )


@respx.mock
def test_discover_exit_zero_when_discovered_superset(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Discovered contains everything in KNOWN_SPEC_URLS plus one extra.
    discovered = {**KNOWN_SPEC_URLS, "9.9.9": _synth_url("9.9.9")}
    respx.get(DEVNET_INDEX_URL).mock(return_value=httpx.Response(200, text=_html_with(discovered)))
    rc = run_discover_versions([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "+ 9.9.9" in out
    for v in KNOWN_SPEC_URLS:
        assert f"= {v}" in out


@respx.mock
def test_discover_exit_one_on_stale_hardcoded(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Discovered is missing one known version.
    only_one = dict(list(KNOWN_SPEC_URLS.items())[:1])
    respx.get(DEVNET_INDEX_URL).mock(return_value=httpx.Response(200, text=_html_with(only_one)))
    rc = run_discover_versions([])
    out = capsys.readouterr().out
    assert rc == 1
    missing = list(KNOWN_SPEC_URLS)[1]
    assert f"- {missing}" in out


@respx.mock
def test_discover_unchanged_when_exact_match(
    capsys: pytest.CaptureFixture[str],
) -> None:
    respx.get(DEVNET_INDEX_URL).mock(
        return_value=httpx.Response(200, text=_html_with(KNOWN_SPEC_URLS))
    )
    rc = run_discover_versions([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "+ " not in out
    assert "- " not in out


@respx.mock
def test_discover_503_returns_exit_2() -> None:
    """Network errors specifically return exit 2 (not 1, not bare nonzero)."""
    respx.get(DEVNET_INDEX_URL).mock(return_value=httpx.Response(503))
    assert run_discover_versions([]) == 2


@respx.mock
def test_discover_connect_error_returns_exit_2() -> None:
    """ConnectError (not just HTTP status errors) returns exit 2."""
    respx.get(DEVNET_INDEX_URL).mock(side_effect=httpx.ConnectError("dns fail"))
    assert run_discover_versions([]) == 2


@respx.mock
def test_discover_shape_changed_returns_exit_2() -> None:
    """A 200 with no recognizable URLs (SPA / shape changed) → DiscoveryError → exit 2."""
    respx.get(DEVNET_INDEX_URL).mock(return_value=httpx.Response(200, text="<html>spa</html>"))
    assert run_discover_versions([]) == 2


def test_help_marks_experimental(capsys: pytest.CaptureFixture[str]) -> None:
    """[experimental] marker must remain visible in --help output."""
    with pytest.raises(SystemExit):
        run_discover_versions(["--help"])
    captured = capsys.readouterr()
    output = (captured.out + captured.err).lower()
    assert "experimental" in output
