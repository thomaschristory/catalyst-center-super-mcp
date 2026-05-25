# Catalyst Center MCP — Session 1 Bootstrap Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify the Catalyst Center sandbox auth flow with curl, acquire OpenAPI specs for versions 2.3.7.9 and 3.1.3 from DevNet, and scaffold the `catalyst-center-super-mcp` repository with stub modules so CI gates (ruff + pytest + uv build) pass on an empty project. **Stop before implementing any real body of `auth.py`, `loader.py`, `dispatcher.py`, or `tools.py`.**

**Architecture:** Mirror the `catalyst-sdwan-super-mcp` repo layout one-to-one (sibling project). Every code module is created as a typed `NotImplementedError` stub this session; the only real content is in config files, build/CI plumbing, docs skeleton, smoke test, and findings docs. A throwaway script — never committed — produces the spec diff.

**Tech Stack:** Python 3.11+, fastmcp ≥ 2.0, httpx ≥ 0.27, pyyaml ≥ 6.0, python-dotenv ≥ 1.0; ruff for lint, pytest + respx for tests, mkdocs-material for docs; uv as the build/install driver; Docker multi-stage with the official `ghcr.io/astral-sh/uv` image.

**Spec reference:** `docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md` (locked at commit `8efddc8`).

**sdwan reference repo:** `/Users/thomas/python/catalyst-sdwan-super-mcp/` — **read-only**. Copy patterns out, never modify.

---

## Phase A: Sandbox auth verification

### Task 1: Probe Catalyst Center sandbox auth and write findings doc

**Files:**
- Create: `docs/superpowers/findings/2026-05-25-sandbox-auth.md`

