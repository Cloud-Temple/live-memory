# -*- coding: utf-8 -*-
"""MCP v2 runtime contract: transport security, tool wire shape, and lifecycle."""

import asyncio
import hashlib
import importlib
import inspect
import json
import logging
from pathlib import Path
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import httpx2
import pytest
from starlette.testclient import TestClient

from live_mem.config import Settings, get_settings


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_KEY = "change_me_in_production"
VALID_HOST = "localhost:8002"
VALID_ORIGIN = f"http://{VALID_HOST}"
V1_27_CONTRACT_SHA256 = {
    name: digest
    for digest, name in (
        line.split(maxsplit=1)
        for line in (ROOT / "tests/mcp_compat/v1_27_tool_contract.sha256")
        .read_text(encoding="utf-8")
        .splitlines()
    )
}
TEST_SETTINGS = Settings(
    _env_file=None,
    admin_bootstrap_key=BOOTSTRAP_KEY,
    mcp_allowed_hosts=VALID_HOST,
    mcp_allowed_origins=VALID_ORIGIN,
    # Explicit empty values make accidental storage or LLM initialization fail
    # locally instead of inheriting developer credentials from .env.
    s3_endpoint_url="",
    s3_access_key_id="",
    s3_secret_access_key="",
    llmaas_api_url="",
    llmaas_api_key="",
)
_server_module = None


def _server():
    assert _server_module is not None, "the isolated server fixture must run first"
    return _server_module


@pytest.fixture(autouse=True)
def isolate_mcp_runtime(monkeypatch):
    """Never inherit the developer .env or its S3-backed token validation."""
    global _server_module
    token_service = SimpleNamespace(
        validate_token=AsyncMock(side_effect=AssertionError("storage is forbidden in this test"))
    )
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    if _server_module is None:
        _server_module = importlib.import_module("live_mem.server")
    monkeypatch.setattr(_server_module, "settings", TEST_SETTINGS)
    monkeypatch.setattr("live_mem.auth.middleware.get_settings", lambda: TEST_SETTINGS)
    monkeypatch.setattr("live_mem.core.tokens.get_token_service", lambda: token_service)
    return token_service


def _mcp_response(headers: dict[str, str], body: bytes = b"{}") -> httpx.Response:
    with TestClient(_server().create_app(), base_url=f"http://{VALID_HOST}") as client:
        return client.post("/mcp", headers=headers, content=body)


def test_v2_tool_catalog_exposes_44_tools_with_legacy_wire_annotations():
    tools = asyncio.run(_server().mcp.list_tools())

    assert len(tools) == 44
    assert all((tool.description or "").strip() for tool in tools)
    annotations = next(tool.annotations for tool in tools if tool.name == "system_about")
    assert annotations is not None
    assert annotations.model_dump(by_alias=True)["readOnlyHint"] is True


def _serialize_tool_contract(tools, *, normalize_docstrings: bool) -> bytes:
    """Serialize the v1 tool contract independently of Python docstring quirks."""
    payload = [
        {
            "annotations": tool.annotations.model_dump(by_alias=True, exclude_none=True)
            if tool.annotations
            else None,
            "description": inspect.cleandoc(tool.description or "")
            if normalize_docstrings
            else tool.description,
            "input_schema": tool.input_schema,
            "name": tool.name,
            "title": tool.title,
        }
        for tool in tools
    ]
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode() + b"\n"


def test_v2_tool_contract_matches_the_committed_mcp_v1_27_golden():
    """The golden was captured from main at a63c432, before this migration."""
    tools = asyncio.run(_server().mcp.list_tools())
    if sys.version_info[:2] == (3, 11):
        # The delivered image uses Python 3.11; retain its exact v1 bytes.
        assert hashlib.sha256(
            _serialize_tool_contract(tools, normalize_docstrings=False)
        ).hexdigest() == V1_27_CONTRACT_SHA256["mcp-v1.27-tool-contract.json"]

    # Python 3.13 dedents a function __doc__; this semantic form is identical
    # across the project-supported Python versions.
    assert hashlib.sha256(
        _serialize_tool_contract(tools, normalize_docstrings=True)
    ).hexdigest() == V1_27_CONTRACT_SHA256["mcp-v1.27-tool-contract-portable.json"]


def test_mcp_transport_rejects_a_missing_bearer_without_storage_access(isolate_mcp_runtime):
    response = _mcp_response({"Host": VALID_HOST, "Content-Type": "application/json"})

    assert response.status_code == 401
    isolate_mcp_runtime.validate_token.assert_not_called()


def test_mcp_transport_rejects_an_invalid_bearer_without_leaking_token(
    isolate_mcp_runtime, caplog
):
    token = "isolated-invalid-bearer"
    isolate_mcp_runtime.validate_token.side_effect = None
    isolate_mcp_runtime.validate_token.return_value = None
    with caplog.at_level(logging.INFO):
        response = _mcp_response(
            {
                "Host": VALID_HOST,
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            }
        )

    assert response.status_code == 401
    isolate_mcp_runtime.validate_token.assert_awaited_once_with(token)
    assert token not in response.text
    assert token not in caplog.text


def test_mcp_transport_checks_host_after_valid_authentication():
    response = _mcp_response(
        {
            "Host": "invalid.example.test",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {BOOTSTRAP_KEY}",
        }
    )

    assert response.status_code == 421


def test_mcp_transport_rejects_an_untrusted_origin():
    response = _mcp_response(
        {
            "Host": VALID_HOST,
            "Origin": "https://invalid.example.test",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {BOOTSTRAP_KEY}",
        }
    )

    assert response.status_code == 403


