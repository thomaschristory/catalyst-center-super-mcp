# Catalyst Center Sandbox Auth — Findings

**Probed:** 2026-05-25
**Host:** sandboxdnac.cisco.com
**Creds:** devnetuser / Cisco123!

## 1. Probe commands

```bash
# Step 2 — Token endpoint
curl -k -sS -o /tmp/cc_token.json -w "HTTP %{http_code}\nContent-Type: %{content_type}\n" \
  -u devnetuser:Cisco123! \
  -X POST https://sandboxdnac.cisco.com/dna/system/api/v1/auth/token
echo "---"
cat /tmp/cc_token.json | python3 -m json.tool

# Step 3 — Authenticated GET
TOKEN=$(python3 -c "import json; print(json.load(open('/tmp/cc_token.json'))['Token'])")
curl -k -sS -o /tmp/cc_count.json -w "HTTP %{http_code}\n" \
  -H "X-Auth-Token: $TOKEN" \
  https://sandboxdnac.cisco.com/dna/intent/api/v1/network-device/count
echo "---"
cat /tmp/cc_count.json | python3 -m json.tool

# Step 4 — Deliberate 401
curl -k -sS -o /tmp/cc_401.json -D /tmp/cc_401_headers.txt -w "HTTP %{http_code}\n" \
  -H "X-Auth-Token: not-a-real-token" \
  https://sandboxdnac.cisco.com/dna/intent/api/v1/network-device/count
echo "--- body ---"
cat /tmp/cc_401.json
echo "--- headers ---"
cat /tmp/cc_401_headers.txt
```

## 2. Token endpoint

- URL: `POST https://sandboxdnac.cisco.com/dna/system/api/v1/auth/token`
- Auth: HTTP Basic (`Authorization: Basic base64(username:password)`)
- Response status: **200**
- Response body shape: `{"Token": "eyJhbGci...t6zgVqlw", "message": ""}` (length: **870** chars)
- Token format: JWT (ES256 — `{"alg": "ES256", "typ": "JWT"}`)
- Token TTL hint: **explicitly embedded in JWT claims** — `iat` and `exp` differ by exactly **3600 seconds (1 hour)**. Not surfaced as a response header; must be read from the JWT payload or assumed as 1 hour.
- Extra response key: `"message": ""` (empty string — no significance observed)

## 3. Auth header

- Name: `X-Auth-Token` (exact casing — confirmed)
- Placement: request header on every authenticated call
- Behaviour: authenticated GET to `/dna/intent/api/v1/network-device/count` returned HTTP 200 with expected JSON body. No cookies required. No XSRF token required.

## 4. 401 behaviour

- Status: **401**
- Body shape: `{"message":"Bad token; invalid JSON"}`
  - Single key `message` with a human-readable error string.
  - Note: error message varies by failure mode — an invalid JWT string produces "Bad token; invalid JSON"; an expired but structurally valid JWT would likely produce a different message (untested).
- Retry-hint headers: **none** — no `WWW-Authenticate`, `Retry-After`, or similar headers observed.
  - Headers present: `date`, `content-type`, `content-length`, `via: api-gateway`, `content-security-policy`, `x-xss-protection`, `x-frame-options`, `access-control-allow-methods`
- Replay-after-expiry behaviour: untested in always-on sandbox (would require waiting 1 hour or manipulating the token).

## 5. Sandbox-reported Catalyst Center version

- From `/dna/intent/api/v1/network-device/count` `version` field: **`"1.0"`**
- Note: this is the **API envelope version**, not the Catalyst Center platform version. The platform version is not returned by this endpoint. The response was `{"response": 4, "version": "1.0"}`.
- Task 10 should verify which field conveys the actual platform version (e.g. from a `/dna/intent/api/v1/dnacaap/management/systemInfo` or similar system endpoint) before pinning `catalyst_center_mcp.active_version`.

## 6. Deviations from bootstrap doc

One minor addition — the response body includes an extra `"message": ""` key beyond the documented `{"Token": "..."}` shape:

```
Documented:  {"Token": "eyJ..."}
Observed:    {"Token": "eyJ...", "message": ""}
```

This is benign — `auth.py` should key only on `response["Token"]` and ignore `message`. Not a breaking deviation.

One clarification on TTL: the bootstrap doc says "~1 hour by default" as an assumption. This is **confirmed precisely** — the JWT `exp - iat = 3600` seconds. The TTL is encoded in the token itself, so `auth.py` can decode the JWT header+payload (no signature verification needed) to know the exact expiry rather than hardcoding 3600.

One important clarification on the "version" field: the bootstrap doc does not specify what the `version` field in API responses means. Observed value is `"1.0"` — this appears to be the **API response schema version**, not the Catalyst Center platform version. Task 10 must probe a system-info endpoint to get the actual platform version before setting `active_version`.

Everything else in the bootstrap doc is confirmed correct.

## 7. Open questions

- **Token TTL:** Confirmed exactly 1 hour via JWT claims (`exp - iat = 3600`). The bootstrap doc's "~1 hour" estimate is accurate.
- **JWT decoding for expiry:** Since the token is a standard JWT (ES256), `auth.py` can parse the `exp` claim without verifying the signature to know when to proactively re-auth. Decide: proactive refresh (e.g. at 50 min) vs reactive re-auth on 401.
- **Platform version endpoint:** `version: "1.0"` in network-device count is the API envelope version. Need to probe a system endpoint (e.g. `/dna/intent/api/v1/network-settings/global-pool` or a dedicated platform-info endpoint) to get actual Catalyst Center version string for Task 10.
- **401 on expired-but-valid JWT:** Untested — would need to use a token after its `exp`. The 401 body message may differ from "Bad token; invalid JSON" (which fired on a non-JWT string). The error message is not machine-parseable for distinguishing "expired" vs "malformed" — plan to treat all 401s as re-auth triggers.
- **Prod-instance behaviour vs always-on sandbox:** Untested. Prod instances may use different auth variants (e.g. SSO, LDAP) that bypass this endpoint.
- **Role in JWT:** The sandbox token carries `"roles": ["OBSERVER"]` — read-only role. This is expected for the always-on sandbox and means write operations may return 403 even with a valid token.
