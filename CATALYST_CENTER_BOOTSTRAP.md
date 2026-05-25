# Bootstrap: catalyst-center-super-mcp

A sibling project to [`catalyst-sdwan-super-mcp`](https://github.com/thomaschristory/catalyst-sdwan-super-mcp).
Same architecture, different Cisco product (Catalyst Center, formerly DNA Center).
Hand this doc to a fresh Claude session along with the sdwan repo as a reference.

---

## What to reuse verbatim

These design decisions carry over with **no changes** — they are not vManage-specific:

- **No codegen.** Load OpenAPI spec at startup, register MCP tools dynamically. Upgrading = drop a new spec folder + bump one config line.
- **Adaptive tool splitting** (`loader.py::_split_section` + `_split_by_path`). Section → sub-tag → URL path depth 3/4/5, with `<4`-op buckets collapsed into `<parent>_misc`. Config knob: `max_actions_per_tool` (default 150).
- **Action-name derivation** from `(method, path, tag)`, not the spec's `operationId`. Same rationale as sdwan — Cisco renames operationIds across minor releases.
- **`(action: str, params: dict)` tool shape.** One MCP tool per group; description enumerates actions and their params.
- **RO/RW gate at startup** (`--read-write` flag). Write tools are not registered in RO mode — never visible to the LLM.
- **Two-index lookup** (`by_action_name` for dispatch, `by_operation_id` for `--diff`).
- **Hybrid auto-follow + cursor pagination** (config-driven defaults, `_*` reserved params for per-call overrides, always wrap responses when pagination ran).
- **Dispatcher retry** on session expiry (re-auth + retry once) and transient HTTP failures.
- **Transports:** stdio / sse / streamable-http via the same CLI flags.
- **Docker:** volume-mounted specs, multi-stage `uv`-based build.
- **Stack:** Python ≥ 3.11, fastmcp, httpx, pyyaml, pytest+respx, ruff, mkdocs-material.

When in doubt, copy the file from `catalyst-sdwan-super-mcp/` and adjust only the swap-points below.

---

## What to swap per product

| Concern | sdwan value | Catalyst Center value |
|---|---|---|
| Product name | Cisco Catalyst SD-WAN Manager (vManage) | Cisco Catalyst Center (formerly DNA Center) |
| Package name | `sdwan_mcp` | `catalyst_center_mcp` (or `cc_mcp`) |
| CLI script | `sdwan-mcp` | `catalyst-center-mcp` |
| Default sandbox host | `sandbox-sdwan-2.cisco.com` | `sandboxdnac.cisco.com` (always-on, no reservation) |
| API base path | `/dataservice/...` | `/dna/intent/api/v1/...` (most ops) + `/dna/system/api/v1/...` (system) |
| Auth endpoint | `POST /j_security_check` (JWT or session) | `POST /dna/system/api/v1/auth/token` (Basic Auth → returns JWT) |
| Auth header | `Authorization: Bearer {token}` + `X-XSRF-TOKEN` | `X-Auth-Token: {token}` |
| Token lifetime | ~30 min, refresh proactively | 1 hour by default; refresh on 401 |
| Cookie handling | httpx jar manages `JSESSIONID` | none — pure header auth |
| Spec source | DevNet vmanageapi YAML, one file per version | DevNet Catalyst Center API spec (check format — likely OpenAPI 3.0 JSON) |
| Bundled versions | 20.15, 20.16, 20.18 | TBD — start with the latest published (2.3.7.x family) |
| Default version | 20.18 | TBD |

---

## Catalyst Center auth flow (confirm before coding)

Best current understanding — **verify against live sandbox before writing `auth.py`**:

```
POST https://{host}/dna/system/api/v1/auth/token
  Authorization: Basic base64(username:password)
  →  200 { "Token": "eyJ...", "message": "" }

Subsequent requests:
  X-Auth-Token: {Token}
```

Token expiry: exactly 3600s (verified from JWT exp/iat claims on the always-on sandbox). No refresh endpoint — re-POST the auth endpoint on 401.

No XSRF, no cookie jar, no separate JWT-vs-session modes. Auth is meaningfully **simpler** than vManage — strip the dual-mode logic in `auth.py` down to a single flow.

Verification steps before committing the auth module:

1. Hit the sandbox: `curl -u devnetuser:Cisco123! -X POST https://sandboxdnac.cisco.com/dna/system/api/v1/auth/token`
2. Confirm response shape and header name (case sensitivity matters — Cisco docs say `X-Auth-Token`).
3. Confirm 401 behaviour when token is stale.

DevNet sandbox creds (always-on, public): `devnetuser` / `Cisco123!` — but **always re-check on the sandbox catalog page** as Cisco rotates these.

---

## Spec acquisition

vManage specs are bundled in this repo under `specs/{version}/`. For Catalyst Center:

1. Source: DevNet Catalyst Center API reference + the downloadable OpenAPI spec (Cisco publishes one per major version).
2. Likely JSON, not YAML. The loader already accepts `.json` — no code change needed.
3. Caveat: Cisco sometimes splits the Catalyst Center spec into multiple files by domain (Sites, Devices, SDA, Wireless, etc.). The loader already merges `*.{yaml,yml,json}` in name order — should Just Work.
4. Verify operation count after first load. vManage 20.18 RW = ~1500 ops → 360 tools at default cap. Catalyst Center is smaller (rough order: 400–600 ops). May want a **lower** `max_actions_per_tool` default (e.g. 80) since the spec is smaller and finer-grained splitting will still produce a reasonable tool count.

---

## Things that will probably differ in non-obvious ways

Flagging these so the next session goes in eyes-open rather than assuming sdwan parity:

- **Pagination conventions.** vManage uses `count`/`startId` on some endpoints. Catalyst Center commonly uses `offset` + `limit`. The pagination detector in `dispatcher.py` looks at param *names* at spec-load time — extend the name list, don't rewrite the strategy.
- **Async/task endpoints.** Catalyst Center has many endpoints that return `{"response": {"taskId": "..."}, "version": "..."}` and require polling `/dna/intent/api/v1/task/{taskId}`. Consider whether a generic "follow task to completion" helper belongs in the dispatcher or stays an LLM-orchestrated multi-call (likely the latter — don't bake product workflow into the dispatcher).
- **Response envelope.** Catalyst Center wraps most responses in `{"response": ..., "version": ...}`. Decide early: unwrap in the dispatcher (cleaner LLM-facing JSON) or pass through (more honest, less surprising on edge cases). I'd default to pass-through and let the LLM see the envelope.
- **Tag taxonomy.** vManage tags are deep and noisy (`Configuration - Feature Profile - SDWAN - Transport - ...`). Catalyst Center tags are flatter (`Devices`, `Sites`, `SDA`, `Wireless`). The adaptive splitter handles both shapes — but the `max_actions_per_tool` sweet spot will differ. Tune after first load.
- **No DevNet-sandbox-specific quirks.** vManage has the `welcome.html` 302 expiry tell. Catalyst Center auth failures are plain 401 — simpler.

---

## Repo bootstrap checklist

For the agent picking this up:

1. `git clone` the sdwan repo as a reference. Don't fork — start fresh so the history is clean.
2. Create `catalyst-center-super-mcp` from scratch using the sdwan structure as a template.
3. Copy + rename: `sdwan_mcp/` → `catalyst_center_mcp/`. Adjust imports, CLI names, config keys.
4. Rewrite `auth.py` from scratch (don't port the JWT+session dual flow — it's the wrong shape).
5. Port `loader.py`, `dispatcher.py`, `tools.py`, `diff.py` largely as-is. Adjust:
   - Pagination param-name list in `dispatcher.py`.
   - Spec path conventions in `loader.py` if Cisco changes the path-template syntax.
6. Drop the latest Catalyst Center OpenAPI spec(s) into `specs/{version}/`.
7. Build the test fixture (`tests/conftest.py`) with a minimal Catalyst Center-shaped spec — auth response, one GET, one POST, one paginated endpoint.
8. Carry over CI workflows, docs structure, Docker setup, branch protection rules verbatim.
9. Verify against the sandbox end-to-end before opening v0.1.0.

---

## What to read first in the sdwan repo

In rough order of "highest signal for the port":

1. `CLAUDE.md` — full architecture, decisions log, and the security/contribution gates section. Mostly carries over.
2. `sdwan_mcp/loader.py` — the splitting algorithm and action-name derivation. Read end-to-end; it's the core of the project.
3. `sdwan_mcp/dispatcher.py` — request dispatch, pagination, retry. Mostly portable.
4. `sdwan_mcp/auth.py` — read to understand the *shape* of the auth module, then throw it away and write a simpler one.
5. `docs/guides/tool-splitting.md` — worked example of the splitter behaviour. The narrative carries over; the numbers will differ.
6. `docs/architecture/{overview,data-flow}.md` — same story, swap product names.

Don't bother copying issue history, milestones, or the qorexdevs incident note — those are sdwan-specific.
