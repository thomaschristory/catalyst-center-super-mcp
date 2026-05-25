# CLAUDE.md — catalyst-center-super-mcp

## Project goal

A FastMCP server that exposes the Cisco Catalyst Center REST API
as MCP tools, with dynamic spec loading so it stays in sync as the API evolves
across versions. No codegen — everything is derived from the upstream OpenAPI
spec.

Public repo: <https://github.com/thomaschristory/catalyst-center-super-mcp>.
Docs: <https://thomaschristory.github.io/catalyst-center-super-mcp/>.

---

## Bootstrap status

This repo was scaffolded on **2026-05-25** per [`docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md`](docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md). All code modules in `catalyst_center_mcp/` are `NotImplementedError` stubs until a follow-up session implements them. Smoke test (`tests/test_smoke.py`) is the only behavior currently verified. See [`docs/superpowers/findings/2026-05-25-sandbox-auth.md`](docs/superpowers/findings/2026-05-25-sandbox-auth.md) for sandbox-confirmed auth flow that `auth.py` should implement.

---

## Stack

- **Python** ≥ 3.11 (CI: 3.11, 3.12, 3.13 on Linux + macOS)
- **Packaging:** `pyproject.toml` (hatchling), managed with `uv`
- **MCP framework:** `fastmcp`
- **HTTP client:** `httpx` (async)
- **Config parsing:** `pyyaml` + `python-dotenv`
- **Tests:** `pytest`, `respx` (HTTP mocks), `pytest-asyncio`
- **Lint / format:** `ruff`
- **Docs:** `mkdocs-material`, deployed to GitHub Pages

Setup:

```bash
uv sync --group dev --group docs
uv run catalyst-center-mcp --help
```

---

## Architecture

### No code generation — dynamic loading

The server reads the OpenAPI spec at startup and registers MCP tools dynamically.
Upgrading to a new Catalyst Center version = drop a new spec folder + change one config line.

### Supported Catalyst Center versions

**2.3.7.9 and 3.1.3.** The repo ships specs for both versions; 3.1.3 is the default.

### Adaptive tool splitting

Cisco's spec has thousands of operations. A single tool per section would push
the description payload past most clients' per-tool budgets. The loader splits
adaptively based on a size cap:

- `catalyst_center_mcp.max_actions_per_tool: 80` (default; `0` disables splitting).
- Algorithm: **section → if over cap, split by sub-tag → if a sub-tag is still
  over cap, recurse on URL path segments at depth 3, 4, 5**.
- Sibling sub-tags with `<4` operations collapse into a single `<parent>_misc`
  tool to avoid a long tail of tiny tools.
- Buckets still over the cap at depth 5 (or oversized `_misc` umbrellas) emit a
  WARNING but are still registered.

Full algorithm, worked example, and tool-count tables live in
[docs/guides/tool-splitting.md](docs/guides/tool-splitting.md).

### Tool shape

```
tool name:    group slug  (e.g. network_discovery, site_design)
description:  lists all actions with their params, built from the spec
args:
  action:     str — a derived stable name like get_device_list; NOT Cisco's operationId
  params:     dict — keys/values vary by action, documented in description
```

Action names come from `(HTTP method, URL path, OpenAPI tag)`, deduped within a
tool. Cisco's `operationId` is preserved on `OperationSpec` as a back-reference
for the `--diff` utility but never reaches the user.

### Read-only by default

HTTP method filtering at startup:

- RO mode (default): registers GET endpoints only
- RW mode (`--read-write` flag): registers GET + POST + PUT + DELETE + PATCH

The LLM never sees write tools in RO mode — they are not registered, not in context.

---

## Authentication

Catalyst Center uses a single token-based auth flow:

```
HTTP Basic  →  POST /dna/system/api/v1/auth/token
→ { token: "..." }

Subsequent requests:
  X-Auth-Token: {token}
```

Token is refreshed proactively when within 2 minutes of expiry.

No cookie jar, no dual-mode — a single flow applies to all supported versions.

---

## Project structure

