# CLI reference

The `catalyst-center-mcp` entry point launches the FastMCP server by default,
and also exposes a small set of standalone subcommands that exit without
starting the server.

## Bare invocation (server)

```bash
catalyst-center-mcp [--config PATH] [--transport stdio|sse|streamable-http]
                    [--host HOST] [--port PORT] [--read-write]
                    [--version VERSION] [--max-actions-per-tool N]
                    [--insecure-allow-public]
                    [--diff OLD NEW]
                    [--show-version]
```

| Flag | Purpose |
|---|---|
| `--config PATH` | Path to the config file. Defaults to `./catalyst-center-mcp.yaml`. Legacy `config.yaml` is honored with a deprecation warning. |
| `--transport` | Override `transport.mode`. |
| `--host`, `--port` | Override `transport.host` / `transport.port`. |
| `--read-write` | Register POST/PUT/DELETE/PATCH endpoints. Read-only by default. |
| `--version` | Override `catalyst_center_mcp.active_version`. |
| `--max-actions-per-tool N` | Override the adaptive-splitter cap (0 disables splitting). |
| `--insecure-allow-public` | Permit binding `0.0.0.0` with `transport.auth.type=none`. Not recommended. |
| `--diff OLD NEW` | Diff two on-disk spec versions and exit. |
| `--show-version` | Print version and exit. |

## Subcommands

The first positional token is matched against the subcommand set
(`fetch`, `list-versions`, `discover-versions`) **before** the main argparse
parser runs. When a subcommand matches, the server is not started. All
non-data output routes to stderr so stdio-mode JSON-RPC is never polluted.

### `fetch`

Download an OpenAPI spec for one or all known Catalyst Center versions
without starting the server.

```bash
catalyst-center-mcp fetch <version> [--config PATH] [--specs-dir DIR]
catalyst-center-mcp fetch --all-known [--config PATH] [--specs-dir DIR]
```

Positional `<version>` and `--all-known` are mutually exclusive and one is
required. The spec lands under `{specs_dir}/{version}/{filename}.json`. TLS
verification is always on, regardless of `catalyst_center.verify_ssl` — the
spec source is a public CDN.

Example:

```bash
catalyst-center-mcp fetch 2.3.7.9
catalyst-center-mcp fetch --all-known --specs-dir ./specs
```

### `list-versions`

Enumerate every version baked into this build's `KNOWN_SPEC_URLS` and any
extra version directories already present on disk. **Offline** — makes no
network calls.

```bash
catalyst-center-mcp list-versions [--config PATH] [--specs-dir DIR]
```

Output has two sections: the known-versions list, then the on-disk roster
annotated with `cached` / `extra` tags.

Example:

```bash
$ catalyst-center-mcp list-versions
Known versions (hardcoded in KNOWN_SPEC_URLS):
  2.3.7.9
  3.1.3

Versions on disk under ./specs/:
  2.3.7.9  (cached)
  3.1.3    (cached)
```

### `discover-versions` *(experimental)*

Scrape Cisco DevNet's docs landing page
(`https://developer.cisco.com/docs/dna-center/`) for Catalyst Center spec
versions and print a diff vs the hardcoded `KNOWN_SPEC_URLS` table. Helper
only — it never mutates the hardcoded table; the maintainer copies new
entries in by hand after reviewing.

```bash
catalyst-center-mcp discover-versions
```

No flags beyond `--help`. Always TLS-verified — DevNet is a public CDN.

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Every hardcoded entry was also discovered on DevNet. `+ <version>` lines may appear for new entries DevNet exposes that aren't yet in `KNOWN_SPEC_URLS` — these do not change the exit code. |
| `1` | One or more hardcoded entries are no longer visible on DevNet (`- <version>` lines). The hardcoded table may be stale. |
| `2` | `DiscoveryError` (regex matched zero URLs on the page — DevNet's HTML shape may have changed) or `httpx.HTTPError` (network down, non-2xx). |

**Why `[experimental]`:** DevNet's docs page is largely a JavaScript SPA;
its static HTML may not contain the full pubhub spec URLs the regex
expects. When that happens this command exits 2 with a clear message
pointing at `catalyst_center_mcp/fetcher/__init__.py:KNOWN_SPEC_URLS`
for manual edits. The regex remains exercised by a synthetic-HTML test
suite so it stays correct if DevNet publishes a static, fully-linked
index in future.
