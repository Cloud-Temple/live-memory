# -*- coding: utf-8 -*-
"""
Non-complaisant tests for admin console security fixes (ADM-01 to ADM-09).

Audit: AUDIT_ADMIN_CONSOLE_2026-05-16.md
Convention: each test tries to BREAK the fix, not validate the happy path.
Pattern: test_FIXNAME_blocks_ATTACK()
"""

import asyncio
import inspect
import json
import logging
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ═══════════════════════════════════════════════════════════════
# Helpers — ASGI simulation
# ═══════════════════════════════════════════════════════════════


def _make_receive(body: bytes):
    """Create an ASGI receive callable returning a single body chunk."""
    called = False

    async def receive():
        nonlocal called
        if not called:
            called = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


def _make_send():
    """Create an ASGI send callable that captures response messages."""
    messages: list[dict] = []

    async def send(msg):
        messages.append(msg)

    return send, messages


def _response_status(messages: list[dict]) -> int:
    """Extract HTTP status from captured ASGI messages."""
    for m in messages:
        if m.get("type") == "http.response.start":
            return m.get("status", 0)
    return 0


def _response_body(messages: list[dict]) -> dict:
    """Extract JSON body from captured ASGI messages."""
    for m in messages:
        if m.get("type") == "http.response.body":
            try:
                return json.loads(m.get("body", b"{}"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}
    return {}


def _response_headers(messages: list[dict]) -> dict[bytes, bytes]:
    """Extract headers dict from captured ASGI messages."""
    for m in messages:
        if m.get("type") == "http.response.start":
            return dict(m.get("headers", []))
    return {}


# ═══════════════════════════════════════════════════════════════
# ADM-01: esc() must escape quotes to prevent attribute injection
# ═══════════════════════════════════════════════════════════════


class TestADM01_EscEscapesQuotes:
    """ADM-01 CRITICAL: esc() in admin-app.js must escape both " and '."""

    def test_esc_blocks_double_quote_injection(self):
        """
        Attack: token name containing " breaks out of data-name="..."
        and injects a malicious data-action attribute.

        Verify: the esc() function source code includes &quot; replacement.
        """
        js_path = (
            Path(__file__).parent.parent
            / "src"
            / "live_mem"
            / "static"
            / "js"
            / "admin-app.js"
        )
        content = js_path.read_text()

        # Find the full esc function line (greedy — the function is one line)
        match = re.search(r"^const esc\s*=\s*s\s*=>.*$", content, re.MULTILINE)
        assert match, "esc() function not found in admin-app.js"
        esc_code = match.group()

        # The function MUST escape double quotes
        assert "&quot;" in esc_code, (
            f"ADM-01 BROKEN: esc() does not escape double quotes. "
            f"Attack: token name='foo\" data-action=\"confirm\"' "
            f"would inject arbitrary attributes. Source: {esc_code}"
        )

    def test_esc_blocks_single_quote_injection(self):
        """
        Attack: value containing ' breaks out of data-args='{"key":"val"}'
        (single-quoted HTML attribute used for JSON args).

        Verify: the esc() function source code includes &#x27; replacement.
        """
        js_path = (
            Path(__file__).parent.parent
            / "src"
            / "live_mem"
            / "static"
            / "js"
            / "admin-app.js"
        )
        content = js_path.read_text()
        match = re.search(r"^const esc\s*=\s*s\s*=>.*$", content, re.MULTILINE)
        assert match, "esc() function not found in admin-app.js"
        esc_code = match.group()

        assert "&#x27;" in esc_code, (
            f"ADM-01 BROKEN: esc() does not escape single quotes. "
            f"Attack: data-args='{{\"tool\":\"val'}}' injection. "
            f"Source: {esc_code}"
        )


# ═══════════════════════════════════════════════════════════════
# ADM-02: /api/tool must use safe_error(), not bare str(e)
# ═══════════════════════════════════════════════════════════════


class TestADM02_SafeErrorInApiTool:
    """ADM-02 HIGH: exception messages must not leak to client."""

    def test_api_tool_blocks_exception_leakage(self):
        """
        Attack: trigger an internal exception in /api/tool and verify
        the response does NOT contain the raw Python exception message
        (which would expose file paths, S3 endpoints, etc.).

        Verify: source code of _api_tool_call uses safe_error() in except block.
        """
        from live_mem.auth.middleware import StaticFilesMiddleware

        source = inspect.getsource(StaticFilesMiddleware._api_tool_call)

        # The except block must call safe_error(), not return str(e)
        assert "safe_error(" in source, (
            "ADM-02 BROKEN: _api_tool_call does not use safe_error(). "
            "A boto3 exception would expose the S3 endpoint URL to the client."
        )

        # And must NOT have the old pattern: "message": str(e)
        # We check the except block specifically
        except_idx = source.rfind("except Exception")
        assert except_idx > 0, "No except block found in _api_tool_call"
        except_block = source[except_idx:]
        assert '"message": str(e)' not in except_block, (
            "ADM-02 BROKEN: _api_tool_call still contains 'message: str(e)' "
            "in the except block. This leaks raw exception messages."
        )


# ═══════════════════════════════════════════════════════════════
# ADM-03: HTML pages must include CSP headers (defense-in-depth)
# ═══════════════════════════════════════════════════════════════


class TestADM03_CspHeadersOnHtml:
    """ADM-03 HIGH: _serve_file must add CSP on HTML, not rely on WAF."""

    @pytest.mark.asyncio
    async def test_admin_html_has_csp_header(self):
        """
        Attack: access the app directly on port 8002 (bypass WAF).
        Without CSP, any XSS is directly exploitable.

        Verify: serving admin.html includes Content-Security-Policy header.
        """
        from live_mem.auth.middleware import StaticFilesMiddleware

        m = StaticFilesMiddleware(None)
        send_fn, messages = _make_send()
        await m._serve_file(send_fn, "admin.html", "text/html; charset=utf-8")

        headers = _response_headers(messages)
        csp = headers.get(b"content-security-policy", b"").decode()

        assert csp, (
            "ADM-03 BROKEN: admin.html served without Content-Security-Policy. "
            "Without WAF, the console has ZERO XSS protection."
        )
        assert "script-src 'self'" in csp, (
            "ADM-03 BROKEN: CSP does not contain script-src 'self'. "
            "Inline scripts or external scripts could execute."
        )
        assert "frame-ancestors 'none'" in csp, (
            "ADM-03 BROKEN: CSP missing frame-ancestors 'none'. "
            "The admin page could be embedded in an attacker's iframe."
        )

    @pytest.mark.asyncio
    async def test_css_file_has_no_csp_header(self):
        """CSP headers should only be added to HTML, not CSS/JS/images."""
        from live_mem.auth.middleware import StaticFilesMiddleware

        m = StaticFilesMiddleware(None)
        send_fn, messages = _make_send()
        await m._serve_file(send_fn, "css/admin.css", "text/css; charset=utf-8")

        headers = _response_headers(messages)
        assert b"content-security-policy" not in headers, (
            "CSP header should NOT be added to non-HTML files"
        )

    @pytest.mark.asyncio
    async def test_xframe_options_on_html(self):
        """Verify X-Frame-Options: DENY is set on HTML pages."""
        from live_mem.auth.middleware import StaticFilesMiddleware

        m = StaticFilesMiddleware(None)
        send_fn, messages = _make_send()
        await m._serve_file(send_fn, "admin.html", "text/html; charset=utf-8")

        headers = _response_headers(messages)
        xfo = headers.get(b"x-frame-options", b"").decode()
        assert xfo == "DENY", (
            f"ADM-03 BROKEN: X-Frame-Options is '{xfo}' instead of 'DENY'"
        )


# ═══════════════════════════════════════════════════════════════
# ADM-05: /api/tool must reject oversized request bodies
# ═══════════════════════════════════════════════════════════════


class TestADM05_BodySizeLimit:
    """ADM-05 MEDIUM: /api/tool must reject bodies > api_tool_max_body_bytes."""

    @pytest.mark.asyncio
    async def test_api_tool_blocks_oversized_body(self):
        """
        Attack: send a multi-MB body to /api/tool to exhaust server memory.

        Verify: response is 413 Request Entity Too Large.
        """
        from live_mem.auth.middleware import StaticFilesMiddleware
        from live_mem.auth.context import current_token_info

        m = StaticFilesMiddleware(None)

        # Auth context: admin (so permission gate passes)
        tok = current_token_info.set(
            {
                "type": "token",
                "client_name": "attacker",
                "permissions": ["read", "write", "admin"],
                "allowed_resources": [],
                "token_hash": "abc123deadbeef0000",
            }
        )

        # Craft a body exceeding default 1 MB limit
        oversized = b"x" * (1_048_576 + 1024)  # 1 MB + 1 KB
        receive = _make_receive(oversized)
        send_fn, messages = _make_send()

        try:
            await m._api_tool_call(receive, send_fn)
        finally:
            current_token_info.reset(tok)

        status = _response_status(messages)
        assert status == 413, (
            f"ADM-05 BROKEN: oversized body got status {status} instead of 413. "
            f"A 2 GB POST to /api/tool would exhaust server memory."
        )

    @pytest.mark.asyncio
    async def test_api_tool_accepts_normal_body(self):
        """A normal-sized body should NOT be rejected by the size limit."""
        from live_mem.auth.middleware import StaticFilesMiddleware
        from live_mem.auth.context import current_token_info

        m = StaticFilesMiddleware(None)

        tok = current_token_info.set(
            {
                "type": "token",
                "client_name": "test",
                "permissions": ["read", "write"],
                "allowed_resources": [],
                "token_hash": "abc123deadbeef0000",
            }
        )

        body = json.dumps({"tool": "system_health", "arguments": {}}).encode()
        receive = _make_receive(body)
        send_fn, messages = _make_send()

        try:
            with patch("live_mem.tools.call_tool_direct") as mock_call:
                mock_call.return_value = {"status": "ok"}
                await m._api_tool_call(receive, send_fn)
        finally:
            current_token_info.reset(tok)

        status = _response_status(messages)
        assert status != 413, (
            f"Normal body of {len(body)} bytes was rejected with 413"
        )


# ═══════════════════════════════════════════════════════════════
# ADM-06: /api/tool must require write permission minimum
# ═══════════════════════════════════════════════════════════════


class TestADM06_PermissionGate:
    """ADM-06 MEDIUM: read-only tokens must be blocked from /api/tool."""

    @pytest.mark.asyncio
    async def test_api_tool_blocks_readonly_token(self):
        """
        Attack: a read-only token tries to call /api/tool to probe
        tool existence and enumerate the admin API.

        Verify: response is 403 with permission error.
        """
        from live_mem.auth.middleware import StaticFilesMiddleware
        from live_mem.auth.context import current_token_info

        m = StaticFilesMiddleware(None)

        # Read-only token — should be blocked
        tok = current_token_info.set(
            {
                "type": "token",
                "client_name": "readonly-spy",
                "permissions": ["read"],
                "allowed_resources": [],
                "token_hash": "readonly1234567890ab",
            }
        )

        body = json.dumps({"tool": "system_health", "arguments": {}}).encode()
        receive = _make_receive(body)
        send_fn, messages = _make_send()

        try:
            await m._api_tool_call(receive, send_fn)
        finally:
            current_token_info.reset(tok)

        status = _response_status(messages)
        resp = _response_body(messages)

        assert status == 403, (
            f"ADM-06 BROKEN: read-only token got status {status} instead of 403. "
            f"A read token can enumerate all 40 MCP tools via /api/tool."
        )
        assert "write" in resp.get("message", "").lower(), (
            f"ADM-06: error message should mention 'write' permission requirement"
        )

    @pytest.mark.asyncio
    async def test_api_tool_allows_write_token(self):
        """A write token must be allowed through the permission gate."""
        from live_mem.auth.middleware import StaticFilesMiddleware
        from live_mem.auth.context import current_token_info

        m = StaticFilesMiddleware(None)

        tok = current_token_info.set(
            {
                "type": "token",
                "client_name": "writer",
                "permissions": ["read", "write"],
                "allowed_resources": [],
                "token_hash": "writer1234567890ab",
            }
        )

        body = json.dumps({"tool": "system_health", "arguments": {}}).encode()
        receive = _make_receive(body)
        send_fn, messages = _make_send()

        try:
            with patch("live_mem.tools.call_tool_direct") as mock_call:
                mock_call.return_value = {"status": "ok"}
                await m._api_tool_call(receive, send_fn)
        finally:
            current_token_info.reset(tok)

        status = _response_status(messages)
        assert status != 403, (
            f"ADM-06 over-correction: write token blocked with {status}"
        )


# ═══════════════════════════════════════════════════════════════
# ADM-08: Audit trail must log tool name and argument keys
# ═══════════════════════════════════════════════════════════════


class TestADM08_AuditLogToolName:
    """ADM-08 MEDIUM: /api/tool must emit audit log with tool name."""

    @pytest.mark.asyncio
    async def test_api_tool_logs_tool_name_in_audit(self):
        """
        Attack: admin deletes a space via /api/tool but audit only shows
        "POST /api/tool" — impossible to know what tool was called.

        Verify: audit logger emits an entry with the tool name.
        """
        from live_mem.auth.middleware import StaticFilesMiddleware
        from live_mem.auth.context import current_token_info

        m = StaticFilesMiddleware(None)

        tok = current_token_info.set(
            {
                "type": "token",
                "client_name": "admin-user",
                "permissions": ["read", "write", "admin"],
                "allowed_resources": [],
                "token_hash": "admin1234567890abc",
            }
        )

        body = json.dumps(
            {"tool": "space_delete", "arguments": {"space_id": "test", "confirm": True}}
        ).encode()
        receive = _make_receive(body)
        send_fn, messages = _make_send()

        audit_entries: list[str] = []
        with patch("live_mem.auth.middleware.audit_logger") as mock_audit:
            mock_audit.info = lambda msg: audit_entries.append(msg)
            with patch("live_mem.tools.call_tool_direct") as mock_call:
                mock_call.return_value = {"status": "ok"}
                try:
                    await m._api_tool_call(receive, send_fn)
                finally:
                    current_token_info.reset(tok)

        # Find the admin_tool_call audit entry
        tool_call_entries = [
            e for e in audit_entries if "admin_tool_call" in e
        ]
        assert tool_call_entries, (
            "ADM-08 BROKEN: no audit entry with event=admin_tool_call found. "
            "A destructive action via /api/tool leaves no traceable audit trail."
        )

        entry = json.loads(tool_call_entries[0])
        assert entry.get("tool") == "space_delete", (
            f"ADM-08 BROKEN: audit entry tool={entry.get('tool')} instead of 'space_delete'"
        )
        assert "space_id" in entry.get("arguments_keys", []), (
            "ADM-08 BROKEN: audit entry missing argument keys"
        )
        assert entry.get("client") == "admin-user", (
            f"ADM-08 BROKEN: audit entry client={entry.get('client')} instead of 'admin-user'"
        )


# ═══════════════════════════════════════════════════════════════
# ADM-09: call_tool_direct must handle unknown tools safely
# ═══════════════════════════════════════════════════════════════


class TestADM09_CallToolDirectRegression:
    """ADM-09 LOW: call_tool_direct must return clean error for unknown tools."""

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        """
        Verify: calling a non-existent tool returns a structured error,
        not a crash or an internal stack trace.
        """
        from live_mem import tools
        from live_mem.tools import call_tool_direct

        # Mock _mcp_ref with a fake tool manager (server not started in tests)
        mock_mcp = MagicMock()
        mock_mcp._tool_manager._tools = {}  # empty registry
        original = tools._mcp_ref
        tools._mcp_ref = mock_mcp
        try:
            result = await call_tool_direct("__nonexistent_tool_xss__", {})
        finally:
            tools._mcp_ref = original

        assert result.get("status") == "error", (
            "ADM-09: unknown tool should return status=error"
        )
        assert "__nonexistent_tool_xss__" in result.get("message", ""), (
            "ADM-09: error message should mention the unknown tool name"
        )

    @pytest.mark.asyncio
    async def test_uninitialized_mcp_returns_error(self):
        """If _mcp_ref is None (server not started), must not crash."""
        from live_mem import tools

        original = tools._mcp_ref
        tools._mcp_ref = None
        try:
            result = await tools.call_tool_direct("anything", {})
            assert result.get("status") == "error", (
                "ADM-09: uninitialized _mcp_ref should return error, not crash"
            )
        finally:
            tools._mcp_ref = original
