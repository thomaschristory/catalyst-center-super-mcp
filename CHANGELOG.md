# Changelog

All notable changes to catalyst-center-super-mcp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — v0.3.0 (in progress)

Tracking PRs land against the [v0.3.0 milestone](https://github.com/thomaschristory/catalyst-center-super-mcp/milestone/2).

### Added
- **`catalyst-center-mcp fetch <version>` / `--all-known`** — download specs without starting the server. (PR #13)
- **`catalyst-center-mcp list-versions`** — enumerate known + on-disk versions offline. (PR #13)
- **`catalyst-center-mcp discover-versions`** *(experimental)* — diff DevNet's docs page against `KNOWN_SPEC_URLS`. The live DevNet page is currently JS-only, so this command exits 2 against the real URL; the parser is forward-compatible if Cisco publishes static markup again. Helper only — does not mutate the hardcoded table. (PR #17)
- **`milestone-rollover.yml` workflow** — closes the just-tagged milestone, opens the next-patch one. Triggers on tag push. (PR #15)
- **Focused `tests/test_retry.py`** — jitter bounds, backoff cap, network-exception retry semantics, exhaustion outcome. (PR #14)

### Changed (behavior — read this if you upgrade)
- The default config filename is now `catalyst-center-mcp.yaml` (was `config.yaml`).
  The server still loads `config.yaml` with a stderr DEPRECATION warning if the
  new name is absent and `--config` was not explicit. The legacy fallback is
  slated for removal in v0.4.0. To migrate: `mv config.yaml catalyst-center-mcp.yaml`.
  (PR #12)

### Documentation
- PyPI Trusted Publisher setup documented in `docs/contributing/release-process.md`. The `v0.3.0` tag push is the first live exercise. (PR E)

## [0.2.0] — 2026-05-26

Hardening release. Resolves the v0.1.0 deferred items that materially affect
day-to-day usage, and locks down the CI supply chain.

### Added
- **Cross-tool action-name disambiguation.** Within a tool, action names that
  collide are now deduped by appending the operation's parent path segment
  (e.g. `get_devices_count__network_device`) instead of the previous
  numeric `_2`, `_3`, … suffix. Names are now stable across spec releases as
  long as the path is stable. **Breaking-ish:** if you scripted against the
  previous numeric form, `get_devices_count` is gone — the canonical name is
  `get_devices_count__network_device`. The tool description still lists every
  action with `(METHOD path)` so you can find the new name. (PR #9)
- **Proactive JWT-based token refresh.** `CatalystCenterAuth` now parses the
  JWT's `exp` claim on login, exposes `expires_in` and `needs_refresh()`, and
  the dispatcher refreshes 60s before expiry under an `asyncio.Lock`
  (single-flight). Reactive 401 re-auth is kept as a fallback. (PR #8)
- **Real DevNet spec auto-fetcher.** The `fetcher/` module now has a working
  implementation backed by a hardcoded `KNOWN_SPEC_URLS` table. New
  exceptions: `SpecVersionUnknownError`, `SpecContentInvalidError`. (PR #7)
- **`auto_fetch: true` by default.** `config.yaml` ships with auto-fetch
  enabled; bundled specs are still preferred when present, so this is a
  no-op for users with the repo's `specs/` tree mounted.
- **CI supply-chain hardening.** Every third-party GitHub Action used by this
  repo is now pinned to a full 40-char commit SHA with a trailing
  `# <tag>` comment, per CLAUDE.md's security posture. This applies to
  `actions/checkout`, `astral-sh/setup-uv`, `actions/upload-pages-artifact`,
  `actions/deploy-pages`, `actions/upload-artifact`, `actions/download-artifact`,
  `pypa/gh-action-pypi-publish`, `docker/setup-buildx-action`,
  `docker/build-push-action`, and `dependabot/fetch-metadata`. Going forward,
  Dependabot's `github-actions` ecosystem bumps will show as SHA→SHA diffs
  (intentional, not a regression).

### Changed
- `astral-sh/setup-uv` v7.5.0 → **v8.1.0** (Dependabot #3, accepted).
- `docker/setup-buildx-action` v3 → **v4** (Dependabot #6, accepted).
- `dependabot/fetch-metadata` v2 → **v3** (Dependabot #4, accepted; the v3
  release's only breaking change is the Node 24 runtime requirement, which
  GitHub-hosted runners already satisfy).
- `actions/checkout` in `release.yml:50` brought in line with the rest of the
  repo at v6 (was v4, leftover from the bootstrap).

### Held / deferred
- `actions/download-artifact` v4 → v8 (Dependabot #2) **held**. v8 introduces
  breaking changes (ESM, default-error on digest mismatch) and the paired
  `actions/upload-artifact` has no v8 yet — latest is v7.0.1. Moving them
  together is the safe path; reopen in v0.3.0.

### Deferred to v0.3.0+
- Task-poll helper (`_await_task` reserved-param seam).
- JWT signature verification (today we trust the `exp` claim from the token
  we just received over TLS, which is sufficient for a TTL hint).
- Sandbox-integration CI job (today's CI covers unit/mock paths only).
- Schema-aware parameter validation in the dispatcher.
- fastmcp 4.x migration.

[0.2.0]: https://github.com/thomaschristory/catalyst-center-super-mcp/releases/tag/v0.2.0

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
