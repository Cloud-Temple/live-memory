# -*- coding: utf-8 -*-
"""
Regression tests for MCP initialize/serverInfo version reporting.

Live Memory must expose its own VERSION value rather than the installed
`mcp` package version.
"""

import asyncio
from importlib.metadata import version as package_version
from pathlib import Path

import live_mem
from live_mem import server


def test_mcp_server_info_version_uses_live_memory_version():
    version_file = Path(__file__).resolve().parents[1] / "VERSION"
    expected = version_file.read_text(encoding="utf-8").strip()
    sdk_version = package_version("mcp")

    actual = server.mcp._lowlevel_server.version

    assert actual == expected
    assert actual == live_mem.__version__
    assert actual != sdk_version, (
        "MCP serverInfo.version fell back to the SDK package version instead "
        "of Live Memory's application version."
    )


def test_startup_catalog_lists_every_registered_tool_with_a_description():
    tools = asyncio.run(server.mcp.list_tools())
    categories = server._group_tool_names([tool.name for tool in tools])
    announced = [name for names in categories.values() for name in names]

    assert len(tools) == 44
    assert set(announced) == {tool.name for tool in tools}
    assert len(announced) == len(set(announced))
    assert "space_badge_mint" in categories["Space"]
    assert all((tool.description or "").strip() for tool in tools)
