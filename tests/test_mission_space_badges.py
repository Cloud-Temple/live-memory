"""Tests d'intégrité pour les badges individuels de spaces de mission.

Ces tests attaquent les invariants du contrat v2.9.0 : autorité technique du
créateur, portée d'un seul space, révocation, et absence de surface auxiliaire.
Ils n'essaient pas de simuler mcp-mission ou mcp-agent : Live Memory ne connaît
ni leurs missions ni leurs sous-agents.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import io
import inspect
import json
import tarfile
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from live_mem.auth.context import (
    _fresh_token_store,
    _get_effective_token_info,
    _invalidated_token_hashes,
    current_token_info,
    update_fresh_token,
)
from live_mem.auth.middleware import AuthMiddleware, StaticFilesMiddleware
from live_mem.core.locks import LockManager
from live_mem.core.models import SpaceMeta, TokenInfo, TokensStore, mask_meta_secrets
from live_mem.core.space import SpaceService
from live_mem.core.tokens import (
    SPACE_BADGE_MAX_ACTIVE,
    TokenService,
)
from live_mem.tools import register_all_tools
from live_mem.tools.space import register as register_space_tools


MISSION_SPACE = "mis_42"
CREATOR_HASH = "sha256:" + "a" * 64
OTHER_HASH = "sha256:" + "b" * 64
BADGE_HASH = "sha256:" + "c" * 64

BADGE_ALLOWED_TOOLS = {"system_whoami", "live_read", "live_note"}
ALL_TOOL_NAMES = {
    "admin_bulk_update_tokens",
    "admin_create_token",
    "admin_delete_token",
    "admin_gc_notes",
    "admin_list_tokens",
    "admin_purge_tokens",
    "admin_revoke_token",
    "admin_update_token",
    "backup_create",
    "backup_delete",
    "backup_download",
    "backup_list",
    "backup_restore",
    "bank_compact",
    "bank_consolidate",
    "bank_consolidation_queues",
    "bank_consolidation_status",
    "bank_delete",
    "bank_list",
    "bank_read",
    "bank_read_all",
    "bank_repair",
    "bank_stale_spaces",
    "bank_write",
    "graph_connect",
    "graph_disconnect",
    "graph_push",
    "graph_status",
    "live_note",
    "live_read",
    "live_search",
    "space_badge_mint",
    "space_create",
    "space_delete",
    "space_export",
    "space_info",
    "space_list",
    "space_rules",
    "space_summary",
    "space_update",
    "space_update_rules",
    "system_about",
    "system_health",
    "system_whoami",
}


@pytest.fixture(autouse=True)
def _clean_fresh_token_state():
    _fresh_token_store.clear()
    _invalidated_token_hashes.clear()
    yield
    _fresh_token_store.clear()
    _invalidated_token_hashes.clear()


def _badge_context(space_id: str = MISSION_SPACE) -> dict:
    return {
        "type": "token",
        "token_kind": "space_badge",
        "client_name": "agent-worker-42",
        "permissions": [],
        "allowed_resources": [space_id],
        "token_hash": BADGE_HASH,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }


class MemoryStorage:
    """Petit faux S3 explicite, suffisant aux invariants de SpaceService."""

    def __init__(self):
        self.objects: dict[str, object] = {}

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def put(self, key: str, value: str) -> None:
        self.objects[key] = value

    async def put_json(self, key: str, value: dict) -> None:
        self.objects[key] = copy.deepcopy(value)

    async def get_json(self, key: str):
        value = self.objects.get(key)
        return copy.deepcopy(value) if isinstance(value, dict) else None

    async def list_objects(self, prefix: str) -> list[dict]:
        return [{"Key": key} for key in self.objects if key.startswith(prefix)]

    async def list_and_get(self, prefix: str, exclude_keep: bool = False) -> list[dict]:
        result = []
        for key, content in self.objects.items():
            if not key.startswith(prefix) or (exclude_keep and key.endswith(".keep")):
                continue
            raw = content if isinstance(content, str) else json.dumps(content)
            result.append({"key": key, "content": raw, "size": len(raw.encode())})
        return result

    async def delete_many(self, keys: list[str]) -> int:
        for key in keys:
            self.objects.pop(key, None)
        return len(keys)


class FailingKeepStorage(MemoryStorage):
    async def put(self, key: str, value: str) -> None:
        if key.endswith("bank/.keep"):
            raise OSError("simulated S3 failure")
        await super().put(key, value)


@pytest.mark.asyncio
async def test_badge_is_single_space_ttl_bound_and_remint_revokes_previous():
    service = TokenService()
    store = TokensStore()

    with patch.object(service, "_load_store", AsyncMock(return_value=store)), patch.object(
        service, "_save_store", AsyncMock()
    ):
        first = await service.mint_space_badge(MISSION_SPACE, "agent-1")
        second = await service.mint_space_badge(MISSION_SPACE, "agent-1")
        old_info = await service.validate_token(first["token"])
        new_info = await service.validate_token(second["token"])

    assert first["status"] == "created"
    assert second["replaced"] is True
    assert old_info is None, "Le badge remplacé ne doit jamais rester utilisable"
    assert new_info["token_kind"] == "space_badge"
    assert new_info["permissions"] == []
    assert new_info["allowed_resources"] == [MISSION_SPACE]
    assert store.tokens[0].revoked is True
    assert store.tokens[1].expires_at is not None


@pytest.mark.asyncio
async def test_badge_expired_does_not_consume_quota_and_badge_over_quota_is_refused():
    service = TokenService()
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    active = [
        TokenInfo(
            hash=f"sha256:{i:064x}",
            kind="space_badge",
            name=f"agent-{i}",
            space_ids=[MISSION_SPACE],
            expires_at=future,
        )
        for i in range(SPACE_BADGE_MAX_ACTIVE - 1)
    ]
    expired = TokenInfo(
        hash="sha256:" + "e" * 64,
        kind="space_badge",
        name="expired",
        space_ids=[MISSION_SPACE],
        expires_at=past,
    )
    store = TokensStore(tokens=[*active, expired])

    with patch.object(service, "_load_store", AsyncMock(return_value=store)), patch.object(
        service, "_save_store", AsyncMock()
    ):
        accepted = await service.mint_space_badge(MISSION_SPACE, "agent-new")
        refused = await service.mint_space_badge(MISSION_SPACE, "agent-overflow")

    assert accepted["status"] == "created"
    assert expired.revoked is True
    assert refused["status"] == "error"
    assert "Plafond" in refused["message"]


@pytest.mark.asyncio
async def test_remint_tombstone_blocks_a_stale_mcp_session():
    service = TokenService()
    old = TokenInfo(
        hash=BADGE_HASH,
        kind="space_badge",
        name="agent-1",
        space_ids=[MISSION_SPACE],
        expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    store = TokensStore(tokens=[old])
    stale_context = _badge_context()
    context_token = current_token_info.set(stale_context)
    update_fresh_token(stale_context)
    try:
        with patch.object(service, "_load_store", AsyncMock(return_value=store)), patch.object(
            service, "_save_store", AsyncMock()
        ):
            result = await service.mint_space_badge(MISSION_SPACE, "agent-1")
        assert result["status"] == "created"
        assert _get_effective_token_info() is None
    finally:
        current_token_info.reset(context_token)


@pytest.mark.asyncio
async def test_late_badge_validation_cannot_clear_its_remint_tombstone():
    service = TokenService()
    raw_badge = "old-badge-secret"
    old = TokenInfo(
        hash="sha256:" + hashlib.sha256(raw_badge.encode()).hexdigest(),
        kind="space_badge",
        name="agent-1",
        space_ids=[MISSION_SPACE],
        expires_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    )
    store = TokensStore(tokens=[old])

    with patch.object(service, "_load_store", AsyncMock(return_value=store)), patch.object(
        service, "_save_store", AsyncMock()
    ):
        # Simule une requête HTTP qui a validé le badge juste avant le re-mint
        # mais n'a pas encore publié son contexte frais.
        stale_info = await service.validate_token(raw_badge)
        assert stale_info is not None
        assert (await service.mint_space_badge(MISSION_SPACE, "agent-1"))["status"] == "created"

    token = current_token_info.set(stale_info)
    try:
        update_fresh_token(stale_info)
        assert _get_effective_token_info() is None
    finally:
        current_token_info.reset(token)


@pytest.mark.asyncio
async def test_expired_badge_context_is_refused_inside_an_open_mcp_session():
    mcp = FastMCP(name="expired-badge")
    register_all_tools(mcp)
    badge = _badge_context()
    badge["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    token = current_token_info.set(badge)
    try:
        tools = mcp._tool_manager._tools
        assert (await _tool_callable(tools["system_whoami"])())["status"] == "error"
        assert (
            await _tool_callable(tools["live_read"])(space_id=MISSION_SPACE)
        )["status"] == "error"
        assert (
            await _tool_callable(tools["live_note"])(
                space_id=MISSION_SPACE, category="progress", content="expired"
            )
        )["status"] == "error"
    finally:
        current_token_info.reset(token)


@pytest.mark.asyncio
async def test_legacy_standard_token_stays_standard_after_schema_extension():
    service = TokenService()
    raw_token = "legacy-standard-token"
    token = TokenInfo(
        hash="sha256:" + hashlib.sha256(raw_token.encode()).hexdigest(),
        name="legacy-agent",
        permissions=["read", "write"],
        space_ids=[MISSION_SPACE],
    )
    store = TokensStore(tokens=[token])
    with patch.object(service, "_load_store", AsyncMock(return_value=store)):
        result = await service.validate_token(raw_token)

    assert token.kind == "standard"
    assert result["token_kind"] == "standard"
    assert result["permissions"] == ["read", "write"]


@pytest.mark.asyncio
async def test_space_meta_is_last_and_creator_proof_is_exact():
    storage = FailingKeepStorage()
    service = SpaceService()
    with patch("live_mem.core.space.get_storage", return_value=storage):
        with pytest.raises(OSError):
            await service.create(MISSION_SPACE, "mission", "# rules", creator_token_hash=CREATOR_HASH)
        assert f"{MISSION_SPACE}/_meta.json" not in storage.objects

    storage = MemoryStorage()
    with patch("live_mem.core.space.get_storage", return_value=storage):
        created = await service.create(
            MISSION_SPACE, "mission", "# rules", creator_token_hash=CREATOR_HASH
        )
        assert created["status"] == "created"
        assert await service.caller_is_creator(MISSION_SPACE, CREATOR_HASH) is True
        assert await service.caller_is_creator(MISSION_SPACE, OTHER_HASH) is False
        assert await service.caller_is_creator(MISSION_SPACE, None) is False


@pytest.mark.asyncio
async def test_legacy_or_bootstrap_space_cannot_mint_a_badge():
    storage = MemoryStorage()
    storage.objects[f"{MISSION_SPACE}/_meta.json"] = SpaceMeta(
        space_id=MISSION_SPACE,
        description="legacy",
    ).model_dump()
    token_service = MagicMock()
    token_service.mint_space_badge = AsyncMock()
    service = SpaceService()

    with patch("live_mem.core.space.get_storage", return_value=storage), patch(
        "live_mem.core.tokens.get_token_service", return_value=token_service
    ):
        result = await service.mint_badge(MISSION_SPACE, CREATOR_HASH, "agent-1")

    assert result["status"] == "error"
    token_service.mint_space_badge.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_serializes_with_mint_and_revokes_the_badge_before_recreation():
    storage = MemoryStorage()
    storage.objects[f"{MISSION_SPACE}/_meta.json"] = SpaceMeta(
        space_id=MISSION_SPACE,
        creator_token_hash=CREATOR_HASH,
    ).model_dump()
    storage.objects[f"{MISSION_SPACE}/_rules.md"] = "# rules"
    minted: list[str] = []
    revoked: list[str] = []
    mint_started = asyncio.Event()
    release_mint = asyncio.Event()

    class TokenServiceForRace:
        async def mint_space_badge(self, _space_id, _client_name):
            mint_started.set()
            await release_mint.wait()
            minted.append("badge")
            return {"status": "created"}

        async def revoke_space_badges(self, _space_id):
            revoked.extend(minted)
            return {"status": "ok", "revoked": len(minted)}

    service = SpaceService()
    fake_tokens = TokenServiceForRace()
    with patch("live_mem.core.space.get_storage", return_value=storage), patch(
        "live_mem.core.tokens.get_token_service", return_value=fake_tokens
    ):
        mint_task = asyncio.create_task(
            service.mint_badge(MISSION_SPACE, CREATOR_HASH, "agent-1")
        )
        await mint_started.wait()
        delete_task = asyncio.create_task(service.delete(MISSION_SPACE))
        await asyncio.sleep(0)
        release_mint.set()
        await mint_task
        deleted = await delete_task

    assert deleted["status"] == "deleted"
    assert minted == ["badge"]
    assert revoked == ["badge"], "La suppression doit révoquer un mint concurrent"
    assert f"{MISSION_SPACE}/_meta.json" not in storage.objects


@pytest.mark.asyncio
async def test_delete_stops_before_s3_when_badge_revocation_cannot_persist():
    storage = MemoryStorage()
    storage.objects[f"{MISSION_SPACE}/_meta.json"] = SpaceMeta(
        space_id=MISSION_SPACE,
        creator_token_hash=CREATOR_HASH,
    ).model_dump()
    token_service = MagicMock()
    token_service.revoke_space_badges = AsyncMock(
        return_value={"status": "error", "message": "token store unavailable"}
    )
    service = SpaceService()

    with patch("live_mem.core.space.get_storage", return_value=storage), patch(
        "live_mem.core.tokens.get_token_service", return_value=token_service
    ):
        result = await service.delete(MISSION_SPACE)

    assert result["status"] == "error"
    assert f"{MISSION_SPACE}/_meta.json" in storage.objects


def _space_tool(name: str):
    mcp = FastMCP(name="space-create-retry")
    register_space_tools(mcp)
    return _tool_callable(mcp._tool_manager._tools[name])


@pytest.mark.asyncio
async def test_creator_can_retry_space_create_after_auto_access_write_failure():
    space_service = MagicMock()
    space_service.create = AsyncMock(
        side_effect=[
            {"status": "created", "space_id": MISSION_SPACE},
            {"status": "already_exists", "space_id": MISSION_SPACE},
        ]
    )
    space_service.ensure_creator_access = AsyncMock(
        side_effect=[
            {"status": "error", "message": "write failed"},
            {"status": "ok", "message": "Space added to token"},
        ]
    )
    creator_context = {
        "type": "token",
        "token_kind": "standard",
        "client_name": "creator",
        "permissions": ["write"],
        "allowed_resources": [],
        "token_hash": CREATOR_HASH,
    }
    token = current_token_info.set(creator_context)
    try:
        with patch("live_mem.core.space.get_space_service", return_value=space_service):
            first = await _space_tool("space_create")(
                space_id=MISSION_SPACE, description="mission", rules="# rules"
            )
            second = await _space_tool("space_create")(
                space_id=MISSION_SPACE, description="mission", rules="# rules"
            )
    finally:
        current_token_info.reset(token)

    assert first["creator_access_pending"] is True
    assert second["status"] == "already_exists"
    assert second["creator_access_repair"] is True
    assert second["token_auto_updated"] is True


@pytest.mark.asyncio
async def test_creator_access_repair_serializes_with_delete_and_recreation():
    storage = MemoryStorage()
    storage.objects[f"{MISSION_SPACE}/_meta.json"] = SpaceMeta(
        space_id=MISSION_SPACE,
        creator_token_hash=CREATOR_HASH,
    ).model_dump()
    access_started = asyncio.Event()
    release_access = asyncio.Event()
    order: list[str] = []

    class TokenServiceForAccessRace:
        async def add_space_to_token(self, **_kwargs):
            access_started.set()
            await release_access.wait()
            order.append("access")
            return {"status": "ok", "message": "Space added to token"}

        async def revoke_space_badges(self, _space_id):
            order.append("revoke")
            return {"status": "ok", "revoked": 0}

    service = SpaceService()
    fake_tokens = TokenServiceForAccessRace()
    lock_manager = LockManager()
    with patch("live_mem.core.space.get_storage", return_value=storage), patch(
        "live_mem.core.space.get_lock_manager", return_value=lock_manager
    ), patch("live_mem.core.tokens.get_token_service", return_value=fake_tokens):
        repair_task = asyncio.create_task(
            service.ensure_creator_access(MISSION_SPACE, CREATOR_HASH)
        )
        await access_started.wait()
        delete_task = asyncio.create_task(service.delete(MISSION_SPACE))
        await asyncio.sleep(0)
        assert not delete_task.done(), "La suppression doit attendre la persistance de l'accès"
        release_access.set()
        assert (await repair_task)["status"] == "ok"
        assert (await delete_task)["status"] == "deleted"

    assert order == ["access", "revoke"]


def test_metadata_masking_never_exports_creator_hash():
    source = {
        "space_id": MISSION_SPACE,
        "creator_token_hash": CREATOR_HASH,
        "graph_memory": {"token": "very-secret-token"},
    }
    masked = mask_meta_secrets(source)

    assert masked["creator_token_hash"] == "***"
    assert masked["graph_memory"]["token"] == "very-sec..."
    assert source["creator_token_hash"] == CREATOR_HASH


@pytest.mark.asyncio
async def test_malformed_metadata_never_leaks_through_space_export():
    storage = MemoryStorage()
    storage.objects[f"{MISSION_SPACE}/_meta.json"] = (
        '{"creator_token_hash":"' + CREATOR_HASH + '"'
    )
    storage.objects[f"{MISSION_SPACE}/_rules.md"] = "# rules"
    service = SpaceService()

    with patch("live_mem.core.space.get_storage", return_value=storage):
        result = await service.export_space(MISSION_SPACE)

    archive = base64.b64decode(result["archive_base64"])
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        meta = tar.extractfile("_meta.json").read().decode()
    assert meta == "{}"
    assert CREATOR_HASH not in archive.decode("latin1")


def _tool_callable(tool):
    for attr in ("fn", "func", "handler", "_fn", "run", "callback"):
        candidate = getattr(tool, attr, None)
        if callable(candidate):
            return candidate
    raise AssertionError(f"Tool {tool.name} has no callable")


def _blocked_tool_args(fn) -> dict:
    text_args = {
        "space_id": MISSION_SPACE,
        "description": "x",
        "rules": "# x",
        "owner": "x",
        "client_name": "agent-x",
        "filename": "x.md",
        "content": "x",
        "category": "progress",
        "query": "x",
        "agent": "x",
        "job_id": "job-x",
        "backup_id": f"{MISSION_SPACE}/2026-01-01T00-00-00",
        "url": "https://example.test",
        "token": "x",
        "memory_id": "x",
        "ontology": "general",
        "token_hash": "sha256:" + "0" * 16,
        "name": "x",
        "permissions": "read",
    }
    args = {}
    for parameter in inspect.signature(fn).parameters.values():
        if parameter.default is not inspect.Parameter.empty:
            continue
        if parameter.name in text_args:
            args[parameter.name] = text_args[parameter.name]
        elif parameter.annotation is bool:
            args[parameter.name] = False
        elif parameter.annotation is int:
            args[parameter.name] = 1
        else:
            args[parameter.name] = "x"
    return args


@pytest.mark.asyncio
async def test_badge_allowlist_is_exhaustive_and_all_other_mcp_tools_reject():
    mcp = FastMCP(name="badge-contract")
    registered = register_all_tools(mcp)
    tools = mcp._tool_manager._tools
    assert registered == len(ALL_TOOL_NAMES) == 44
    assert set(tools) == ALL_TOOL_NAMES

    token = current_token_info.set(_badge_context())
    try:
        for name, tool in tools.items():
            if name in BADGE_ALLOWED_TOOLS:
                continue
            result = await _tool_callable(tool)(**_blocked_tool_args(_tool_callable(tool)))
            assert result["status"] == "error", f"Badge accepted forbidden tool {name}"
    finally:
        current_token_info.reset(token)


@pytest.mark.asyncio
async def test_badge_can_only_read_and_write_its_exact_live_space_and_whoami():
    mcp = FastMCP(name="badge-live")
    register_all_tools(mcp)
    tools = mcp._tool_manager._tools
    live_service = MagicMock()
    live_service.read_notes = AsyncMock(return_value={"status": "ok", "total": 0})
    live_service.write_note = AsyncMock(return_value={"status": "created"})
    token_service = MagicMock()
    token_service.list_tokens = AsyncMock(return_value={"tokens": []})

    token = current_token_info.set(_badge_context())
    try:
        with patch("live_mem.core.live.get_live_service", return_value=live_service), patch(
            "live_mem.core.tokens.get_token_service", return_value=token_service
        ):
            assert (
                await _tool_callable(tools["live_read"])(space_id=MISSION_SPACE)
            )["status"] == "ok"
            assert (
                await _tool_callable(tools["live_note"])(
                    space_id=MISSION_SPACE, category="progress", content="ok"
                )
            )["status"] == "created"
            assert (await _tool_callable(tools["system_whoami"])())["status"] == "ok"

            cross_space = await _tool_callable(tools["live_read"])(space_id="other")
            assert cross_space["status"] == "error"
            search = await _tool_callable(tools["live_search"])(
                space_id=MISSION_SPACE, query="x"
            )
            assert search["status"] == "error"
    finally:
        current_token_info.reset(token)


def _receive_json(payload: dict):
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {
                "type": "http.request",
                "body": json.dumps(payload).encode(),
                "more_body": False,
            }
        return {"type": "http.disconnect"}

    return receive


def _capture_send():
    messages: list[dict] = []

    async def send(message):
        messages.append(message)

    return send, messages


def _http_status(messages: list[dict]) -> int:
    return next(
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    )


@pytest.mark.asyncio
async def test_badge_is_refused_by_real_http_api_and_never_receives_a_cookie():
    badge = _badge_context()

    async def terminal(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    app = AuthMiddleware(StaticFilesMiddleware(terminal))
    send, messages = _capture_send()
    api_scope = {
        "type": "http",
        "path": "/api/spaces",
        "method": "GET",
        "headers": [(b"authorization", b"Bearer badge-secret")],
        "query_string": b"",
    }
    with patch.object(AuthMiddleware, "_validate_token", AsyncMock(return_value=badge)):
        await app(api_scope, _receive_json({}), send)
    assert _http_status(messages) == 403

    send, login_messages = _capture_send()
    login_scope = {
        "type": "http",
        "path": "/api/login",
        "method": "POST",
        "headers": [(b"authorization", b"Bearer badge-secret")],
        "query_string": b"",
        "scheme": "http",
    }
    with patch.object(AuthMiddleware, "_validate_token", AsyncMock(return_value=badge)):
        await app(login_scope, _receive_json({"token": "badge-secret"}), send)
    assert _http_status(login_messages) == 403
    headers = next(
        message["headers"]
        for message in login_messages
        if message["type"] == "http.response.start"
    )
    assert not any(key == b"set-cookie" for key, _value in headers)

    send, logout_messages = _capture_send()
    logout_scope = {
        "type": "http",
        "path": "/api/logout",
        "method": "POST",
        "headers": [(b"authorization", b"Bearer badge-secret")],
        "query_string": b"",
    }
    with patch.object(AuthMiddleware, "_validate_token", AsyncMock(return_value=badge)):
        await app(logout_scope, _receive_json({}), send)
    assert _http_status(logout_messages) == 403
