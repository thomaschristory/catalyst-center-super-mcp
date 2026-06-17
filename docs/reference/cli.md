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
                    [--debug] [--debug-all-calls] [--debug-no-redact]
                    [--diff OLD NEW]
                    [--show-version]
```

| Flag | Purpose |
|---|---|
| `--config PATH` | Path to the config file. Defaults to `./catalyst-center-mcp.yaml`. A legacy `config.yaml` is no longer auto-detected — rename it to `catalyst-center-mcp.yaml` or pass it explicitly via `--config`. |
| `--transport` | Override `transport.mode`. |
| `--host`, `--port` | Override `transport.host` / `transport.port`. |
| `--read-write` | Register POST/PUT/DELETE/PATCH endpoints. Read-only by default. |
| `--version` | Override `catalyst_center_mcp.active_version`. |
| `--max-actions-per-tool N` | Override the adaptive-splitter cap (0 disables splitting). |
| `--insecure-allow-public` | Permit binding `0.0.0.0` with `transport.auth.type=none`. Not recommended. |
| `--debug` | Capture the upstream Catalyst Center request/response on failed calls and surface a redacted `debug` object in the tool result + stderr. Off by default; observational only (no new tool, safe in read-only mode). Equivalent to `CATALYST_CENTER_MCP_DEBUG=1`. |
| `--debug-all-calls` | With `--debug`: capture every call, not just failures (verbose). Equivalent to `CATALYST_CENTER_MCP_DEBUG_CAPTURE=all`. |
| `--debug-no-redact` | With `--debug`: do **not** strip auth headers / credential-shaped body values from captured output. Only safe on a trusted local terminal. Equivalent to `CATALYST_CENTER_MCP_DEBUG_REDACT=0`. |
| `--diff OLD NEW` | Diff two on-disk spec versions and exit. |
| `--show-version` | Print version and exit. |

The `--debug*` flags default to `None` (not `False`) so an unset flag never
overrides an env/YAML `debug.*` setting — only an explicitly passed flag wins,
preserving the CLI > env > YAML precedence used everywhere else.

### Debug mode (#31)

Debug mode is **off by default and changes nothing when off**. Turning it on
makes the dispatcher attach a structured `debug` object to tool results and log
the same record to stderr (one `[dispatcher][debug] {...}` JSON line), so you
can see exactly what was sent to and returned by Catalyst Center — the resolved
method/path, the **exact serialized request body actually sent**, and the full
upstream status / error code / headers / body, plus timing and the tool/action
name. It is the way to diagnose opaque upstream errors from the *facts of the
exchange* rather than guessing.

With `redact: true` (the default), the captured `debug` object and its stderr
line are scrubbed so they are safe to share:

- **Auth headers** — `X-Auth-Token`, `Authorization`, `Cookie`, `Set-Cookie`
  (and `Proxy-Authorization`) — are replaced with `<redacted>`.
- **Credential-shaped body/query values** — the value of any key matching
  `token` / `secret` / `password` / `cookie` / `credential` / `apiKey` /
  `sessionId` / `privateKey` (case-insensitive) is replaced with `<redacted>`.
  This matters because Catalyst Center's auth endpoint returns the credential
  *in the response body* as `{"Token": "..."}` — header-only redaction would
  leak it into a capture labelled "safe to share".

Redaction is scoped to the diagnostic capture; the primary tool result is the
data the caller requested and is returned as-is. Oversized captured bodies are
truncated. `capture: errors` (default) attaches `debug` only to failed calls;
`capture: all` also attaches it to dict-shaped successes (list/str successes go
to stderr only, to avoid reshaping the payload). The env equivalents are
`CATALYST_CENTER_MCP_DEBUG`, `CATALYST_CENTER_MCP_DEBUG_REDACT`, and
`CATALYST_CENTER_MCP_DEBUG_CAPTURE`.

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
(`https://developer.cisco.com/docs/catalyst-center/`) for Catalyst Center spec
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
