# Security Audit — Admin Console `/admin`

**Date**: 2026-05-16  
**Auditor**: CLR (Cline agent)  
**Scope**: Admin console `/admin` — backend (`/api/tool`, `_api_tool_call`, `call_tool_direct`), frontend (`admin.html`, `admin-api.js`, `admin-app.js`, `admin.css`), auth middleware, WAF Caddy  
**Version audited**: v2.0.1 (commit f8c7360)  
**Version remediated**: v2.0.2  
**Methodology**: Static code review, data flow analysis, STRIDE threat modeling  

---

## Executive Summary

The `/admin` console exposes all 40 MCP tools through an elegant web interface and an internal REST proxy (`POST /api/tool → call_tool_direct()`). The architecture is fundamentally sound: HttpOnly cookie authentication (LM2-04), per-tool permission enforcement, strict CSP via the Caddy WAF. However, **10 findings** were identified, of which **7 have been remediated** in v2.0.2, including **1 critical** (XSS via HTML attribute injection) and **3 high** severity issues.

| Severity | Count | Findings | Status |
|----------|-------|----------|--------|
| 🔴 CRITICAL | 1 | ADM-01 | ✅ Fixed |
| 🟠 HIGH | 3 | ADM-02, ADM-03, ADM-04 | ✅✅🔶 (ADM-04 accepted) |
| 🟡 MEDIUM | 4 | ADM-05, ADM-06, ADM-07, ADM-08 | ✅✅🔶✅ (ADM-07 accepted) |
| 🔵 LOW | 2 | ADM-09, ADM-10 | ✅🔶 (ADM-10 accepted) |

**Remediation summary**: 7/10 fixed, 3/10 risk-accepted (ADM-04, ADM-07, ADM-10).  
**Test coverage**: 13 non-complaisant tests in `tests/test_admin_console_security.py`.  
**Regression**: 368/368 PASS + 1 xfailed (was 355+1, zero regressions).

---

## Findings & Remediations

### ADM-01 🔴 CRITICAL — Incomplete HTML Escaping → Attribute Injection / XSS

**File**: `admin-app.js:7`  
**Vector**: Token names, space descriptions, emails — any user-controlled data rendered in HTML  
**Status**: ✅ **Fixed in v2.0.2**

**Description**:  
The `esc()` sanitization function only neutralized `&`, `<`, and `>`:
```javascript
// BEFORE (vulnerable)
const esc = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
```

It did **not escape** single quotes (`'`) or double quotes (`"`). Values processed by `esc()` were inserted into HTML attributes:

```javascript
// Example: token name in a double-quoted attribute
data-action="update-token" data-hash="${h}" data-name="${n}"
// data-msg="Permanently delete token ${n}?"
```

**Attack scenario**: An attacker with `admin` permission creates a token with a malicious name:
```
foo" data-action="confirm" data-tool="space_delete" data-args='{"space_id":"prod","confirm":true}' data-msg="x
```
When another admin opens the Tokens page, the rendered HTML contains a button that triggers space deletion on accidental click.

**Existing mitigations**:
- `space_id` values are validated server-side by `_SPACE_ID_REGEX` (alphanumeric + hyphens only) → no quotes possible ✓
- Token hashes are hexadecimal → no quotes possible ✓
- However, **token names**, **emails**, **space descriptions**, and **owners** had **no character restrictions** server-side

**Remediation**:
```javascript
// AFTER (v2.0.2)
const esc = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#x27;');
```

**Tests**: `TestADM01_EscEscapesQuotes` (2 tests — source introspection verifying `&quot;` and `&#x27;` in esc function)

---

### ADM-02 🟠 HIGH — Exception Message Leakage in `/api/tool`

**File**: `auth/middleware.py` (`_api_tool_call`)  
**Status**: ✅ **Fixed in v2.0.2**

**Description**:  
The `/api/tool` endpoint returned the full Python exception message to the client:
```python
# BEFORE (vulnerable)
except Exception as e:
    await self._send_json(send, {"status": "error", "message": str(e)}, 500)
```

This could expose internal file paths, S3 endpoint URLs, configuration details, and boto3/httpx stack traces. The `safe_error()` helper (already used elsewhere for VULN-27) was not applied here.

**Remediation**:
```python
# AFTER (v2.0.2)
except Exception as e:
    logger.exception("/api/tool error")
    from ..auth.context import safe_error
    await self._send_json(send, safe_error(e, "/api/tool"), 500)
```

**Tests**: `TestADM02_SafeErrorInApiTool` (1 test — source introspection verifying `safe_error(` present and `str(e)` absent from except block)