**Context:** Bootstrap doc assumes `POST /dna/system/api/v1/auth/token` with Basic auth returns `{"Token": "..."}` and subsequent requests use header `X-Auth-Token`. Verify before any code is written. Always-on sandbox: `sandboxdnac.cisco.com`. Public creds per DevNet sandbox catalog (currently `devnetuser` / `Cisco123!` but Cisco rotates — verify at https://devnetsandbox.cisco.com/ first).

- [ ] **Step 1: Confirm current sandbox creds**

Open https://devnetsandbox.cisco.com/ in a browser, search for "Catalyst Center", click the always-on sandbox card. Note the host, username, password shown on that page. If they differ from `sandboxdnac.cisco.com` / `devnetuser` / `Cisco123!`, use the live values in the curl commands below.

- [ ] **Step 2: Probe the token endpoint**

Run:

```bash
curl -k -sS -o /tmp/cc_token.json -w "HTTP %{http_code}\nContent-Type: %{content_type}\n" \
  -u devnetuser:Cisco123! \
  -X POST https://sandboxdnac.cisco.com/dna/system/api/v1/auth/token
echo "---"
cat /tmp/cc_token.json | python3 -m json.tool
```

Expected: HTTP 200, JSON body containing a `Token` key (verify exact casing). Note the token length and prefix. If status is 401/403, recheck creds from Step 1. If it's a redirect or HTML page, the sandbox path may have changed — document this and stop.

- [ ] **Step 3: Probe an authenticated GET**

Use the token from Step 2:

```bash
TOKEN=$(python3 -c "import json; print(json.load(open('/tmp/cc_token.json'))['Token'])")
curl -k -sS -o /tmp/cc_count.json -w "HTTP %{http_code}\n" \
  -H "X-Auth-Token: $TOKEN" \
  https://sandboxdnac.cisco.com/dna/intent/api/v1/network-device/count
echo "---"
cat /tmp/cc_count.json | python3 -m json.tool
```

Expected: HTTP 200, JSON body `{"response": <int>, "version": "<str>"}`. Confirms the `X-Auth-Token` header name and casing work, and that responses use the `{response, version}` envelope per the design.

- [ ] **Step 4: Probe a deliberate 401**

```bash
curl -k -sS -o /tmp/cc_401.json -D /tmp/cc_401_headers.txt -w "HTTP %{http_code}\n" \
  -H "X-Auth-Token: not-a-real-token" \
  https://sandboxdnac.cisco.com/dna/intent/api/v1/network-device/count
echo "--- body ---"
cat /tmp/cc_401.json
echo "--- headers ---"
cat /tmp/cc_401_headers.txt
```

Expected: HTTP 401. Note the response body shape and any `WWW-Authenticate` or retry-hint headers — `auth.py` will pattern-match on this in a future session.

- [ ] **Step 5: Write findings doc**

Create `docs/superpowers/findings/2026-05-25-sandbox-auth.md` with this content (substitute observed values from Steps 1–4; redact the token to first/last 8 chars):

```markdown
# Catalyst Center Sandbox Auth — Findings

**Probed:** 2026-05-25
**Host:** sandboxdnac.cisco.com
**Creds:** devnetuser / Cisco123!  (verified live at devnetsandbox.cisco.com)

## 1. Probe commands
<paste the four curl invocations from Steps 2–4>

## 2. Token endpoint
- URL: `POST https://sandboxdnac.cisco.com/dna/system/api/v1/auth/token`
- Auth: HTTP Basic
- Response status: 200
- Response body: `{"Token": "<8-char-prefix>...<8-char-suffix>"}`  (length: <N> chars)
- Token TTL hint: <none in response | header X-…: …>

## 3. Auth header
- Name: `X-Auth-Token` (exact casing — confirmed)
- Placement: request header on every authenticated call
- Behaviour: <observed from Step 3 + Step 4>

## 4. 401 behaviour
- Status: 401
- Body shape: <verbatim from /tmp/cc_401.json>
- Retry-hint headers: <list from /tmp/cc_401_headers.txt>
- Replay-after-expiry behaviour: <if testable, otherwise "untested in always-on sandbox">

## 5. Deviations from bootstrap doc
<list anything that contradicts CATALYST_CENTER_BOOTSTRAP.md; if nothing, write "None — bootstrap doc assumptions confirmed.">

## 6. Open questions
- Token TTL: bootstrap doc claims ~1 hour; not directly observable from a single probe.
- Prod-instance behaviour vs always-on sandbox: untested.
```

- [ ] **Step 6: If deviations found, update bootstrap doc**

If Step 5 lists deviations, edit `/Users/thomas/python/catalyst-center-super-mcp/CATALYST_CENTER_BOOTSTRAP.md` to match observed reality. Otherwise skip.

- [ ] **Step 7: Commit**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
git add docs/superpowers/findings/2026-05-25-sandbox-auth.md CATALYST_CENTER_BOOTSTRAP.md
git commit -m "docs: capture Catalyst Center sandbox auth probe results"
```

---

## Phase B: Spec acquisition

### Task 2: Download Catalyst Center 2.3.7.9 OpenAPI spec

**Files:**
- Create: `specs/2.3.7.9/catalyst-center-openapi.json`

**Context:** Cisco publishes the OpenAPI JSON under https://developer.cisco.com/docs/dna-center/ — typically a downloadable file per major version, sometimes behind a "Download" button that requires a free DevNet account. The download URL is not stable across versions, so this task is partially manual.

- [ ] **Step 1: Locate the 2.3.7.9 spec**

Open https://developer.cisco.com/docs/dna-center/ in a browser. Look for a version selector (top-right or sidebar) and choose 2.3.7.9. Click "Download" / "OpenAPI" / "API Spec" — Cisco's UI label varies. Save the JSON to `/tmp/cc-2.3.7.9.json`.

If the download is split into multiple files by domain (Sites, Devices, SDA, Wireless, …), download all of them into `/tmp/cc-2.3.7.9/`. The loader (in a later session) merges `*.{yaml,yml,json}` in name order, so multiple files are fine.

- [ ] **Step 2: Validate it's parseable JSON and looks like OpenAPI**

```bash
python3 -c "
import json, sys
data = json.load(open('/tmp/cc-2.3.7.9.json'))
assert 'openapi' in data or 'swagger' in data, 'not an OpenAPI doc'
print('openapi version:', data.get('openapi') or data.get('swagger'))
print('info.version:', data.get('info', {}).get('version'))
print('paths count:', len(data.get('paths', {})))
"
```

Expected: prints `openapi version: 3.x` (or `swagger: 2.0` for older specs), an `info.version` containing `2.3.7.9` (or similar), and a non-zero paths count. If any assertion fails, the file isn't what we want — retry Step 1.

- [ ] **Step 3: Drop into the repo**

```bash
mkdir -p /Users/thomas/python/catalyst-center-super-mcp/specs/2.3.7.9
cp /tmp/cc-2.3.7.9.json /Users/thomas/python/catalyst-center-super-mcp/specs/2.3.7.9/catalyst-center-openapi.json
# OR if multi-file:
# cp /tmp/cc-2.3.7.9/*.json /Users/thomas/python/catalyst-center-super-mcp/specs/2.3.7.9/
```

- [ ] **Step 4: Commit**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
git add specs/2.3.7.9/
git commit -m "specs: bundle Catalyst Center 2.3.7.9 OpenAPI spec from DevNet"
```

---

### Task 3: Download Catalyst Center 3.1.3 OpenAPI spec

**Files:**
- Create: `specs/3.1.3/catalyst-center-openapi.json`

**Context:** Same as Task 2 but for version 3.1.3.

- [ ] **Step 1: Locate the 3.1.3 spec**

Same browser flow as Task 2 Step 1 but select 3.1.3 in the version selector. Save to `/tmp/cc-3.1.3.json` (or `/tmp/cc-3.1.3/` if multi-file).

- [ ] **Step 2: Validate**

```bash
python3 -c "
import json
data = json.load(open('/tmp/cc-3.1.3.json'))
assert 'openapi' in data or 'swagger' in data
print('openapi version:', data.get('openapi') or data.get('swagger'))
print('info.version:', data.get('info', {}).get('version'))
print('paths count:', len(data.get('paths', {})))
"
```

Expected: same checks pass; `info.version` reflects 3.1.3.

- [ ] **Step 3: Drop into the repo**

```bash
mkdir -p /Users/thomas/python/catalyst-center-super-mcp/specs/3.1.3
cp /tmp/cc-3.1.3.json /Users/thomas/python/catalyst-center-super-mcp/specs/3.1.3/catalyst-center-openapi.json
```

- [ ] **Step 4: Commit**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
git add specs/3.1.3/
git commit -m "specs: bundle Catalyst Center 3.1.3 OpenAPI spec from DevNet"
```

---

### Task 4: Spec diff (throwaway script, no committed code)

**Files:**
- Create: `docs/superpowers/findings/2026-05-25-spec-diff.md`
- Temporarily create then delete: `/tmp/cc-spec-diff.py`

**Context:** Compare 2.3.7.9 and 3.1.3 to pick the default bundled version. Anchor the choice on whichever version the sandbox actually runs (smoke tests should match the default). Script is intentionally throwaway — `diff.py` in the package gets a real implementation in a later session and is more general.

- [ ] **Step 1: Write the throwaway diff script**

Write to `/tmp/cc-spec-diff.py`:

```python
"""One-off spec diff for the bootstrap session. Not committed."""
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path("/Users/thomas/python/catalyst-center-super-mcp")
A_PATH = REPO / "specs/2.3.7.9/catalyst-center-openapi.json"
B_PATH = REPO / "specs/3.1.3/catalyst-center-openapi.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def ops(spec: dict) -> list[tuple[str, str, str, list[str]]]:
    """Return (method, path, operationId, tags) tuples."""
    out = []
    for path, item in (spec.get("paths") or {}).items():
        for method, op in (item or {}).items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            out.append((
                method.upper(),
                path,
                (op or {}).get("operationId", ""),
                (op or {}).get("tags", []) or [],
            ))
    return out


def main() -> None:
    a, b = load(A_PATH), load(B_PATH)
    a_ops, b_ops = ops(a), ops(b)
    a_paths = {(m, p) for m, p, _, _ in a_ops}
    b_paths = {(m, p) for m, p, _, _ in b_ops}
    a_opids = {oid for _, _, oid, _ in a_ops if oid}
    b_opids = {oid for _, _, oid, _ in b_ops if oid}

    print(f"# Spec diff: 2.3.7.9 vs 3.1.3")
    print()
    print(f"## Top-line counts")
    print(f"- 2.3.7.9 ops: {len(a_ops)}  (paths: {len({p for _, p, _, _ in a_ops})})")
    print(f"- 3.1.3   ops: {len(b_ops)}  (paths: {len({p for _, p, _, _ in b_ops})})")
    print(f"- operationId overlap: {len(a_opids & b_opids)} of "
          f"{len(a_opids | b_opids)} ({100*len(a_opids & b_opids)/max(1,len(a_opids|b_opids)):.1f}%)")
    print()

    print("## Per-method counts")
    a_methods = Counter(m for m, _, _, _ in a_ops)
    b_methods = Counter(m for m, _, _, _ in b_ops)
    for m in sorted(set(a_methods) | set(b_methods)):
        print(f"- {m}: 2.3.7.9={a_methods[m]}  3.1.3={b_methods[m]}  delta={b_methods[m]-a_methods[m]:+}")
    print()

    print("## Per-tag op-count delta (sorted by abs delta desc)")
    a_tags = Counter(t for _, _, _, tags in a_ops for t in tags)
    b_tags = Counter(t for _, _, _, tags in b_ops for t in tags)
    rows = []
    for t in set(a_tags) | set(b_tags):
        rows.append((t, a_tags[t], b_tags[t], b_tags[t] - a_tags[t]))
    rows.sort(key=lambda r: abs(r[3]), reverse=True)
    print(f"| tag | 2.3.7.9 | 3.1.3 | delta |")
    print(f"|---|---:|---:|---:|")
    for t, ac, bc, d in rows[:30]:
        print(f"| `{t}` | {ac} | {bc} | {d:+} |")
    if len(rows) > 30:
        print(f"| _… {len(rows)-30} more rows omitted_ | | | |")
    print()

    added = sorted(b_paths - a_paths)
    removed = sorted(a_paths - b_paths)
    print(f"## Added in 3.1.3 ({len(added)} total)")
    for m, p in added[:50]:
        print(f"- `{m} {p}`")
    if len(added) > 50:
        print(f"- _… {len(added)-50} more_")
    print()
    print(f"## Removed in 3.1.3 ({len(removed)} total)")
    for m, p in removed[:50]:
        print(f"- `{m} {p}`")
    if len(removed) > 50:
        print(f"- _… {len(removed)-50} more_")
    print()

    print("## Breaking-change scan")
    AUTH_PATH = "/dna/system/api/v1/auth/token"
    a_auth = any(p == AUTH_PATH for _, p, _, _ in a_ops)
    b_auth = any(p == AUTH_PATH for _, p, _, _ in b_ops)
    print(f"- Auth endpoint `{AUTH_PATH}` present: 2.3.7.9={a_auth}  3.1.3={b_auth}")

    def pagination_param_names(spec_ops, full_spec):
        names = Counter()
        for _, path, _, _ in spec_ops:
            for method_obj in (full_spec.get("paths", {}).get(path, {}) or {}).values():
                if not isinstance(method_obj, dict):
                    continue
                for param in method_obj.get("parameters") or []:
                    n = (param or {}).get("name", "").lower()
                    if n in {"offset", "limit", "startindex", "count", "page", "pagesize", "starttime", "endtime"}:
                        names[n] += 1
        return names

    print(f"- 2.3.7.9 pagination param frequencies: {dict(pagination_param_names(a_ops, a))}")
    print(f"- 3.1.3   pagination param frequencies: {dict(pagination_param_names(b_ops, b))}")
    print()

    print("## Recommendation")
    print("_Pin `active_version` in config.yaml to whichever version the always-on sandbox runs,")
    print("so smoke tests match by default. Check the sandbox's API response `version` field")
    print("(visible in Task 1 Step 3) to decide._")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script and capture output**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
python3 /tmp/cc-spec-diff.py > docs/superpowers/findings/2026-05-25-spec-diff.md
```

- [ ] **Step 3: Edit the findings doc**

Open `docs/superpowers/findings/2026-05-25-spec-diff.md` and prepend a metadata block:

```markdown
# Catalyst Center Spec Diff — 2.3.7.9 vs 3.1.3

**Compared:** 2026-05-25
**Source A:** `specs/2.3.7.9/catalyst-center-openapi.json` (downloaded from DevNet)
**Source B:** `specs/3.1.3/catalyst-center-openapi.json` (downloaded from DevNet)
**Generated by:** `/tmp/cc-spec-diff.py` (not committed)

---

```

…then under the auto-generated `## Recommendation` section, fill in the actual choice based on the sandbox's reported `version` (see Task 1 Step 3's `cc_count.json` — the `version` field there is the Catalyst Center version the sandbox runs). State it as one line: `Default active_version: <X>. Rationale: sandbox runs <Y>.`