```
catalyst-center-super-mcp/
  catalyst_center_mcp/            source package
    __init__.py               version
    server.py                 entrypoint, CLI, async pre-flight
    config.py                 config.yaml loader + ${ENV} interpolation
    auth.py                   HTTP Basic → token login, refresh
    loader.py                 spec loading, adaptive splitting (section/sub-tag/path), RO/RW filter, action-name derivation, indexing
    dispatcher.py             httpx client, param routing, retry on token expiry + transient HTTP failures
    tools.py                  dynamic MCP tool registration
    diff.py                   version diff utility
  tests/                      pytest suite (test_loader, test_dispatcher, test_diff, test_config)
    conftest.py               minimal OpenAPI spec fixture
  docs/                       mkdocs-material site
    index.md
    getting-started/{install,first-run,sandbox}.md
    guides/{mcp-clients,read-write,tool-splitting,spec-versions,docker}.md
    reference/{cli,configuration,authentication}.md
    architecture/{overview,data-flow}.md
    contributing/{development,release-process}.md
  specs/                      OpenAPI documents, one folder per version
    2.3.7.9/                  ← bundled
    3.1.3/                    ← bundled (default; matches DevNet sandbox)
  .github/
    workflows/{lint,test,docs,docker,release}.yml
    ISSUE_TEMPLATE/{bug,feature}.yml
    dependabot.yml
  scripts/                    helper scripts (currently empty placeholder)
  pyproject.toml              project + ruff + mypy + pytest config
  mkdocs.yml
  Dockerfile                  multi-stage, uv-based
  docker-compose.yml          SSE on :8000 by default
  config.yaml                 default config — points at DevNet sandbox
  .env.example
  CHANGELOG.md
  LICENSE                     Apache-2.0
  README.md
  CLAUDE.md                   this file
```

`specs/{version}/` accepts `*.yaml`, `*.yml`, and `*.json` files — they are merged
in name order.

---

## Config file

```yaml
# config.yaml
catalyst_center:
  host: sandboxdnac.cisco.com   # DevNet sandbox by default
  port: 443
  verify_ssl: false
  username: "${CATALYST_CENTER_USERNAME}"
  password: "${CATALYST_CENTER_PASSWORD}"

catalyst_center_mcp:
  specs_dir: ./specs
  active_version: "3.1.3"
  max_actions_per_tool: 80          # default; 0 disables splitting (see docs/guides/tool-splitting.md)
  pagination:
    enabled: true                   # master switch for auto-follow
    max_pages: 5                    # cap on stitched pages per call
    page_size: null                 # offset-style override; null = endpoint default

transport:
  mode: stdio                       # stdio | sse | streamable-http
  host: 127.0.0.1
  port: 8000
```

---

## CLI flags

```bash
catalyst-center-mcp                                          # stdio, RO, version from config
catalyst-center-mcp --transport sse --port 8000              # SSE transport
catalyst-center-mcp --transport streamable-http              # streamable HTTP
catalyst-center-mcp --read-write                             # enable mutations
catalyst-center-mcp --version 2.3.7.9                        # override spec version
catalyst-center-mcp --max-actions-per-tool 50                # smaller, more numerous tools
catalyst-center-mcp --diff 2.3.7.9 3.1.3                     # diff two versions and exit
catalyst-center-mcp --config /path/to/config.yaml            # custom config file
```

The `catalyst-center-super-mcp` script name is also registered if you prefer the long form.

---

## Docker

```bash
# Build
docker build -t catalyst-center-super-mcp .

# Claude Desktop (stdio) — specs mounted from host
docker run -i --rm \
  -e CATALYST_CENTER_USERNAME=devnetuser \
  -e CATALYST_CENTER_PASSWORD='your_password' \
  -v "$(pwd)/specs:/app/specs" \
  catalyst-center-super-mcp

# SSE (network-accessible)
docker run -p 8000:8000 \
  -e CATALYST_CENTER_USERNAME=devnetuser \
  -e CATALYST_CENTER_PASSWORD='your_password' \
  -v "$(pwd)/specs:/app/specs" \
  catalyst-center-super-mcp --transport sse --host 0.0.0.0 --port 8000

# Via docker-compose (SSE by default)
docker compose up -d
```

Specs are always mounted as a volume — never baked into the image — so you can
upgrade Catalyst Center versions without rebuilding.

---

## Data flow

### Startup

