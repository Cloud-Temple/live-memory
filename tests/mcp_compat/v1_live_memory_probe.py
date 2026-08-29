"""Read-only MCP v1 probe against the Live Memory v2 endpoint."""

import asyncio
import json
import os
from importlib.metadata import version

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def probe() -> None:
    url = os.environ["MCP_URL"]
    headers = {"Authorization": f"Bearer {os.environ['MCP_TOKEN']}"}
    last_error: Exception | None = None

    for _ in range(30):
        try:
            async with streamablehttp_client(
                url, headers=headers, timeout=5, sse_read_timeout=5
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    initialize = await session.initialize()
                    tools = await session.list_tools()
                    about = await session.call_tool("system_about", {})
                    assert any(tool.name == "system_about" for tool in tools.tools)
                    assert about.content and about.content[0].text
                    print(
                        json.dumps(
                            {
                                "mcp_sdk": version("mcp"),
                                "initialize": bool(initialize),
                                "tools": len(tools.tools),
                                "read_only_call": "system_about",
                            }
                        )
                    )
                    return
        except Exception as error:
            last_error = error
            await asyncio.sleep(1)

    raise RuntimeError(f"MCP v1 probe failed after retries: {last_error}")


asyncio.run(probe())