def test_mcp_transport_accepts_an_absent_origin_after_authentication():
    response = _mcp_response(
        {
            "Host": VALID_HOST,
            "Content-Type": "application/json",
            "Authorization": f"Bearer {BOOTSTRAP_KEY}",
        }
    )

    # The deliberately incomplete JSON-RPC payload may be rejected by MCP, but
    # an absent Origin is not a DNS-rebinding rejection.
    assert response.status_code != 403


def test_transport_security_does_not_change_non_mcp_routes():
    with TestClient(_server().create_app(), base_url=f"http://{VALID_HOST}") as client:
        response = client.get(
            "/not-an-mcp-route",
            headers={"Host": "invalid.example.test", "Authorization": f"Bearer {BOOTSTRAP_KEY}"},
        )

    assert response.status_code == 404


def test_mcp_transport_limits_request_body_to_four_mebibytes():
    response = _mcp_response(
        {
            "Host": VALID_HOST,
            "Content-Type": "application/json",
            "Authorization": f"Bearer {BOOTSTRAP_KEY}",
        },
        b"x" * (4 * 1024 * 1024 + 1),
    )

    assert response.status_code == 413


@pytest.mark.parametrize(
    "field,value",
    [
        ("mcp_allowed_hosts", "*"),
        ("mcp_allowed_hosts", "*.example.test"),
        ("mcp_allowed_hosts", "*.example.test:*"),
        ("mcp_allowed_origins", "https://*.example.test"),
        ("mcp_allowed_origins", "https://example.test/path"),
    ],
)
def test_mcp_allowlists_reject_global_and_hostname_wildcards(field, value):
    with pytest.raises(ValueError):
        Settings.model_validate({field: value})


def test_outbound_clients_keep_redirects_and_standard_trust_store_enabled():
    for path in (ROOT / "src/live_mem/core/graph_bridge.py", ROOT / "scripts/cli/client.py"):
        source = path.read_text(encoding="utf-8")
        assert "streamable_http_client" in source
        assert "httpx2.AsyncClient" in source
        assert "follow_redirects=True" in source
        assert "trust_env=True" in source


@pytest.mark.parametrize(
    ("environment", "expected_keyword"),
    [
        ("SSL_CERT_FILE", "cafile"),
        ("SSL_CERT_DIR", "capath"),
    ],
)
def test_httpx2_honors_standard_tls_trust_store_environment(
    monkeypatch, environment, expected_keyword
):
    from httpx2 import _config

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setenv(environment, "/tmp/mcp-v2-test-ca")
    with patch("ssl.create_default_context") as create_context:
        _config.create_ssl_context(trust_env=True)

    assert create_context.call_args.kwargs == {expected_keyword: "/tmp/mcp-v2-test-ca"}


@pytest.mark.asyncio
async def test_outbound_graph_client_closes_httpx2_and_preserves_transport_options():
    from live_mem.core.graph_bridge import GraphMemoryClient

    class FakeHTTPClient:
        closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

    class FakeSession:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def initialize(self):
            return None

        async def call_tool(self, *_args):
            return SimpleNamespace(content=[SimpleNamespace(text='{"status":"ok"}')])

    @asynccontextmanager
    async def fake_transport(*_args, **_kwargs):
        yield object(), object()

    http_client = FakeHTTPClient()
    with (
        patch("live_mem.core.graph_bridge.httpx2.AsyncClient", return_value=http_client) as factory,
        patch("live_mem.core.graph_bridge.streamable_http_client", fake_transport),
        patch("live_mem.core.graph_bridge.ClientSession", FakeSession),
    ):
        result = await GraphMemoryClient("https://graph.example.test", "token", timeout=7).call_tool(
            "memory_list", {}
        )

    assert result == {"status": "ok"}
    assert http_client.closed is True
    assert factory.call_args.kwargs["follow_redirects"] is True
    assert factory.call_args.kwargs["trust_env"] is True


@pytest.mark.asyncio
async def test_httpx2_redirect_does_not_forward_bearer_authorization_to_another_origin():
    seen_authorization: list[str | None] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        seen_authorization.append(request.headers.get("authorization"))
        if request.url.host == "first.example.test":
            return httpx2.Response(302, headers={"Location": "https://second.example.test/final"})
        return httpx2.Response(200, text="ok")

    async with httpx2.AsyncClient(
        headers={"Authorization": "Bearer isolated-test-token"},
        follow_redirects=True,
        trust_env=True,
        transport=httpx2.MockTransport(handler),
    ) as client:
        response = await client.get("https://first.example.test/start")

    assert response.status_code == 200
    assert seen_authorization == ["Bearer isolated-test-token", None]


@pytest.mark.asyncio
async def test_httpx2_redirect_keeps_bearer_authorization_on_the_same_origin():
    seen_authorization: list[str | None] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        seen_authorization.append(request.headers.get("authorization"))
        if request.url.path == "/start":
            return httpx2.Response(302, headers={"Location": "/final"})
        return httpx2.Response(200, text="ok")

    async with httpx2.AsyncClient(
        headers={"Authorization": "Bearer isolated-test-token"},
        follow_redirects=True,
        trust_env=True,
        transport=httpx2.MockTransport(handler),
    ) as client:
        response = await client.get("https://same.example.test/start")

    assert response.status_code == 200
    assert seen_authorization == ["Bearer isolated-test-token", "Bearer isolated-test-token"]


def test_lifespan_closes_the_consolidator_once_without_background_work():
    close = AsyncMock()
    with patch("live_mem.core.consolidator.close_consolidator_if_initialized", close):
        async def exercise() -> None:
            async with _server()._lifespan(_server().mcp):
                pass

        asyncio.run(exercise())

    close.assert_awaited_once_with()