- [ ] **Step 4: Delete the throwaway script**

```bash
rm /tmp/cc-spec-diff.py
```

- [ ] **Step 5: Commit**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
git add docs/superpowers/findings/2026-05-25-spec-diff.md
git commit -m "docs: spec diff report for 2.3.7.9 vs 3.1.3; recommend default version"
```

---

## Phase C: Repo scaffold

### Task 5: Root-level project metadata files

**Files:**
- Create: `/Users/thomas/python/catalyst-center-super-mcp/.gitignore`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/LICENSE`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/CHANGELOG.md`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/README.md`

- [ ] **Step 1: Write `.gitignore`**

```gitignore
# Local secrets / config
.env
.env.local

# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
.uv/

# Tooling
.ruff_cache/
.mypy_cache/
.pytest_cache/
.coverage
htmlcov/
coverage.xml

# Docs
site/

# OS
.DS_Store
Thumbs.db

# Editors
.vscode/
.idea/
*.swp

# Claude Code agent state — per-clone, not source-of-truth
.claude/
```

- [ ] **Step 2: Write `LICENSE`**

Copy the Apache 2.0 license text verbatim from `/Users/thomas/python/catalyst-sdwan-super-mcp/LICENSE`. Read that file, then write the same content to `catalyst-center-super-mcp/LICENSE`. No name/year substitutions inside the standard license body — only the copyright line at the top should reflect this project's holder (`Copyright 2026 Thomas Christory`).

