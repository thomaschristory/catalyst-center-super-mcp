# Catalyst Center Super MCP — Bootstrap Design

**Date:** 2026-05-25
**Status:** Approved (awaiting spec self-review and user sign-off)
**Scope:** Session 1 — sandbox auth verification, spec acquisition, repo scaffold. Stops before any real implementation of `loader.py`, `dispatcher.py`, `auth.py`, `tools.py`.

---

## 1. Project context

Sibling of [`catalyst-sdwan-super-mcp`](https://github.com/thomaschristory/catalyst-sdwan-super-mcp). Same architecture (dynamic OpenAPI → MCP tool registration, adaptive splitting, RO/RW gate, etc.) targeting Cisco Catalyst Center (formerly DNA Center) instead of Catalyst SD-WAN Manager. See `CATALYST_CENTER_BOOTSTRAP.md` in the repo root for the full reuse/swap table.

The reference repo at `/Users/thomas/python/catalyst-sdwan-super-mcp/` is read-only for this work.

## 2. Decisions

| Topic | Decision |
|---|---|
| Package / CLI name | `catalyst_center_mcp` / `catalyst-center-mcp` |
| Bundled spec versions | `2.3.7.9` and `3.1.3` |
| Default bundled version | TBD — picked after spec diff, anchored on whatever `sandboxdnac.cisco.com` runs |
| Spec source | DevNet portal download (canonical OpenAPI JSON per major version) |
| `max_actions_per_tool` default | `80` |
| Response envelope | Pass through `{response, version}` verbatim |
| Async task polling | Pass through `{taskId}` verbatim — LLM orchestrates polling. `_await_task` reserved-param seam documented for future dispatcher addition. |
| Token refresh | Reactive only — refresh on `401` |
| Default mode | Read-only; `--read-write` flag opts in |
| `.env.example` creds | Blank placeholders, comment pointing to DevNet sandbox page |
| Env var prefix | `CATALYST_CENTER_*` (no `CC_` shorthand) |
| GitHub home | `github.com/thomaschristory/catalyst-center-super-mcp` (repo not created in this session) |
| License | MIT |
| Git remote / push | None this session; local `git init` only |

## 3. Session deliverables

1. **Sandbox auth findings doc** — `docs/superpowers/findings/2026-05-25-sandbox-auth.md`. Curl probes of token endpoint, authenticated GET, and a deliberate 401. Confirms or corrects the bootstrap doc's assumptions before any code is written.
2. **Spec acquisition** — `specs/2.3.7.9/` and `specs/3.1.3/` populated with the DevNet OpenAPI JSON.
3. **Spec diff report** — `docs/superpowers/findings/2026-05-25-spec-diff.md`. Throwaway script (no committed code) produces op counts, per-tag deltas, added/removed paths, breaking-change scan, and a default-version recommendation.
4. **Repo scaffold** — `pyproject.toml`, `catalyst_center_mcp/` package with stub modules, `config.yaml`, `.env.example`, `tests/` skeleton, `docs/` skeleton, `Dockerfile`, `docker-compose.yml`, `mkdocs.yml`, `.github/workflows/{ci,release,docs}.yml`, `LICENSE`, `README.md`, `CHANGELOG.md`, `CLAUDE.md`, `AGENTS.md`.

**Explicitly out of scope this session:** any real body of `auth.py`, `loader.py`, `dispatcher.py`, `tools.py`; `gh repo create`; any git push; integration tests; real test fixtures.

## 4. Component map

**Convention:** "Adapt (stub body)" and "Verbatim port (stub body)" both mean the same thing this session — the file is created with the imports, module docstring, and exported symbol names taken from the sdwan analogue (or rewritten from scratch for `auth.py`), but the function/method bodies raise `NotImplementedError` per §8. Only `__init__.py`, `pyproject.toml`, `config.yaml`, `.env.example`, `Dockerfile`, `docker-compose.yml`, workflows, docs, and tests get real content this session.

| File / area | Treatment | Notes |
|---|---|---|
| `pyproject.toml` | Adapt from sdwan | Swap name, script entry point, URLs. Same deps. |
| `catalyst_center_mcp/__init__.py` | New, trivial | Version constant. |
| `catalyst_center_mcp/cli.py` | Adapt (stub body) | CLI name swap; argparse flags identical. |
| `catalyst_center_mcp/config.py` | Adapt (stub body) | Drop vManage-specific keys. |
| `catalyst_center_mcp/auth.py` | Rewrite from scratch (stub body) | Single flow: Basic → token → `X-Auth-Token`. No JWT/session dual mode. |
| `catalyst_center_mcp/loader.py` | Verbatim port (stub body) | Splitter + action-name derivation unchanged. |
| `catalyst_center_mcp/dispatcher.py` | Port + tweak (stub body) | Add `offset`/`limit` to pagination param-name list. `_await_task` seam documented. |
| `catalyst_center_mcp/tools.py` | Verbatim port (stub body) | MCP tool registration is product-agnostic. |
| `catalyst_center_mcp/diff.py` | Verbatim port (stub body) | Bundled-spec-version comparator. |
| `catalyst_center_mcp/server.py` | Adapt (stub body) | fastmcp transport wiring. |
| `config.yaml` | New | See §5. |
| `.env.example` | New | See §6. |
| `Dockerfile`, `docker-compose.yml` | Adapt | Rename volume mount path. |
| `mkdocs.yml`, `docs/**` | Adapt | Skeleton only this session. |
| `.github/workflows/*` | Verbatim | Lint/test/build/publish. |
| `tests/conftest.py` | Stub | `minimal_spec` fixture raises `pytest.skip` until loader exists. |
| `tests/test_smoke.py` | New | Asserts every module imports. |
| `LICENSE`, `CHANGELOG.md`, `README.md`, `CLAUDE.md`, `AGENTS.md` | New / adapt | MIT, empty changelog, v0.1.0-stub README, CLAUDE.md carries architecture + gates sections (no qorexdevs, no issue history). |

## 5. `config.yaml` initial contents

```yaml
catalyst_center:
  base_url: https://sandboxdnac.cisco.com
  verify_ssl: true
  api_version: TBD-after-spec-diff   # pin to whatever sandboxdnac runs
  spec_dir: specs

server:
  read_write: false
  max_actions_per_tool: 80
  transport: stdio
  host: 127.0.0.1
  port: 8765

pagination:
  auto_follow: true
  max_pages: 20
  default_limit: 100
```

## 6. `.env.example` initial contents

```bash
# Catalyst Center connection
# DevNet always-on sandbox: https://developer.cisco.com/site/sandbox/
# Sandbox host: sandboxdnac.cisco.com  (creds rotate — verify on the sandbox page)
CATALYST_CENTER_BASE_URL=
CATALYST_CENTER_USERNAME=
CATALYST_CENTER_PASSWORD=
CATALYST_CENTER_VERIFY_SSL=true

# Server (optional overrides for config.yaml)
# CATALYST_CENTER_READ_WRITE=false
# CATALYST_CENTER_TRANSPORT=stdio
```

## 7. Target directory tree at end of session

```
catalyst-center-super-mcp/
├── .env.example
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── release.yml
│       └── docs.yml
├── .gitignore
├── AGENTS.md
├── CATALYST_CENTER_BOOTSTRAP.md
├── CHANGELOG.md
├── CLAUDE.md
├── Dockerfile
├── LICENSE
├── README.md
├── catalyst_center_mcp/
│   ├── __init__.py
│   ├── auth.py
│   ├── cli.py
│   ├── config.py
│   ├── diff.py
│   ├── dispatcher.py
│   ├── loader.py
│   ├── server.py
│   └── tools.py
├── config.yaml
├── docker-compose.yml
├── docs/
│   ├── architecture/
│   │   ├── overview.md
│   │   └── data-flow.md
│   ├── guides/
│   │   └── tool-splitting.md
│   └── index.md
├── docs/superpowers/
│   ├── specs/
│   │   └── 2026-05-25-catalyst-center-bootstrap-design.md
│   └── findings/
│       ├── 2026-05-25-sandbox-auth.md
│       └── 2026-05-25-spec-diff.md
├── mkdocs.yml
├── pyproject.toml
├── specs/
│   ├── 2.3.7.9/
│   │   └── catalyst-center-openapi.json
│   └── 3.1.3/
│       └── catalyst-center-openapi.json
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── test_smoke.py
```

## 8. Stub module shape

Every module written this session follows this pattern:

```python
"""<one-line module purpose>.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""

def <expected_entry_point>(*args, **kwargs):
    raise NotImplementedError("scaffold only — implement per design doc")
```

Each stub exports the symbols downstream modules will import (e.g. `auth.py` exports `CatalystCenterAuth`; `loader.py` exports `load_spec`, `Loader`). Signatures are read off the sdwan analogue — no invented APIs.

## 9. Sandbox auth findings doc shape

Sections in `docs/superpowers/findings/2026-05-25-sandbox-auth.md`:

1. **Probe commands** — exact curl invocations.
2. **Token endpoint** — URL, method, request headers, response status, response body (token redacted to first/last 8 chars), TTL hints if any.
3. **Auth header** — exact casing of `X-Auth-Token`, placement, behaviour when missing / malformed / expired.
4. **401 behaviour** — body shape, retry-hint headers, behaviour on replayed expired token.
5. **Deviations from bootstrap doc** — anything to update in `CATALYST_CENTER_BOOTSTRAP.md` before writing `auth.py`.
6. **Open questions** — anything the always-on sandbox can't answer about prod behaviour.

## 10. Spec diff doc shape

Sections in `docs/superpowers/findings/2026-05-25-spec-diff.md`:

1. **Source URLs, download timestamps, file sizes** for both versions.
2. **Top-line counts** — total ops, per HTTP method, unique tags, unique path prefixes, operationId overlap %.
3. **Per-tag op-count delta** table, sorted by absolute delta desc.
4. **Added paths** (3.1.3 only) — first 50, `... N more`.
5. **Removed paths** (2.3.7.9 only) — same.
6. **Breaking-change scan** — auth endpoint identical? pagination param names unchanged? response envelope key unchanged?
7. **Recommendation** — default version for `config.yaml`. Anchor on the sandbox version with a caveat if it diverges from newest.

## 11. Testing scope this session

- `tests/conftest.py`: `minimal_spec` fixture returns `{}` and raises `pytest.skip("scaffold only")`. Real content waits until `loader.py` has a body.
- `tests/test_smoke.py`: imports every module, asserts importable. Catches syntax errors in the scaffold.
- No integration tests, no respx mocks, no sandbox-hitting tests.

## 12. CI gates this session

- `ruff check`
- `ruff format --check`
- `pytest`
- `uv build`

All four must pass on the empty scaffold. No `mypy`/`pyright` yet — matches sdwan, defers until real code exists. Docker build runs in CI without push.

## 13. Explicit non-goals

- No `gh repo create`, no `git push`.
- No real bodies in `loader.py` / `dispatcher.py` / `auth.py` / `tools.py`.
- No invented endpoint behaviour. If sandbox probe contradicts the bootstrap doc, the findings doc is updated and the session stops at the checkpoint, not "fixing" `auth.py`.
- No carry-over of sdwan's qorexdevs incident note, issue history, or milestones.
- No `api_version` default chosen until the spec diff recommends one.

## 14. End-of-session checkpoint

Hand back to the user with:

- This scaffold tree on disk.
- `docs/superpowers/findings/2026-05-25-sandbox-auth.md` populated.
- `docs/superpowers/findings/2026-05-25-spec-diff.md` populated with a default-version recommendation.
- Local `git init` only — no remote, no push, no PR.

Next session picks up by filling in `auth.py` first (cheapest to verify against the sandbox), then `loader.py` against the bundled specs, then `dispatcher.py`, then `tools.py`.
