# catalyst-center-super-mcp

FastMCP server for the Cisco Catalyst Center (formerly DNA Center) API,
generated dynamically from the official OpenAPI specs.

Sibling project to [`catalyst-sdwan-super-mcp`](https://github.com/thomaschristory/catalyst-sdwan-super-mcp).

## Status

**v0.1.0 — scaffold only.** Auth, loader, dispatcher, and tool registration
modules are stubs (`NotImplementedError`). See
`docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md`
for what's intentionally deferred and why.

## Install (once published)

```bash
uv tool install catalyst-center-super-mcp
```

## Configure

Copy `.env.example` to `.env` and fill in your Catalyst Center credentials.
See `config.yaml` for runtime knobs (transport, splitting cap, retries,
pagination).

## Run

```bash
catalyst-center-mcp                              # stdio (Claude Desktop)
catalyst-center-mcp --transport sse --host 0.0.0.0 --port 8000
```

## License

Apache-2.0 — see `LICENSE`.