- [ ] **Step 3: Write `CHANGELOG.md`**

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial repo scaffold: package skeleton with stub modules, config schema,
  Docker setup, CI workflows, docs skeleton.
- Bundled OpenAPI specs for Catalyst Center 2.3.7.9 and 3.1.3.
- Sandbox auth verification findings.
```

- [ ] **Step 4: Write `README.md`**

```markdown
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
```

- [ ] **Step 5: Commit**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
git add .gitignore LICENSE CHANGELOG.md README.md
git commit -m "chore: add root-level project metadata (LICENSE, README, CHANGELOG, gitignore)"
```

---

### Task 6: `pyproject.toml`

**Files:**
- Create: `/Users/thomas/python/catalyst-center-super-mcp/pyproject.toml`

- [ ] **Step 1: Write the file**

```toml
[project]
name = "catalyst-center-super-mcp"
version = "0.1.0"
description = "FastMCP server for the Cisco Catalyst Center (formerly DNA Center) API, generated dynamically from the official OpenAPI specs."
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
license-files = ["LICENSE"]
authors = [{ name = "Thomas Christory", email = "mick27@gmail.com" }]
keywords = ["catalyst-center", "dna-center", "cisco", "mcp", "fastmcp", "openapi", "automation"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Console",
    "Intended Audience :: System Administrators",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: System :: Networking",
]
dependencies = [
    "fastmcp>=2.0",
    "httpx>=0.27",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
]

[project.scripts]
catalyst-center-mcp = "catalyst_center_mcp.server:main"
catalyst-center-super-mcp = "catalyst_center_mcp.server:main"

[project.urls]
Homepage = "https://github.com/thomaschristory/catalyst-center-super-mcp"
Documentation = "https://thomaschristory.github.io/catalyst-center-super-mcp/"
Issues = "https://github.com/thomaschristory/catalyst-center-super-mcp/issues"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["catalyst_center_mcp"]

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-cov>=5.0",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "mypy>=1.10",
    "ruff>=0.6",
    "types-PyYAML>=6.0",
]
docs = [
    "mkdocs>=1.6",
    "mkdocs-material>=9.5",
    "pyyaml>=6.0",
]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "RUF", "SIM", "TID", "C4"]
ignore = ["E501"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101"]

[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
warn_unused_ignores = true
strict = true

[tool.pytest.ini_options]
addopts = "-ra --strict-markers --strict-config"
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Verify it parses**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
python3 -c "import tomllib; tomllib.load(open('pyproject.toml','rb')); print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add pyproject.toml with deps, entry points, ruff/pytest config"
```

---

### Task 7: Package `__init__.py` with version constant

**Files:**
- Create: `/Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp/__init__.py`

- [ ] **Step 1: Write the file**

```python
"""FastMCP server for the Cisco Catalyst Center (formerly DNA Center) API."""

__version__ = "0.1.0"
```

- [ ] **Step 2: Commit**

```bash
mkdir -p /Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp
cd /Users/thomas/python/catalyst-center-super-mcp
git add catalyst_center_mcp/__init__.py
git commit -m "feat(pkg): add catalyst_center_mcp package with __version__"
```

---

### Task 8: Failing smoke test (TDD red phase)

**Files:**
- Create: `/Users/thomas/python/catalyst-center-super-mcp/tests/__init__.py`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/tests/conftest.py`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/tests/test_smoke.py`

**Context:** Write the smoke test before the stubs so we have a clear red→green transition. The smoke test asserts every expected module is importable; with no stubs yet, it fails.

- [ ] **Step 1: Write `tests/__init__.py` (empty)**

```python
```

(literal empty file — `touch tests/__init__.py` equivalent)

- [ ] **Step 2: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures.

The `minimal_spec` fixture is a placeholder — it returns nothing until
`loader.py` has a real implementation. Tests that need it should skip
for now.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def minimal_spec() -> dict:
    pytest.skip("minimal_spec fixture not yet implemented — scaffold only")
```

- [ ] **Step 3: Write `tests/test_smoke.py`**

```python
"""Import smoke test.

Asserts every module in `catalyst_center_mcp` is importable. Catches
accidental syntax errors and missing-symbol bugs in the scaffold during
CI. Does NOT exercise behaviour — bodies are stubs that raise
NotImplementedError when invoked.
"""
from __future__ import annotations

import importlib

EXPECTED_MODULES = [
    "catalyst_center_mcp",
    "catalyst_center_mcp.auth",
    "catalyst_center_mcp.config",
    "catalyst_center_mcp.diff",
    "catalyst_center_mcp.dispatcher",
    "catalyst_center_mcp.fetcher",
    "catalyst_center_mcp.loader",
    "catalyst_center_mcp.pagination",
    "catalyst_center_mcp.server",
    "catalyst_center_mcp.tools",
    "catalyst_center_mcp.transport_auth",
]


def test_all_modules_importable() -> None:
    for name in EXPECTED_MODULES:
        importlib.import_module(name)


def test_version_present() -> None:
    import catalyst_center_mcp

    assert isinstance(catalyst_center_mcp.__version__, str)
    assert catalyst_center_mcp.__version__.count(".") >= 2
```

- [ ] **Step 4: Run pytest, watch it fail**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
uv venv --python 3.12 2>/dev/null || true
uv sync --group dev
uv run pytest tests/test_smoke.py -v
```

Expected: `test_all_modules_importable` FAILS with `ModuleNotFoundError: No module named 'catalyst_center_mcp.auth'` (or similar). `test_version_present` should PASS because Task 7 created `__init__.py` with `__version__`.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: add import smoke test (currently failing — stubs come next)"
```

---

### Task 9: Stub modules (TDD green phase)

**Files:**
- Create: `/Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp/auth.py`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp/config.py`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp/loader.py`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp/dispatcher.py`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp/pagination.py`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp/tools.py`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp/diff.py`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp/transport_auth.py`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp/server.py`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/catalyst_center_mcp/fetcher/__init__.py`

**Context:** Each stub declares the symbols that downstream code will import (read off the sdwan analogues) but raises `NotImplementedError` from every callable. This makes the smoke test pass while making any accidental real call loud.

A common spec link is included so the deferral is discoverable from any module:
`Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md`

