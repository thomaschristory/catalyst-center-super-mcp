# catalyst-center-super-mcp

FastMCP server for the Cisco Catalyst Center (formerly DNA Center) API,
generated dynamically from the official OpenAPI specs.

Sibling project to [`catalyst-sdwan-super-mcp`](https://github.com/thomaschristory/catalyst-sdwan-super-mcp).

## Status

See [`CHANGELOG.md`](CHANGELOG.md) for the current release and what changed.

## Install (once published)

```bash
uv tool install catalyst-center-super-mcp
```

## Configure

Copy `.env.example` to `.env` and fill in your Catalyst Center credentials.

The YAML config file is **optional** — exporting `CATALYST_CENTER_USERNAME` /
`CATALYST_CENTER_PASSWORD` (or a `.env`) is enough to start, which is what makes
the server work under `uv tool install` + an MCP client (whose working directory
is not your project dir). Settings resolve in this order, highest first:

**CLI flags > environment variables > YAML file > built-in defaults.**

Env vars: `CATALYST_CENTER_HOST`, `CATALYST_CENTER_PORT`,
`CATALYST_CENTER_USERNAME`, `CATALYST_CENTER_PASSWORD`,
`CATALYST_CENTER_VERIFY_SSL`. When launched by an MCP client, set them in the
client's server `env` block (the client does not inherit your shell exports).

See `catalyst-center-mcp.yaml` for the remaining runtime knobs (transport,
splitting cap, retries, pagination).

## Run

```bash
catalyst-center-mcp                              # stdio (Claude Desktop)
catalyst-center-mcp --transport sse --host 0.0.0.0 --port 8000
```

## License

Apache-2.0 — see `LICENSE`.
