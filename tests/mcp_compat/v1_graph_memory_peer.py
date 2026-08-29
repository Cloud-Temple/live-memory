"""Minimal read-only MCP v1 peer used only by the local compatibility test."""

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("Graph Memory v1 fixture", host="0.0.0.0", port=8003)


@mcp.tool()
async def memory_list() -> dict:
    return {"status": "ok", "memories": [], "fixture": "mcp-v1"}


app = mcp.streamable_http_app()