- [ ] **Step 1: Write `auth.py`**

```python
"""Catalyst Center upstream authentication.

Single flow: HTTP Basic against POST /dna/system/api/v1/auth/token, returns
a token used as the `X-Auth-Token` header on every subsequent request.
Reactive refresh on 401. No JWT/session dual-mode (unlike sdwan).

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""
from __future__ import annotations

import httpx


class CatalystCenterAuth:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("scaffold only — implement per design doc")

    async def fetch_token(self, client: httpx.AsyncClient) -> str:
        raise NotImplementedError("scaffold only — implement per design doc")

    def header(self) -> dict[str, str]:
        raise NotImplementedError("scaffold only — implement per design doc")
```

- [ ] **Step 2: Write `config.py`**

```python
"""Runtime configuration loaded from config.yaml + env-var interpolation.

Mirrors the sdwan AppConfig structure, swapping VManageConfig →
CatalystCenterConfig and dropping the use_jwt dual-mode flag (Catalyst
Center has a single auth flow).

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetryConfig:
    pass


@dataclass
class PaginationConfig:
    pass


@dataclass
class CatalystCenterConfig:
    pass


@dataclass
class CatalystCenterMcpConfig:
    pass


@dataclass
class TransportAuthConfig:
    pass


@dataclass
class TransportConfig:
    pass


@dataclass
class AppConfig:
    pass


def load_config(path: str = "config.yaml") -> AppConfig:
    raise NotImplementedError("scaffold only — implement per design doc")
```

- [ ] **Step 3: Write `loader.py`**

```python
"""OpenAPI spec loader and adaptive tool splitter.

Verbatim port of sdwan's loader: section → sub-tag → URL path depth 3/4/5,
buckets with <4 ops collapsed into `<parent>_misc`. Action names derived
from (method, path, tag), not the spec's operationId. Pagination style
detected at load time from parameter names.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParameterSpec:
    pass


@dataclass
class OperationSpec:
    pass


@dataclass
class ToolGroup:
    pass


@dataclass
class SpecIndex:
    pass


class SpecLoader:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("scaffold only — implement per design doc")

    def load(self) -> SpecIndex:
        raise NotImplementedError("scaffold only — implement per design doc")
```

- [ ] **Step 4: Write `dispatcher.py`**

```python
"""Request dispatch with auth, retry, and pagination.

Adapted from sdwan's dispatcher. Pagination param-name list extended to
include `offset` and `limit` (Catalyst Center's primary convention).
Reserved-param seam for future `_await_task: true` polling helper —
NOT implemented in v0.1.0; LLM orchestrates Catalyst Center's
`{taskId}` poll loop directly.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""
from __future__ import annotations

from typing import Any


class Dispatcher:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("scaffold only — implement per design doc")

    async def dispatch(self, action_name: str, params: dict[str, Any]) -> Any:
        raise NotImplementedError("scaffold only — implement per design doc")
```

- [ ] **Step 5: Write `pagination.py`**

```python
"""Pagination strategies for Catalyst Center endpoints.

Verbatim port of sdwan's pagination module. Primary strategy is
offset/limit (Catalyst Center's dominant convention). Hybrid
auto-follow + cursor support driven by config.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""
from __future__ import annotations

from typing import Any


async def paginate(*args: object, **kwargs: object) -> Any:
    raise NotImplementedError("scaffold only — implement per design doc")
```

- [ ] **Step 6: Write `tools.py`**

```python
"""MCP tool registration from a loaded SpecIndex.

Verbatim port of sdwan's tools module. One MCP tool per ToolGroup;
description enumerates actions and their params. RW gate enforced
here — write tools are not registered when `read_write=False`.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""
from __future__ import annotations

from typing import Any


def register_tools(
    mcp: Any,
    index: Any,
    dispatcher: Any,
    read_write: bool,
) -> None:
    raise NotImplementedError("scaffold only — implement per design doc")
```

- [ ] **Step 7: Write `diff.py`**

```python
"""Compare two bundled spec versions.

Verbatim port of sdwan's diff module. Used by the CLI `--diff` flag in
a later session; not invoked at scaffold time.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""
from __future__ import annotations

from typing import Any


def diff_versions(a: Any, b: Any) -> Any:
    raise NotImplementedError("scaffold only — implement per design doc")


def print_diff(diff: Any) -> None:
    raise NotImplementedError("scaffold only — implement per design doc")
```

- [ ] **Step 8: Write `transport_auth.py`**

```python
"""Bearer-token auth for the MCP server's SSE / streamable-HTTP transports.

Distinct from upstream Catalyst Center auth (see auth.py). Protects the
MCP server itself when exposed over the network. Verbatim port of sdwan's
transport_auth module.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""
from __future__ import annotations

from typing import Any


def make_bearer_middleware(*args: object, **kwargs: object) -> Any:
    raise NotImplementedError("scaffold only — implement per design doc")
```

- [ ] **Step 9: Write `server.py`**

```python
"""FastMCP server entry point.

`main()` is the script target declared in pyproject.toml. Wires up
config loading, spec loading, auth, dispatcher, tool registration, and
transport selection (stdio / sse / streamable-http).

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""
from __future__ import annotations


def main() -> None:
    raise NotImplementedError("scaffold only — implement per design doc")
```

- [ ] **Step 10: Write `fetcher/__init__.py`**

```python
"""Auto-fetch Catalyst Center OpenAPI specs from DevNet at startup.

Subpackage placeholder only. Real DevNet download flow is deferred —
the canonical URL discovery is non-trivial and out of scope for the
bootstrap session. config.yaml ships with `auto_fetch: false`; real
implementation will set the default to `true`.

Implementation deferred — see docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md
"""
from __future__ import annotations

from pathlib import Path


def fetch_spec(version: str, dest: Path) -> None:
    raise NotImplementedError("scaffold only — implement per design doc")
```

