# 🖥️ Live Memory CLI, Shell & Tests

> Scriptable CLI, interactive shell and test scripts for Live Memory MCP v1.9.0.

🇫🇷 [Version française](README.fr.md)

---

## Prerequisites

```bash
pip install click rich prompt-toolkit mcp[cli]>=1.8.0
```

Environment variables:
```bash
export MCP_URL=http://localhost:8080    # Server URL (via WAF)
export MCP_TOKEN=your_secret_token      # Authentication token
```

---

## Scriptable CLI (Click)

```bash
python scripts/mcp_cli.py health                      # Health status
python scripts/mcp_cli.py whoami                       # Current token identity
python scripts/mcp_cli.py about                        # Service info
python scripts/mcp_cli.py space list                   # List spaces
python scripts/mcp_cli.py space create id desc rules   # Create a space
python scripts/mcp_cli.py space update id -d "desc"    # Update description/owner
python scripts/mcp_cli.py space summary id             # Full summary
python scripts/mcp_cli.py space export id              # Export as tar.gz
python scripts/mcp_cli.py live note space obs "msg"    # Write a note
python scripts/mcp_cli.py bank consolidate space       # LLM consolidation
python scripts/mcp_cli.py token create name -p read,write --email u@ex.com  # Create a token
python scripts/mcp_cli.py token update sha256:a8c5 --email u@ex.com     # Update a token
python scripts/mcp_cli.py token list                                     # List tokens
python scripts/mcp_cli.py graph push space             # Push to Graph Memory
python scripts/mcp_cli.py bank compact space            # Analyze oversized files (dry-run)
python scripts/mcp_cli.py bank compact space --apply    # Compact via LLM (manage)
python scripts/mcp_cli.py backup create space           # Create a backup
python scripts/mcp_cli.py backup create --all           # Backup ALL spaces (admin)
python scripts/mcp_cli.py backup download id           # Download a backup
python scripts/mcp_cli.py gc --space-id id --confirm   # Garbage Collector
```

Full help: `python scripts/mcp_cli.py --help`

---

## Interactive Shell

```bash
python scripts/mcp_cli.py shell
```

Features:
- **Tab completion** on all commands
- **Persistent history** (`~/.live_mem_shell_history`)
- **Rich display** with colors (tables, panels, Markdown)

---

## 🧪 Test Scripts

### Anti-Hallucination Test — `test_hallucination.py`

Reproduces and detects LLM consolidator hallucinations (Issue #17). 5 scenarios, 25 assertions.

```bash
# All scenarios
python scripts/test_hallucination.py

# Single scenario (A, B, C, ABC, D, E, ALL)
python scripts/test_hallucination.py --scenario D

# Verbose + keep test spaces
python scripts/test_hallucination.py -v --keep
```

| Scenario | Detects |
|----------|---------|
| A | Invented file structure (Next.js for a Rails project) |
| B | Invented metrics (LoC not in notes) |
| C | Domain term reinterpretation (Group, Lens) |
| D | Replaced plan not removed from backlog |
| E | Stale status despite newer progress notes |

---

### Global Test Suite — `test_recette.py`

Unified script with **4 selectable suites** via command line:

```bash
# List available suites
python scripts/test_recette.py --list

# ALL suites (44 tests, ~60s)
python scripts/test_recette.py --url http://localhost:8085

# Single suite
python scripts/test_recette.py --suite recette     # Agent pipeline (7 tests)
python scripts/test_recette.py --suite isolation    # Multi-tenant (18 tests)
python scripts/test_recette.py --suite qualite      # MCP tools (19 tests)

# Multiple suites
python scripts/test_recette.py --suite recette,isolation

# Options
python scripts/test_recette.py --suite isolation -v --step  # Verbose + step-by-step
python scripts/test_recette.py --no-cleanup                  # Keep test data
```

#### Available Suites

| Suite | Tests | Description |
|---|---|---|
| `recette` | 7 | Full pipeline: token → space → notes → LLM consolidation → bank → cleanup |
| `isolation` | 18 | Multi-tenant isolation v0.7.1: cross-space access denied, backup_list filtering, read-only enforcement, auto-add space to token |
| `qualite` | 19 | MCP tools testing: system, admin, space, live, bank, backup, GC |
| `graph` | ~8 | Graph Memory bridge: connect, push, status, disconnect (optional, requires `--graph-url` and `--graph-token`) |

**Expected result**: 44 PASS, 0 FAIL (without graph). With graph: ~52 PASS.

```bash
# Graph suite (requires running Graph Memory instance)
python scripts/test_recette.py --suite graph \
  --graph-url http://host.docker.internal:8080 \
  --graph-token TOKEN
```

> ⚠️ When Live Memory runs in Docker, use `host.docker.internal` instead of `localhost` for Graph Memory URLs.

---

## Common Options

| Option | Description |
|---|---|
| `--url` | Live Memory server URL (default: `$MCP_URL` or `http://localhost:8080`) |
| `--token` | Admin bootstrap key (default: `$ADMIN_BOOTSTRAP_KEY` or `.env`) |
| `--suite` | Suites to run, comma-separated (default: all) |
| `--graph-url` | Graph Memory URL (for `--suite graph`) |
| `--graph-token` | Graph Memory token (for `--suite graph`) |
| `--step` | Step-by-step mode (pause between steps) |
| `--no-cleanup` | Keep test data after completion |
| `-v` | Verbose output |
| `--list` | List available suites and exit |

---

## Architecture

```
scripts/
├── mcp_cli.py                # CLI entry point (Click) + Interactive shell
├── test_recette.py           # 🧪 Global test suite (4 suites, ~44 tests)
├── test_hallucination.py     # 🧪 Anti-hallucination tests (Issue #17, 5 scenarios)
├── test_bank_compact.py      # 🧪 Bank compaction unit tests
├── test_dedup_fix.py         # 🧪 Deduplication fix tests
├── README.md                 # Documentation (English) ← You are here
├── README.fr.md              # Documentation (French)
└── cli/
    ├── __init__.py           # Config (BASE_URL, TOKEN)
    ├── client.py             # MCPClient Streamable HTTP (MCP SDK)
    ├── commands.py           # Click commands
    ├── display.py            # Rich display (tables, panels)
    └── shell.py              # Interactive shell (prompt_toolkit)
```

---

*Live Memory CLI v1.9.0*