```
server.py (async pre-flight)
  → config.py     reads config.yaml, interpolates env vars
  → loader.py     loads all *.{yaml,yml,json} from specs/{version}/
                  merges paths + schemas
                  filters by RO/RW flag
                  adaptively splits ops into ToolGroups
                    (section → sub-tag → URL path; see tool-splitting.md)
                  derives a stable action_name per op
                  builds flat action_name → op index (plus operation_id index for --diff)
  → auth.py       CatalystCenterAuth initialised with credentials
  → dispatcher.py httpx.AsyncClient created
  → dispatcher.connect()  → auth.login() → HTTP Basic → POST /dna/system/api/v1/auth/token → X-Auth-Token
  → tools.py      registers one fastmcp tool per group
  → mcp.run()     starts selected transport
```

### Tool call

```
LLM calls tool "network_discovery"
  → tools.py       receives { action: "get_device_list", params: {} }
                   validates action against the group's derived action_names
  → dispatcher.call("get_device_list", {})
  → dispatcher     looks up op via SpecIndex.by_action_name
                   resolves path template, splits query/body params
                   fires httpx request with X-Auth-Token header
                   on 401: re-auths, retries once
  → LLM            receives JSON response
```

### Shutdown

```
finally block in server.py
  → dispatcher.close()
    → client.aclose()
```

---

## Loader logic (loader.py)

1. `_load_and_merge()` — glob `specs/{version}/*.{yaml,yml,json}`, merge into one dict.
2. `_extract_operations()` — flatten paths/methods into `OperationSpec`s; each gets a
   stable `action_name` derived from `(method, path, tag)` via `_derive_action_name()`.
3. `_split_into_groups()` — RO/RW filter, then bucket ops by section. For each section,
   `_split_section()` decides whether to keep it as one tool or split by sub-tag.
   Over-cap sub-tags fall through to `_split_by_path()`, which recurses on URL path
   segments at depth 3, 4, 5. Sibling buckets with `<4` ops collapse to `<parent>_misc`.
4. `_dedupe_tool_names()` and `_dedupe_action_names()` ensure uniqueness within and
   across tools (appending `_2`, `_3`, … on collision).
5. `_build_index()` — two flat dicts: `by_action_name` (used by the dispatcher) and
   `by_operation_id` (used only by `--diff`).

RO/RW filter:

```python
RO_METHODS = {"get"}
RW_METHODS = {"get", "post", "put", "delete", "patch"}
```

---

## Dispatcher logic (dispatcher.py)

Lookup: `SpecIndex.by_action_name[action_name]` → `OperationSpec`. Cisco's
`operation_id` is not used here — it's only kept around for `--diff`.

Path param injection:

- spec path `/dna/intent/api/v1/network-device/{id}` + params `{"id": "10.0.0.1"}` → `/dna/intent/api/v1/network-device/10.0.0.1`
- remaining params routed to query string (GET) or JSON body (POST/PUT/PATCH)

Unknown params (not in spec): forwarded as query params with a warning log.

Token expiry detection: 401 response.
On expiry → `auth.login()` again → retry once.

---

## Diff utility (diff.py)

```bash
uv run catalyst-center-mcp --diff 2.3.7.9 3.1.3
```

Output:

```
=== Catalyst Center API Diff: 2.3.7.9 → 3.1.3 ===

REMOVED (breaking):
  - getNetworkDeviceList  [Network Discovery]  GET /dna/intent/api/v1/network-device

ADDED:
  + getNetworkDeviceById  [Network Discovery]  GET /dna/intent/api/v1/network-device/{id}

CHANGED (parameter drift):
  ~ listAllDevices  [Network Discovery]
      added: 'family' — query, string, optional
```

---

## Security & contribution gates

Public-repo posture (applies to `main` and to fork PRs from untrusted contributors).

### Branch protection on `main`

Configured via `gh api -X PUT repos/.../branches/main/protection`. Current state:

| Setting | Value | Why |
|---|---|---|
| `required_status_checks` | `lint`, `test (ubuntu-latest, 3.12)`, `strict: true` | Block merges where CI is red or stale relative to main. |
| `required_pull_request_reviews.required_approving_review_count` | **1** | No code lands on `main` without at least one approving review. Stops a hostile or low-quality PR from being silently merged. |
| `enforce_admins` | **false** | Solo-maintainer trade-off: admins can self-merge their own PRs (GitHub disallows self-approval). With `enforce_admins: true` + reviews=1 the maintainer would be locked out of merging anything alone. |
| `required_conversation_resolution` | true | Forces explicit "done" on every review comment. |
| `allow_force_pushes` / `allow_deletions` | false | Standard protection of `main` history. |
| `required_linear_history` | false | We don't insist on linear history; squash-merge of well-named PRs is fine. |