- [ ] **Step 11: Run the smoke test, watch it pass**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
uv run pytest tests/test_smoke.py -v
```

Expected: both tests PASS. If `test_all_modules_importable` still fails, the failure name tells you which module is missing — go back to the matching step.

- [ ] **Step 12: Run ruff to confirm stubs lint cleanly**

```bash
uv run ruff check catalyst_center_mcp/ tests/
uv run ruff format --check catalyst_center_mcp/ tests/
```

Expected: both pass with zero issues. If `ruff format --check` complains, run `uv run ruff format catalyst_center_mcp/ tests/` and re-check.

- [ ] **Step 13: Commit**

```bash
git add catalyst_center_mcp/
git commit -m "feat(pkg): add stub modules (auth, config, loader, dispatcher, pagination, tools, diff, transport_auth, server, fetcher)"
```

---

### Task 10: `config.yaml`

**Files:**
- Create: `/Users/thomas/python/catalyst-center-super-mcp/config.yaml`

- [ ] **Step 1: Write the file**

```yaml
catalyst_center:
  # Cisco Catalyst Center Sandbox defaults — replace with your own deployment.
  # https://devnetsandbox.cisco.com/  (always-on, no reservation required)
  host: sandboxdnac.cisco.com
  port: 443
  verify_ssl: true
  username: "${CATALYST_CENTER_USERNAME}"
  password: "${CATALYST_CENTER_PASSWORD}"
  timeout: 30.0            # per-request httpx timeout (seconds)
  retries:
    max_attempts: 3        # total attempts incl. first try; 1 disables retries
    statuses: [502, 503, 504]
    backoff_base: 0.5      # seconds; first backoff is base * 2**0 with jitter
    backoff_cap: 8.0       # upper bound on a single backoff
    retry_mutating: false  # default: only GET is retried

catalyst_center_mcp:
  specs_dir: ./specs
  active_version: "TBD-after-spec-diff"  # update from docs/superpowers/findings/2026-05-25-spec-diff.md
  max_actions_per_tool: 80               # adaptive splitter cap; 0 disables splitting
  auto_fetch: false                      # v0.1.0 ships without fetcher; flip when fetcher/ is real
  pagination:
    enabled: true
    max_pages: 5
    page_size: null

transport:
  mode: stdio                       # stdio | sse | streamable-http
  host: 127.0.0.1
  port: 8000
  # HTTP transports (sse, streamable-http) only:
  #   type: none    → no auth. Auto-demoted to 127.0.0.1 if host is non-loopback,
  #                   unless you also pass --insecure-allow-public.
  #   type: bearer  → require `Authorization: Bearer <token>` on every request.
  auth:
    type: none
    # token: "${CATALYST_CENTER_MCP_TOKEN}"
```

- [ ] **Step 2: Verify YAML parses**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
uv run python -c "import yaml; yaml.safe_load(open('config.yaml')); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Update `active_version`**

Open `docs/superpowers/findings/2026-05-25-spec-diff.md`, read the `## Recommendation` line, and replace `TBD-after-spec-diff` in `config.yaml` with that version (e.g. `"2.3.7.9"`).

- [ ] **Step 4: Commit**

```bash
git add config.yaml
git commit -m "config: add config.yaml with retries, pagination, transport auth (active_version pinned to sandbox)"
```

---

### Task 11: `.env.example`

**Files:**
- Create: `/Users/thomas/python/catalyst-center-super-mcp/.env.example`

- [ ] **Step 1: Write the file**

```bash
# Catalyst Center connection
# DevNet always-on sandbox: https://devnetsandbox.cisco.com/
# Sandbox host: sandboxdnac.cisco.com  (creds rotate — verify on the sandbox page)
CATALYST_CENTER_USERNAME=
CATALYST_CENTER_PASSWORD=
# Optional — overrides config.yaml `catalyst_center.host` if set.
# CATALYST_CENTER_HOST=
# CATALYST_CENTER_VERIFY_SSL=true

# MCP server transport bearer token (only used when transport.auth.type=bearer in config.yaml)
# CATALYST_CENTER_MCP_TOKEN=
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "config: add .env.example with blank placeholders and DevNet sandbox pointer"
```

---

### Task 12: Docker setup

**Files:**
- Create: `/Users/thomas/python/catalyst-center-super-mcp/Dockerfile`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/docker-compose.yml`

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
COPY catalyst_center_mcp ./catalyst_center_mcp

# Install into /app/.venv
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# --- runtime ---
FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /app /app
COPY config.yaml ./

ENV PATH="/app/.venv/bin:$PATH"

# Specs are mounted at runtime — not baked into the image
# -----------------------------------------------------------------------
# Usage:
#
# Build:
#   docker build -t catalyst-center-super-mcp .
#
# Claude Desktop (stdio):
#   docker run -i --rm \
#     -e CATALYST_CENTER_USERNAME=devnetuser \
#     -e CATALYST_CENTER_PASSWORD=Cisco123! \
#     -v $(pwd)/specs:/app/specs \
#     catalyst-center-super-mcp
#
# Network (SSE):
#   docker run -p 8000:8000 \
#     -e CATALYST_CENTER_USERNAME=devnetuser \
#     -e CATALYST_CENTER_PASSWORD=Cisco123! \
#     -v $(pwd)/specs:/app/specs \
#     catalyst-center-super-mcp --transport sse --host 0.0.0.0 --port 8000
# -----------------------------------------------------------------------

ENTRYPOINT ["catalyst-center-mcp"]
```

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
services:
  catalyst-center-mcp:
    build: .
    image: catalyst-center-super-mcp:latest
    env_file: .env
    environment:
      - CATALYST_CENTER_USERNAME=${CATALYST_CENTER_USERNAME}
      - CATALYST_CENTER_PASSWORD=${CATALYST_CENTER_PASSWORD}
      - CATALYST_CENTER_MCP_TOKEN=${CATALYST_CENTER_MCP_TOKEN}
    volumes:
      - ./specs:/app/specs:ro
      - ./config.yaml:/app/config.yaml:ro
    # Default for compose: SSE transport on 8000 (network-accessible)
    command: ["--transport", "sse", "--host", "0.0.0.0", "--port", "8000"]
    ports:
      - "8000:8000"
    restart: unless-stopped

  # Uncomment for a separate RW endpoint.
  # catalyst-center-mcp-rw:
  #   build: .
  #   image: catalyst-center-super-mcp:latest
  #   env_file: .env
  #   volumes:
  #     - ./specs:/app/specs:ro
  #     - ./config.yaml:/app/config.yaml:ro
  #   command: ["--transport", "sse", "--host", "0.0.0.0", "--port", "8001", "--read-write"]
  #   ports:
  #     - "8001:8001"
