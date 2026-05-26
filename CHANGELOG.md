# Changelog

All notable changes to catalyst-center-super-mcp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-26

First working release. The `catalyst-center-mcp` CLI runs against the always-on
DevNet sandbox (`sandboxdnac.cisco.com`) end-to-end and exposes the Catalyst
Center API as MCP tools.

### Added
- FastMCP server that dynamically registers MCP tools from the Catalyst Center OpenAPI spec at startup.
- Bundled OpenAPI specs for Catalyst Center **2.3.7.9** (default; matches the always-on DevNet sandbox running 2.3.7.10) and **3.1.3** (latest GA).
- Adaptive size-driven tool splitter: section → sub-tag → URL path depth (3/4/5), with `<4`-op buckets collapsed into `<parent>_misc`. Default cap 80 actions per tool, configurable via `catalyst_center_mcp.max_actions_per_tool`.
- Action names derived from `(method, path, tag)` — stable across Cisco's `operationId` churn between releases. The upstream `operationId` is preserved on `OperationSpec` as a back-reference for the `--diff` utility.
- Upstream authentication: HTTP Basic → `POST /dna/system/api/v1/auth/token` → `X-Auth-Token` header. Reactive re-auth on 401 with a single retry.
- Pagination: offset (primary) and cursor (3.1.3 endpoints). Auto-follow up to N pages; responses wrap with `_paginated: {pages, truncated, next_cursor}` metadata when stitched.
- Reserved per-call parameters: `_max_pages`, `_page_size`, `_auto_follow` — stripped before the HTTP request.
- Configurable retry on transient HTTP failures (502/503/504 by default); never retries mutating methods unless `retry_mutating: true`. Exponential backoff with jitter, capped.
- Transports: **stdio** (default), **SSE**, **streamable-http** (FastMCP 3.x).
- Bearer-token auth middleware for HTTP transports, with bind-safety logic that demotes `0.0.0.0` to `127.0.0.1` when `transport.auth.type=none` unless `--insecure-allow-public` is passed.
- `--diff <v1> <v2>` CLI utility: compares two bundled specs and prints added/removed/changed operations (with per-parameter drift).
- Read-only by default. `--read-write` opt-in to register `POST`/`PUT`/`DELETE`/`PATCH` endpoints.
- Tested against the live sandbox: auth, envelope pass-through, and offset-paginated GETs verified end-to-end.

### Deferred to v0.2.0+
- **DevNet spec auto-fetcher** (`fetcher/`) — placeholder only. Specs must be pre-staged in `specs/{version}/`. `auto_fetch: false` is the documented default.
- **Proactive JWT-based token refresh** — the sandbox confirms the JWT TTL is 3600s via the `exp` claim. v0.1.0 relies on reactive 401 re-auth; proactive refresh can be added later without changing the public surface.
- **Task-poll helper** (`_await_task` reserved-param seam) — scoped out for v0.1.0. The LLM orchestrates Catalyst Center's `taskId` poll loop directly.
- **Cross-tool action-name disambiguation** — within a tool, action names that collide (e.g. multiple `*/count` endpoints in the `Devices` tag) are deduped by appending `_2`, `_3`, …. This is inherited from the sibling sdwan implementation. The tool description shown to the LLM lists every action with its `(METHOD path)` annotation so the right one is identifiable; a path-derived suffix on collision is a v0.2.0 candidate.

[0.1.0]: https://github.com/thomaschristory/catalyst-center-super-mcp/releases/tag/v0.1.0