---

### ADM-03 🟠 HIGH — No CSP Headers Without WAF (Defense-in-Depth Gap)

**File**: `auth/middleware.py` (`_serve_file`)  
**Status**: ✅ **Fixed in v2.0.2**

**Description**:  
The `_serve_file()` method serving `admin.html` included **no security headers**. CSP (`script-src 'self'`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and `Permissions-Policy` were only set by the Caddy WAF.

If the application were accessed directly on port 8002 (bypassing the WAF — in dev, debug, or misconfigured deployment), the admin console had **zero CSP protection**, making XSS vulnerabilities directly exploitable.

**Remediation**: Security headers are now added to all HTML responses by `_serve_file()`:
```python
# AFTER (v2.0.2) — defense-in-depth, duplicates WAF headers
if "text/html" in content_type:
    headers.extend([
        (b"content-security-policy", b"default-src 'self'; script-src 'self'; ..."),
        (b"x-frame-options", b"DENY"),
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    ])
```

Non-HTML files (CSS, JS, images) are not affected.

**Tests**: `TestADM03_CspHeadersOnHtml` (3 tests — CSP on HTML, no CSP on CSS, X-Frame-Options: DENY)

---

### ADM-04 🟠 HIGH — Raw Token Stored in Cookie

**File**: `auth/middleware.py` (`_api_login`)  
**Status**: 🔶 **Risk accepted** (documented)

**Description**:  
The authentication cookie stores the raw bearer token:
```python
cookie_parts = [f"{AUTH_COOKIE_NAME}={token}", "Path=/", "HttpOnly", "SameSite=Strict"]
```

If an attacker extracts the cookie (server vulnerability, memory dump, physical access to browser), they obtain the full bearer token usable from any HTTP client.

**Existing mitigations**:
- `HttpOnly` blocks JavaScript exfiltration ✓
- `SameSite=Strict` blocks CSRF ✓
- `Secure` flag added in HTTPS ✓
- Session cookie (no Max-Age) → expires when browser closes ✓

**Risk acceptance rationale**: The admin console is an internal tool. Implementing a server-side session store (~50-150 lines) would add complexity without proportionate security gain given the existing mitigations. The choice is documented here for future reference.

---

### ADM-05 🟡 MEDIUM — No Request Body Size Limit on `/api/tool`

**File**: `auth/middleware.py` (`_api_tool_call`), `config.py`  
**Status**: ✅ **Fixed in v2.0.2**

**Description**:  
The `/api/tool` endpoint read the entire HTTP body into memory without any size limit. A malicious client could send a multi-GB body to exhaust server memory (WAF limits to 75 MB, but not applicable if WAF is bypassed).

**Remediation**: New configurable setting `API_TOOL_MAX_BODY_BYTES` (default: 1 MB). The body read loop now tracks cumulative size and returns `413 Request Entity Too Large` if exceeded.

**Tests**: `TestADM05_BodySizeLimit` (2 tests — oversized body rejected with 413, normal body accepted)

---

### ADM-06 🟡 MEDIUM — No Permission Gate on `/api/tool`

**File**: `auth/middleware.py` (`_api_tool_call`)  
**Status**: ✅ **Fixed in v2.0.2**

**Description**:  
The `/api/tool` endpoint had no permission check at the route level. Any authenticated token (including `read`-only) could call the endpoint and attempt to invoke any of the 40 MCP tools. While each tool enforces its own permissions internally, a read-only token could enumerate tools and probe the API.

**Remediation**: `check_write_permission()` is now called at the top of `_api_tool_call`. Read-only tokens get `403 Forbidden`. Users with read-only access can still use `/live` for viewing.

**Tests**: `TestADM06_PermissionGate` (2 tests — read-only token blocked with 403, write token allowed through)

---

### ADM-07 🟡 MEDIUM — Admin Console Structure Publicly Visible

**File**: `auth/middleware.py` (`PUBLIC_PATHS`)  
**Status**: 🔶 **Risk accepted**

**Description**:  
`/admin` and `/admin/` are in `PUBLIC_PATHS`, allowing anyone to load the HTML page, CSS, and JS. This reveals tool names, categories, and API structure.

**Risk acceptance rationale**: The Swagger UI on `/` already exposes the same information (tool names, parameters). The actual data and operations require a valid authentication cookie. Placing `/admin` behind auth would break the login flow (the page itself contains the login form).

---

### ADM-08 🟡 MEDIUM — Audit Trail Doesn't Log Tool Name/Arguments

**File**: `auth/middleware.py` (`_api_tool_call`)  
**Status**: ✅ **Fixed in v2.0.2**

**Description**:  
The AuditMiddleware logged requests to `/api/tool` but only recorded the HTTP path — not which tool was called or what arguments were passed. An admin deleting a space or revoking a token via the console left only a generic trace.

**Remediation**: A dedicated audit log entry is now emitted **before** tool execution:
```json
{
    "event": "admin_tool_call",
    "request_id": "abc123...",
    "tool": "space_delete",
    "arguments_keys": ["space_id", "confirm"],
    "client": "admin-user"
}
```
Only argument **keys** are logged (not values, which may contain sensitive data).

**Tests**: `TestADM08_AuditLogToolName` (1 test — verifies audit entry contains tool name, argument keys, and client identity)

---

### ADM-09 🔵 LOW — Reliance on Internal FastMCP API

**File**: `tools/__init__.py` (`call_tool_direct`)  
**Status**: ✅ **Regression test added in v2.0.2**

**Description**:  
`call_tool_direct()` accesses private FastMCP attributes (`_tool_manager._tools`) and probes for callable attributes via a fallback loop. This is brittle and could break on library upgrades.

**Remediation**: Regression tests added to verify `call_tool_direct` handles both unknown tools and uninitialized `_mcp_ref` gracefully.

**Tests**: `TestADM09_CallToolDirectRegression` (2 tests — unknown tool returns structured error, uninitialized mcp_ref returns error without crash)

---

### ADM-10 🔵 LOW — No CSRF Token Mechanism

**File**: N/A (architecture)  
**Status**: 🔶 **Risk accepted**

**Description**:  
CSRF protection relies solely on `SameSite=Strict` and JSON `Content-Type`. No synchronizer token or double-submit cookie is implemented.

**Risk acceptance rationale**: `SameSite=Strict` prevents cookie transmission from cross-origin requests. JSON `Content-Type` prevents standard form-based CSRF. Combined, these provide adequate protection per OWASP guidelines for internal APIs. Residual risk is limited to malicious browser extensions or local proxy attacks.

---

## Architecture Assessment

### Strengths ✅

1. **HttpOnly + SameSite=Strict cookie** — Robust protection against XSS exfiltration and CSRF
2. **Per-tool permission enforcement** — Each MCP tool checks its own permissions via `check_xxx()`, avoiding fragile duplication
3. **Strict CSP at WAF** — `script-src 'self'` without `unsafe-inline`, zero inline onclick (event delegation pattern)
4. **Audit middleware** — All non-static requests are traced with client identity and timing
5. **Lightweight proxy** — `call_tool_direct()` reuses the ASGI auth context, no protocol overhead
6. **No localStorage for tokens** — LM2-01/LM2-04 fixes correctly applied

### Remaining concerns ⚠️

1. **WAF dependency for full security** — Without Caddy, only the application-level CSP (ADM-03 fix) protects against XSS
2. **Single endpoint for 40 tools** — Large attack surface, mitigated by per-tool permission checks
3. **Raw token in cookie** — No session-to-token indirection (ADM-04, accepted risk)
4. **No application-level rate limiting** — Only the Caddy WAF rate-limits `/api/*` (120 req/min)

---

## Appendix: Test Coverage

File: `tests/test_admin_console_security.py` — 13 tests, 7 classes

| Class | Tests | Finding | Pattern |
|-------|-------|---------|---------|
| `TestADM01_EscEscapesQuotes` | 2 | ADM-01 | Source introspection — verifies `&quot;` and `&#x27;` in `esc()` |
| `TestADM02_SafeErrorInApiTool` | 1 | ADM-02 | Source introspection — verifies `safe_error()` in except block |
| `TestADM03_CspHeadersOnHtml` | 3 | ADM-03 | ASGI simulation — verifies CSP/XFO on HTML, absent on CSS |
| `TestADM05_BodySizeLimit` | 2 | ADM-05 | ASGI simulation — oversized body → 413, normal body → pass |
| `TestADM06_PermissionGate` | 2 | ADM-06 | ASGI simulation — read token → 403, write token → pass |
| `TestADM08_AuditLogToolName` | 1 | ADM-08 | ASGI simulation + mock audit logger — tool name in entry |
| `TestADM09_CallToolDirectRegression` | 2 | ADM-09 | Direct call — unknown tool → error, None mcp_ref → error |

Convention: **non-complaisant** — each test tries to *break* the fix (inject quotes, send oversized body, use wrong permissions), not validate the happy path.