### Fork PR workflow approval (manual UI step)

GitHub does not expose this via REST API for public repos, so it must be set in the web UI:

> Repo → Settings → Actions → General → **Fork pull request workflows from outside collaborators** → choose **"Require approval for first-time contributors"** (recommended) or stricter.

This means a fork PR from a brand-new account won't even trigger CI until the maintainer clicks Approve, which kills a class of supply-chain noise (resource use, CI log scraping, and the ability to test workflow-injection attempts).

### Triggers that touch secrets

Only one workflow in the repo uses the dangerous `pull_request_target` trigger:

- `.github/workflows/dependabot-auto-merge.yml` — gated by `if: github.actor == 'dependabot[bot]'`, so a non-dependabot author cannot reach the privileged code path.

All other workflows (`lint.yml`, `test.yml`, `docker.yml`, `docs.yml`) use `pull_request`, which means fork PRs run in the restricted, no-secrets context. **Never switch any of these to `pull_request_target` without re-reading [Keeping your GitHub Actions secure: pwn requests](https://securitylab.github.com/research/github-actions-preventing-pwn-requests/).**

### Reviewing PRs from unknown contributors

For PRs from authors not previously known to the project:

1. Look at the author's GH profile: account age, repo mix (mostly forks?), event log pattern (drive-by `issue-N-*` branches across many unrelated repos?), commit-email vs. GH-name mismatch. These don't determine intent on their own, but raise the bar for review.
2. Adversarial diff scan: any new top-level imports, any `subprocess`/`exec`/`eval`, any new network calls, any `verify=False`, any logging that could echo `Authorization` / `X-Auth-Token`, any new workflow triggers (especially `pull_request_target`, `workflow_run`), any pre/post-install hooks in `pyproject.toml`.
3. For workflow file changes: confirm no new `secrets.*` access, no shell interpolation of `${{ github.event.* }}` fields without quoting, no new third-party action references without a pinned full-commit SHA.

A clean diff from a sketchy profile is still mergeable — but **never auto-merge from a first-time contributor**, even if all status checks pass.

---

## Key decisions log

| Decision | Choice | Reason |
|---|---|---|
| Language | Python ≥ 3.11 | Simpler local iteration, no build step |
| MCP framework | fastmcp | Minimal boilerplate |
| Packaging | hatchling + uv | Modern Python packaging, fast dependency resolution |
| Tool splitting | Size-driven adaptive splitter (`max_actions_per_tool`, default 80). Section → sub-tag → URL path (depth 3–5). | The earlier `section`/`tag` toggle was too coarse. A single size cap with recursive fallback adapts cleanly to the spec's actual shape without a mode switch. |
| Action names | Derived from `(method, path, tag)`, not Cisco's `operationId`. | Cisco renames operationIds between releases. Our user-facing action name stays stable across those renames. operationId remains on `OperationSpec` as a back-reference for `--diff`. |
| Supported versions | 2.3.7.9 and 3.1.3 | Matches DevNet sandbox and current GA release. |
| Params shape | `(action: str, params: dict)` | Scales with tag size; description documents per-action params |
| RO/RW | Flag at runtime | Safe default, explicit opt-in for mutations |
| Auth | HTTP Basic → POST `/dna/system/api/v1/auth/token` → `X-Auth-Token` | Single flow; matches actual Catalyst Center auth; no dual-mode needed |
| Spec versioning | Drop folder + config line | No codegen, easy upgrade path |
| Spec formats | YAML, YML, **and JSON** | We accept all three extensions for compatibility with however Cisco publishes each version. |
| Transport | Flag at runtime | stdio for local, SSE/HTTP for remote/tunneled |
| Docker | Volume-mounted specs | Upgrade specs without rebuilding image |
| Pagination strategy | Hybrid auto-follow + cursor | Common case "just works"; truncation honest, resumable. |
| Pagination knobs | Config defaults + `_*` reserved params | Server-wide default, per-call override without bloating action params. |
| Pagination response shape | Always wrap when paginated (`{data, pagination}`) | Predictable signal to LLM that auto-follow ran. |
| Pagination detection | Spec-load time from param names | Cheap, deterministic; response sanity-check covers drift. |
| License | Apache-2.0 | Consistent with sibling repo `catalyst-sdwan-super-mcp`. |
