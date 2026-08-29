# 🖥️ Live Memory CLI, Shell & Tests

> Scriptable CLI, interactive shell and test scripts for Live Memory MCP v2.4.0.

🇫🇷 [Version française](README.fr.md)

---

## Prerequisites

```bash
pip install click rich prompt-toolkit 'mcp[cli]>=2.1.1,<3' 'httpx2>=2.5.0,<3'
```

Environment variables:

```bash
export MCP_URL=http://localhost:8080    # Server URL (via WAF)
export MCP_TOKEN=your_secret_token      # Authentication token
```

---

## Parity with `/admin` and `/live`

| Surface          | Exposes                                         | Notes                                                                                       |
| ---------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `mcp_cli.py`     | All **43 MCP tools** (full operational parity)  | Click commands + interactive shell. This README is the reference list.                       |
| Web `/admin`     | Same 43 MCP tools via `POST /api/tool` proxy    | Authenticated web console (HttpOnly cookie). Dashboard, Spaces, Tokens, Explorer, Backups, Graph Bridge, Stale Banks, Maintenance. |
| Web `/live`      | Read-only viewer of spaces / live notes / bank  | Uses dedicated REST endpoints (`/api/spaces`, `/api/live/<id>`, `/api/bank/<id>`), NOT MCP. |

The CLI is the canonical surface — anything you can do in `/admin` you can also do from `mcp_cli.py` (and vice-versa). `/live` is a read-only convenience UI; its capabilities are a subset of `live read`, `bank read`, `bank list`, `space info`.

---

## Scriptable CLI (Click)

Every MCP tool maps to a Click command. Full help: `python scripts/mcp_cli.py --help` or `... <group> --help`.

### System (3 tools)

```bash
python scripts/mcp_cli.py health                              # Service health (S3 + LLM probes)
python scripts/mcp_cli.py whoami                              # Current token identity
python scripts/mcp_cli.py about                               # Service version, capabilities
```

### Space (9 tools)

```bash
python scripts/mcp_cli.py space list                          # List accessible spaces
python scripts/mcp_cli.py space create my-proj -d "Desc"      # Create a space (auto-attached to caller token)
python scripts/mcp_cli.py space info my-proj                  # Details (counts, owner, dates, queue summary)
python scripts/mcp_cli.py space rules my-proj                 # Memory Bank rules of this space
python scripts/mcp_cli.py space summary my-proj               # Full synthesis (rules + bank + notes counts)
python scripts/mcp_cli.py space update my-proj -d "New desc"  # Update description / owner
python scripts/mcp_cli.py space update-rules my-proj -f rules.md  # Replace rules (manage)
python scripts/mcp_cli.py space export my-proj                # Export as tar.gz
python scripts/mcp_cli.py space delete my-proj --confirm      # Irreversible (manage)
```

### Live notes (3 tools)

```bash
python scripts/mcp_cli.py live note my-proj observation "Found X"   # Append a note (agent = token)
python scripts/mcp_cli.py live read my-proj                          # List recent unconsolidated notes
python scripts/mcp_cli.py live search my-proj "keyword"              # Full-text search in notes
```

### Bank (11 tools)

```bash
python scripts/mcp_cli.py bank list my-proj                          # List bank files
python scripts/mcp_cli.py bank read my-proj activeContext.md         # Read one bank file
python scripts/mcp_cli.py bank read-all my-proj                      # Read entire bank (agent startup)
python scripts/mcp_cli.py bank consolidate my-proj                   # 🧠 Enqueue async LLM consolidation (fire-and-forget)
python scripts/mcp_cli.py bank consolidation-status <job_id>         # Manual status check (do NOT poll automatically)
python scripts/mcp_cli.py bank consolidation-queues                  # Lane summary across all accessible spaces
python scripts/mcp_cli.py bank stale-spaces                          # 🚨 Spaces ≥5 notes / oldest ≥5 days
python scripts/mcp_cli.py bank stale-spaces --min-notes 10 --min-age-days 7 --consolidate  # Trigger bulk consolidation
python scripts/mcp_cli.py bank compact my-proj                       # Dry-run scan of oversized files
python scripts/mcp_cli.py bank compact my-proj --apply               # Enqueue strict LLM compaction (manage)
python scripts/mcp_cli.py bank repair my-proj                        # Dry-run scan (Unicode / parasitic prefixes)
python scripts/mcp_cli.py bank repair my-proj --apply                # Apply fixes (manage)
python scripts/mcp_cli.py bank write my-proj activeContext.md -f ./ctx.md   # Bypass LLM (manage)
python scripts/mcp_cli.py bank delete my-proj progress.md --confirm  # Delete file + Unicode duplicates (manage)
```

### Graph Bridge (4 tools)

```bash
python scripts/mcp_cli.py graph connect my-proj <url> <token> <memory_id> [ontology]
python scripts/mcp_cli.py graph push my-proj                         # Push bank → graph (delete + re-ingest)
python scripts/mcp_cli.py graph status my-proj                       # Connection + graph stats
python scripts/mcp_cli.py graph disconnect my-proj
```

### Backup (5 tools)

```bash
python scripts/mcp_cli.py backup create my-proj -d "before migration"
python scripts/mcp_cli.py backup create --all                        # Backup ALL accessible spaces (admin)
python scripts/mcp_cli.py backup list [my-proj]                      # List backups (filter by space optional)
python scripts/mcp_cli.py backup download <backup_id>                # Download archive
python scripts/mcp_cli.py backup restore <backup_id> --confirm       # Restore (space must not exist)
python scripts/mcp_cli.py backup delete <backup_id> --confirm        # Permanent
```

