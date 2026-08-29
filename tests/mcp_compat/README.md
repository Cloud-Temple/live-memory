# MCP v2 compatibility proof

Run this isolated local test with:

```bash
docker compose -p live-memory-mcp-v2-compat -f tests/mcp_compat/compose.yaml up -d --build
docker compose -p live-memory-mcp-v2-compat -f tests/mcp_compat/compose.yaml wait \
  live-memory-v1-27 live-memory-v1-28 \
  graph-memory-v2-probe-27 graph-memory-v2-probe-28 http-security-probe
docker compose -p live-memory-mcp-v2-compat -f tests/mcp_compat/compose.yaml logs --no-color
docker compose -p live-memory-mcp-v2-compat -f tests/mcp_compat/compose.yaml down --remove-orphans
```

Do not use `--abort-on-container-exit`: the two v1 fixture servers must stay
up until both v2 probes have completed. This isolated test never loads the
repository `.env`, does not invoke `live_mem.main`, and starts no S3, LLM,
token-admin, or production service. Its five one-shot probes prove:

- `mcp==1.27.0` and `mcp==1.28.1` initialize, list tools, and call read-only
  `system_about` through the delivered Caddy configuration to Live Memory v2;
- the v2 native transport and the Live Memory Graph Memory client initialize,
  list tools, and call `memory_list` against minimal MCP v1.27 and v1.28 peers;
- Caddy preserves the public Host header and the backend returns 401, 421, and
  403 for unauthenticated, invalid-Host, and invalid-Origin MCP requests; an
  absent Origin and a non-MCP route retain their expected behavior.
