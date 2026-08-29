"""Live Memory's v2 outbound Graph Memory client against a v1 local peer."""

import asyncio
import json
import os
from importlib.metadata import version

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from live_mem.core.graph_bridge import GraphMemoryClient


async def probe() -> None:
    base_url = os.environ["GRAPH_MEMORY_BASE_URL"].rstrip("/")
    peer_version = os.environ["GRAPH_MEMORY_V1_VERSION"]
    last_result: dict | None = None
    for _ in range(30):
        try:
            # depends_on only waits for the v1 container to start; it does not
            # wait for its pip install and Uvicorn startup. Retry the complete
            # native v2 transport contract and the wrapper call together.
            async with httpx2.AsyncClient(
                timeout=httpx2.Timeout(5, read=5),
                follow_redirects=True,
                trust_env=True,
            ) as http_client:
                async with streamable_http_client(
                    f"{base_url}/mcp", http_client=http_client
                ) as (read, write):
                    async with ClientSession(read, write) as session:
                        initialize = await session.initialize()
                        tools = await session.list_tools()
                        assert any(tool.name == "memory_list" for tool in tools.tools)

            client = GraphMemoryClient(base_url, "", timeout=5)
            last_result = await client.call_tool("memory_list", {})
            if last_result.get("status") == "ok":
                print(
                    json.dumps(
                        {
                            "mcp_sdk": version("mcp"),
                            "v1_peer_sdk": peer_version,
                            "initialize": bool(initialize),
                            "tools": len(tools.tools),
                            "read_only_call": "memory_list",
                            "result": last_result,
                        }
                    )
                )
                return
        except Exception as error:
            last_result = {"status": "error", "message": str(error)}
        await asyncio.sleep(1)
    raise RuntimeError(f"MCP v2 outbound probe failed: {last_result}")


asyncio.run(probe())