```

- [ ] **Step 3: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "build(docker): add multi-stage Dockerfile (uv-based) and docker-compose"
```

---

### Task 13: mkdocs skeleton

**Files:**
- Create: `/Users/thomas/python/catalyst-center-super-mcp/mkdocs.yml`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/docs/index.md`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/docs/architecture/overview.md`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/docs/architecture/data-flow.md`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/docs/guides/tool-splitting.md`

- [ ] **Step 1: Write `mkdocs.yml`**

```yaml
site_name: catalyst-center-super-mcp
site_description: FastMCP server for the Cisco Catalyst Center API
site_url: https://thomaschristory.github.io/catalyst-center-super-mcp/
repo_url: https://github.com/thomaschristory/catalyst-center-super-mcp
repo_name: thomaschristory/catalyst-center-super-mcp

theme:
  name: material
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
  features:
    - navigation.instant
    - navigation.tracking
    - navigation.tabs
    - navigation.sections
    - navigation.expand
    - navigation.top
    - content.code.copy
    - content.code.annotate

nav:
  - Home: index.md
  - Architecture:
      - Overview: architecture/overview.md
      - Data flow: architecture/data-flow.md
  - Guides:
      - Tool splitting: guides/tool-splitting.md

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences
  - pymdownx.tabbed:
      alternate_style: true
  - tables
  - toc:
      permalink: true
```

- [ ] **Step 2: Write placeholder docs**

`docs/index.md`:

```markdown
# catalyst-center-super-mcp

FastMCP server for the Cisco Catalyst Center (formerly DNA Center) API.

> **Scaffold release.** Real auth/loader/dispatcher implementation lands in a follow-up session. See [the bootstrap design](https://github.com/thomaschristory/catalyst-center-super-mcp/blob/main/docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md) for what's intentionally deferred.
```

`docs/architecture/overview.md`:

```markdown
# Architecture overview

_Placeholder. Will be filled in once auth.py, loader.py, dispatcher.py have real implementations._

The architecture mirrors [`catalyst-sdwan-super-mcp`](https://github.com/thomaschristory/catalyst-sdwan-super-mcp) one-to-one — see that repo's architecture docs for the model. The Catalyst Center port deviates only in auth (single flow) and pagination defaults (offset/limit primary).
```

`docs/architecture/data-flow.md`:

```markdown
# Data flow

_Placeholder. See the sdwan repo's `docs/architecture/data-flow.md` for the model._
```

`docs/guides/tool-splitting.md`:

```markdown
# Tool splitting

_Placeholder. See the sdwan repo's `docs/guides/tool-splitting.md` for the algorithm. Numbers will differ on Catalyst Center because the spec is smaller and flatter; `max_actions_per_tool` ships at 80 instead of sdwan's 150._
```

- [ ] **Step 3: Verify mkdocs builds**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
uv sync --group docs
uv run mkdocs build --strict
```

Expected: build completes with no warnings (the `--strict` flag turns warnings into errors). If it fails on missing references, fix the offending link.

- [ ] **Step 4: Commit**

```bash
git add mkdocs.yml docs/index.md docs/architecture/ docs/guides/
git commit -m "docs: add mkdocs skeleton with placeholders for architecture and guides"
```

---

### Task 14: GitHub Actions workflows

**Files:**
- Create: `/Users/thomas/python/catalyst-center-super-mcp/.github/workflows/ci.yml`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/.github/workflows/release.yml`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/.github/workflows/docs.yml`

- [ ] **Step 1: Write `ci.yml` (new — sdwan has no equivalent)**

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint-test-build:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v7
      - name: Install Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}
      - name: Sync dependencies
        run: uv sync --group dev
      - name: Ruff lint
        run: uv run ruff check .
      - name: Ruff format check
        run: uv run ruff format --check .
      - name: Pytest
        run: uv run pytest -v
      - name: Build sdist + wheel
        run: uv build
```

- [ ] **Step 2: Write `release.yml`**

Copy `/Users/thomas/python/catalyst-sdwan-super-mcp/.github/workflows/release.yml` content, then replace these strings:

- `catalyst-sdwan-super-mcp` → `catalyst-center-super-mcp` (in the PyPI URL)

The full adapted file:

```yaml
name: release

on:
  push:
    tags:
      - "v*"

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - name: Install uv
        uses: astral-sh/setup-uv@v7
      - name: Install Python
        run: uv python install 3.12
      - name: Build sdist + wheel
        run: uv build
      - name: Upload dist artifact
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  pypi-publish:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/catalyst-center-super-mcp
    permissions:
      id-token: write
    steps:
      - name: Download dist artifact
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1

  github-release:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - name: Download dist artifact
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - name: Create GitHub release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          TAG: ${{ github.ref_name }}
        run: |
          gh release create "$TAG" \
            --title "$TAG" \
            --notes "Release $TAG. See CHANGELOG.md for details." \
            dist/*
```

- [ ] **Step 3: Write `docs.yml`**

```yaml
name: docs

on:
  pull_request:
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - ".github/workflows/docs.yml"
  push:
    branches: [main]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - ".github/workflows/docs.yml"
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - name: Install uv
        uses: astral-sh/setup-uv@v7
        with:
          enable-cache: true
      - name: Install Python
        run: uv python install 3.12
      - name: Sync deps (runtime + docs)
        run: uv sync --group docs
      - name: Build site (strict)
        run: uv run mkdocs build --strict
      - name: Upload Pages artifact
        if: github.event_name == 'push' || github.event_name == 'workflow_dispatch'
        uses: actions/upload-pages-artifact@v5
        with:
          path: site

  deploy:
    needs: build
    if: github.event_name == 'push' || github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v5
```

