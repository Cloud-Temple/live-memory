"""Assert the v2 Host/Origin decisions after a real Caddy proxy hop."""

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


URL = "http://mcp.test:8080/mcp"
TOKEN = os.environ["MCP_TOKEN"]


def status(headers: dict[str, str]) -> int:
    request = Request(URL, data=b"{}", headers=headers, method="POST")
    try:
        with urlopen(request, timeout=3) as response:
            return response.status
    except HTTPError as error:
        return error.code


def get_status(path: str, headers: dict[str, str]) -> int:
    request = Request(f"http://mcp.test:8080{path}", headers=headers, method="GET")
    try:
        with urlopen(request, timeout=3) as response:
            return response.status
    except HTTPError as error:
        return error.code


for attempt in range(30):
    try:
        results = {
            "unauthenticated": status(
                {"Host": "mcp.test:8080", "Content-Type": "application/json"}
            ),
            "invalid_host": status(
                {
                    "Host": "invalid.example.test",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {TOKEN}",
                }
            ),
            "invalid_origin": status(
                {
                    "Host": "mcp.test:8080",
                    "Origin": "https://invalid.example.test",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {TOKEN}",
                }
            ),
            "origin_absent": status(
                {
                    "Host": "mcp.test:8080",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {TOKEN}",
                }
            ),
            "non_mcp_route": get_status(
                "/not-an-mcp-route",
                {
                    "Host": "invalid.example.test",
                    "Authorization": f"Bearer {TOKEN}",
                },
            ),
        }
        assert results["unauthenticated"] == 401
        assert results["invalid_host"] == 421
        assert results["invalid_origin"] == 403
        assert results["origin_absent"] != 403
        assert results["non_mcp_route"] == 404
        print(json.dumps(results))
        break
    except (AssertionError, URLError) as error:
        if attempt == 29:
            raise RuntimeError(f"Caddy transport-security probe failed: {error}") from error
        time.sleep(1)