### Admin — tokens & GC (8 tools)

```bash
python scripts/mcp_cli.py token create agent-cline -p read,write --email cline@team.io
python scripts/mcp_cli.py token list                                 # List tokens (filterable)
python scripts/mcp_cli.py token update <hash> --add-spaces my-proj   # Delta update (add/remove spaces, perms, email)
python scripts/mcp_cli.py token bulk-update --name-contains agent --add-spaces my-proj --confirm   # Mass update
python scripts/mcp_cli.py token revoke <hash>                        # Soft-revoke (keeps audit trail)
python scripts/mcp_cli.py token delete <hash>                        # Hard-delete (admin)
python scripts/mcp_cli.py token purge [--all]                        # Purge revoked tokens (or --all)
python scripts/mcp_cli.py gc --space-id my-proj --confirm            # Cleanup orphaned notes (default age 7d)
```

---

## Interactive Shell

```bash
python scripts/mcp_cli.py shell
```

Features:

- **Tab completion** on all commands and subcommands
- **Persistent history** (`~/.live_mem_shell_history`)
- **Contextual help**: `help`, `help <verb>` (e.g. `help bank`)
- **Rich display** with colors (tables, panels, Markdown)
- **`--json` flag** on any command for raw JSON output

---

## 🧪 Test Scripts

### Anti-Hallucination Test — `test_hallucination.py`

Reproduces and detects LLM consolidator hallucinations (Issue #17). 5 scenarios, 25 assertions.

```bash
python scripts/test_hallucination.py                       # All scenarios
python scripts/test_hallucination.py --scenario D          # Single scenario (A, B, C, ABC, D, E, ALL)
python scripts/test_hallucination.py -v --keep             # Verbose + keep test spaces
```

| Scenario | Detects                                                   |
| -------- | --------------------------------------------------------- |
| A        | Invented file structure (Next.js for a Rails project)      |
| B        | Invented metrics (LoC not in notes)                        |
| C        | Domain term reinterpretation (Group, Lens)                 |
| D        | Replaced plan not removed from backlog                     |
| E        | Stale status despite newer progress notes                  |

---

### Global Test Suite — `test_recette.py`

Unified script with **4 selectable suites**:

```bash
python scripts/test_recette.py --list                       # List available suites
python scripts/test_recette.py --url http://localhost:8085  # ALL suites
python scripts/test_recette.py --suite recette              # Pipeline agent (7 tests)
python scripts/test_recette.py --suite isolation            # Multi-tenant (18 tests)
python scripts/test_recette.py --suite qualite              # MCP tools (19 tests)
python scripts/test_recette.py --suite recette,isolation    # Multiple suites
python scripts/test_recette.py --suite isolation -v --step  # Step-by-step
python scripts/test_recette.py --no-cleanup                 # Keep test data
```

#### Available Suites

| Suite       | Tests | Description                                                                                                |
| ----------- | ----- | ---------------------------------------------------------------------------------------------------------- |
| `recette`   | 7     | Full pipeline: token → space → notes → LLM consolidation → bank → cleanup                                  |
| `isolation` | 18    | Multi-tenant: cross-space access denied, backup filtering, read-only enforcement, auto-add space to token |
| `qualite`   | 19    | MCP tools: system, admin, space, live, bank, backup, GC                                                    |
| `graph`     | ~8    | Graph Memory bridge: connect, push, status, disconnect (optional, requires `--graph-url` and `--graph-token`) |

```bash
# Graph suite (requires running Graph Memory instance)
python scripts/test_recette.py --suite graph \
  --graph-url http://host.docker.internal:8080 \
  --graph-token TOKEN
```

> ⚠️ When Live Memory runs in Docker, use `host.docker.internal` instead of `localhost` for Graph Memory URLs.

### Bank Compaction Unit Test — `test_bank_compact.py`

Direct unit test for the compaction engine. Run via `python scripts/test_bank_compact.py`.

---

## Common Options

| Option          | Description                                                                |
| --------------- | -------------------------------------------------------------------------- |
| `--url`         | Live Memory server URL (default: `$MCP_URL` or `http://localhost:8080`)    |
| `--token`       | Admin bootstrap key (default: `$ADMIN_BOOTSTRAP_KEY` or `.env`)            |
| `--json` / `-j` | Raw JSON output on any command (bypasses Rich formatting)                  |
| `--suite`       | Suites to run, comma-separated (default: all)                              |
| `--graph-url`   | Graph Memory URL (for `--suite graph`)                                     |
| `--graph-token` | Graph Memory token (for `--suite graph`)                                   |
| `--step`        | Step-by-step mode (pause between steps)                                    |
| `--no-cleanup`  | Keep test data after completion                                            |
| `-v`            | Verbose output                                                             |
| `--list`        | List available suites and exit                                             |

---

## Architecture

```
scripts/
├── mcp_cli.py                # CLI entry point (Click) + Interactive shell
├── test_recette.py           # 🧪 Global test suite (4 suites, ~44 tests)
├── test_hallucination.py     # 🧪 Anti-hallucination tests (Issue #17, 5 scenarios)
├── test_bank_compact.py      # 🧪 Bank compaction unit tests
├── README.md                 # Documentation (English) ← You are here
├── README.fr.md              # Documentation (French)
└── cli/
    ├── __init__.py           # Config (BASE_URL, TOKEN)
    ├── client.py             # MCPClient Streamable HTTP (MCP SDK)
    ├── commands.py           # Click commands (1 per MCP tool)
    ├── display.py            # Rich display (tables, panels)
    └── shell.py              # Interactive shell (prompt_toolkit)
```

---

*Live Memory CLI v2.4.0*