- [ ] **Step 4: Validate YAML parses**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
for f in .github/workflows/*.yml; do
  uv run python -c "import yaml; yaml.safe_load(open('$f')); print('$f ok')"
done
```

Expected: three `ok` lines.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/
git commit -m "ci: add ci.yml (lint+test+build matrix) and port release.yml + docs.yml from sdwan"
```

---

### Task 15: Agent docs — `CLAUDE.md` and `AGENTS.md`

**Files:**
- Create: `/Users/thomas/python/catalyst-center-super-mcp/CLAUDE.md`
- Create: `/Users/thomas/python/catalyst-center-super-mcp/AGENTS.md`

**Context:** Carry over sdwan's CLAUDE.md and AGENTS.md, swapping product names. Strip out: the qorexdevs incident note, vManage-specific issue history, milestone trackers. Keep the architecture summary and the contribution/security gates.

- [ ] **Step 1: Read the sdwan versions**

```bash
ls -la /Users/thomas/python/catalyst-sdwan-super-mcp/CLAUDE.md /Users/thomas/python/catalyst-sdwan-super-mcp/AGENTS.md
```

Read each file in full. Identify sections to keep (architecture, decisions log, security/contribution gates) vs. sections to drop (incident notes, issue/milestone trackers).

- [ ] **Step 2: Write the adapted `CLAUDE.md`**

Substitution rules across the kept content:

- `Catalyst SD-WAN Manager` / `vManage` → `Catalyst Center` / `Cisco DNA Center`
- `catalyst-sdwan-super-mcp` → `catalyst-center-super-mcp`
- `sdwan_mcp` → `catalyst_center_mcp`
- `sdwan-mcp` → `catalyst-center-mcp`
- `VMANAGE_USERNAME` / `VMANAGE_PASSWORD` → `CATALYST_CENTER_USERNAME` / `CATALYST_CENTER_PASSWORD`
- `vmanage:` → `catalyst_center:` (in YAML examples)
- `j_security_check` / JWT / session dual-mode → single Basic→token→`X-Auth-Token` flow
- `JSESSIONID` references → removed (no cookie jar in Catalyst Center)
- sandbox host `sandbox-sdwan-2.cisco.com` → `sandboxdnac.cisco.com`
- API base `/dataservice/...` → `/dna/intent/api/v1/...` and `/dna/system/api/v1/...`
- bundled versions `20.15/20.16/20.18` → `2.3.7.9/3.1.3`
- default `max_actions_per_tool: 150` → `80`
- `use_jwt` references → removed
- the qorexdevs PR note → removed entirely
- any "milestones for v0.x.y" sections → removed (this is a fresh v0.1.0)

Add a section at the top: "Bootstrap status — this repo was scaffolded on 2026-05-25 per `docs/superpowers/specs/2026-05-25-catalyst-center-bootstrap-design.md`. All code modules are NotImplementedError stubs until a follow-up session."

- [ ] **Step 3: Write the adapted `AGENTS.md`**

Apply the same substitution rules from Step 2. Drop any sdwan-specific operational anecdotes.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md AGENTS.md
git commit -m "docs: add CLAUDE.md and AGENTS.md (adapted from sdwan, dropping incident/milestone history)"
```

---

## Phase D: End-to-end verification

### Task 16: Run all CI gates locally and confirm green

**Files:** none modified

**Context:** The CI workflow runs ruff + pytest + uv build. Run all four locally before declaring the session done; CI failing on push is preventable here.

- [ ] **Step 1: Clean install**

```bash
cd /Users/thomas/python/catalyst-center-super-mcp
rm -rf .venv .ruff_cache .pytest_cache dist build
uv sync --group dev
```

Expected: completes without errors.

- [ ] **Step 2: Ruff lint**

```bash
uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 3: Ruff format check**

```bash
uv run ruff format --check .
```

Expected: `N files already formatted` (zero would-be-reformatted files).

- [ ] **Step 4: Pytest**

```bash
uv run pytest -v
```

Expected: 2 passed (`test_all_modules_importable`, `test_version_present`); 0 failed. If the `minimal_spec` fixture is touched anywhere, it should skip — that's fine.

- [ ] **Step 5: Build**

```bash
uv build
ls -la dist/
```

Expected: `dist/` contains `catalyst_center_super_mcp-0.1.0-py3-none-any.whl` and `catalyst_center_super_mcp-0.1.0.tar.gz`.

- [ ] **Step 6: Sanity-check the wheel**

```bash
uv run --with dist/*.whl --no-project python -c "
import catalyst_center_mcp
print('imported version:', catalyst_center_mcp.__version__)
try:
    catalyst_center_mcp.server.main()
except NotImplementedError as e:
    print('expected NotImplementedError:', e)
"
```

Expected: prints `imported version: 0.1.0` and `expected NotImplementedError: scaffold only — implement per design doc`.

- [ ] **Step 7: Final commit (only if anything changed during verification)**

If Steps 1–6 surfaced lint/format issues you had to fix, commit those:

```bash
git add -A
git status   # confirm only formatting fixes
git commit -m "chore: post-verification lint/format fixes" || echo "nothing to commit"
```

- [ ] **Step 8: Print the session checkpoint summary**

Report back to the user with:

1. Final tree: `find . -type f -not -path './.venv/*' -not -path './.git/*' -not -path './dist/*' -not -path './build/*' -not -path './.ruff_cache/*' -not -path './.pytest_cache/*' -not -path './site/*' -not -path './specs/*/catalyst-center-openapi.json' | sort`
2. Findings doc summary — the auth verdict (matches bootstrap doc or not) and the spec-diff default-version recommendation.
3. Git log: `git log --oneline`
4. Reminder: GitHub repo not created. Local-only. User decides next when to `gh repo create`.

---

## Out of scope this session — explicit non-goals

- No real bodies in `auth.py`, `loader.py`, `dispatcher.py`, `pagination.py`, `tools.py`, `transport_auth.py`, `diff.py`, `server.py`, `fetcher/`.
- No `gh repo create`. No `git push`. No PR.
- No integration tests, no respx mocks, no sandbox-hitting tests.
- No `mypy`/`pyright` in CI yet (matches sdwan).
- No DevNet auto-fetcher implementation (subpackage is a stub).
- No `api_version` default chosen blind — only after Task 4 produces a recommendation.
- No carry-over of qorexdevs incident note, sdwan issue history, or milestones.
