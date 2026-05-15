# Authentication & Multi-Agent Collaboration — Live Memory

> **Version**: 1.6.0 | **Date**: 2026-04-25 | **Author**: Cloud Temple

---

## 1. Authentication Model

### 1.1 Architecture

```
Agent (Cline, Claude, etc.)
    │
    │  Authorization: Bearer lm_a1b2c3d4e5f6...
    │
    ▼
┌────────────────────────────────────┐
│  Auth Middleware (ASGI)             │
│                                     │
│  1. Extracts token from header      │
│     (or query string ?token=xxx)    │
│  2. SHA-256 hash of the token       │
│  3. Looks up hash in tokens.json    │
│  4. Verifies: not revoked,          │
│     not expired, permissions OK,    │
│     space_id authorized             │
│  5. Stores identity in              │
│     contextvars (for tools)         │
└────────────────────────────────────┘
```

### 1.2 Token Types

| Type       | Permissions          | Usage                    | Example Tools                                      |
| ---------- | -------------------- | ------------------------ | -------------------------------------------------- |
| **Reader** | `read`               | Read-only access         | `bank_read_all`, `live_read`, `space_list`         |
| **Writer** | `read, write`        | Read + write access      | + `live_note`, `bank_consolidate`, `space_create`, `graph_push` |
| **Admin**  | `read, write, admin` | Full access              | + `admin_*`, `space_delete`, `backup_restore`, `admin_gc_notes` |

### 1.3 Bootstrap Key

On first startup, only the `ADMIN_BOOTSTRAP_KEY` (environment variable) allows authentication. It is used to create the first admin token, after which it should no longer be used.

```
Startup → ADMIN_BOOTSTRAP_KEY → admin_create_token → Admin token
                                                         │
                                                         ▼
                                              admin_create_token → Agent tokens
```

### 1.4 Space Access Control

Each token has a `space_ids` list:
- `[]` (empty) = access to **all** spaces
- `["project-alpha", "project-beta"]` = restricted to these spaces

When a tool receives a `space_id`, the `check_access()` helper verifies:

```python
def check_access(resource_id: str) -> Optional[dict]:
    """Checks whether the current token can access this space."""
    token_info = current_token_info.get()
    
    if token_info is None:
        return {"status": "error", "message": "Authentication required"}
    
    # Admin → full access
    if "admin" in token_info.get("permissions", []):
        return None
    
    # Verify the space is in the allowed list
    allowed = token_info.get("allowed_resources", [])
    if allowed and resource_id not in allowed:
        return {"status": "error", "message": f"Access denied to space '{resource_id}'"}
    
    return None  # OK
```

### 1.5 Token = Agent (v0.8.1+, replaces the v0.2.0 decoupling)

The token **is** the agent's identity. The token's `client_name` is used everywhere:

- `live_note()`: the `agent` parameter was **removed** — the identity is always the token's `client_name`
- `bank_consolidate(agent="")`: auto-detects the token's `client_name` for write users
- `bank_consolidate(agent="xxx")`: only a manage+ user (manage or admin) can consolidate another agent's notes
- `get_current_agent_name()` returns the token's `client_name` (or "anonymous" if no token)
- **One token = one agent** — no token sharing between multiple agents

> ⚠️ **History**: v0.2.0 introduced a Token/Agent decoupling that allowed passing `agent=` freely.
> This approach was abandoned in v0.8.1 because it caused orphaned notes (the consolidator
> filters by agent name in the S3 filename — if the name didn't match the token, notes
> were never consolidated).

### 1.6 Token Storage

Tokens are stored in `_system/tokens.json` on S3 (see `S3_DATA_MODEL.md`).

**Token format**: `lm_` + 43 base64url characters = **46 characters** total.

```python
import secrets
token = "lm_" + secrets.token_urlsafe(32)
# e.g.: lm_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0u1V2
```

**Hashing**: SHA-256 of the full token.

```python
import hashlib
token_hash = "sha256:" + hashlib.sha256(token.encode()).hexdigest()
```

---

## 2. Multi-Agent Collaboration

### 2.1 Collaboration Scenarios

#### Scenario A: Development Team (2-3 agents)

```
┌──────────────┐     ┌───────────────┐     ┌──────────────┐
│ Cline (Dev)  │     │Claude (Review)│     │ QA Agent     │
│ Token: write │     │ Token: write  │     │ Token: write │
└──────┬───────┘     └──────┬────────┘     └──────┬───────┘
       │                    │                     │
       ▼                    ▼                     ▼
    live_note            live_note             live_note
    (observation,        (insight,             (issue,
     decision,           question)              progress)
     todo)
       │                    │                     │
       └────────────────────┼─────────────────────┘
                            │
                            ▼
                    ┌─────────────────┐
                    │ Shared space    │
                    │ "project-alpha" │
                    │                 │
                    │ live/ (all      │
                    │  notes)         │
                    │                 │
                    │ bank/ (LLM-    │
                    │  consolidated)  │
                    └─────────────────┘
```

Each agent:
1. At startup: `bank_read_all("project-alpha")` to load context
2. During work: `live_note(...)` to write observations
3. Periodically: `live_read(agent="claude-review")` to see what others are doing
4. At session end: `bank_consolidate("project-alpha", agent="my-name")` to synthesize their own notes

#### Scenario B: Per-agent Consolidation (v0.2.0+)

```
Agent Cline writes 20 notes → bank_consolidate(agent="cline-dev")
    → Only cline-dev's notes are consolidated
    → claude-review's notes remain in live/
    → Write permission is sufficient

Agent Claude writes 15 notes → bank_consolidate(agent="claude-review")
    → Only claude-review's notes are consolidated
    → Write permission is sufficient

Admin → bank_consolidate(agent="")
    → ALL notes are consolidated
    → Manage permission required
```

### 2.2 Inter-agent Communication Patterns

Agents do not communicate directly with each other. They communicate **via the shared space**:

```
Agent A → live_note(category="question", "Should we support CSV?")
                                            │
                                            ▼
                                        S3 (note)
                                            │
Agent B → live_read(category="question") ←──┘
Agent B → live_note(category="decision", "No, JSON only")
```

### 2.3 Collaboration Best Practices

| Practice                      | Description                                                           |
| ----------------------------- | --------------------------------------------------------------------- |
| **Identify the agent**        | The agent is the token's `client_name` (automatic since v0.8.1)       |
| **Categorize notes**          | Use standard categories (observation, decision, todo, etc.)           |
| **Tag notes**                 | Add tags for filtering (`tags="auth,module"`)                         |
| **Read before writing**       | `bank_read_all` at startup, `live_read` regularly                     |
| **Consolidate your notes**    | `bank_consolidate(agent="my-name")` — each agent consolidates their own |
| **Atomic notes**              | One note = one fact, one decision, one todo. No mega-long notes       |
| **Periodic GC**               | `admin_gc_notes` to clean up notes from disappeared agents            |

---

## 3. Detailed Permission Matrix

### By Tool Category

| Tool                 | Min Perm | Check access | Notes                                  |
| -------------------- | -------- | ------------ | -------------------------------------- |
| **Space**            |          |              |                                        |
| `space_create`       | write    | —            | Creates a new space                    |
| `space_list`         | read     | filter       | Only shows authorized spaces           |
| `space_info`         | read     | ✅           |                                        |
| `space_rules`        | read     | ✅           |                                        |
| `space_summary`      | read     | ✅           |                                        |
| `space_export`       | read     | ✅           |                                        |
| `space_delete`       | admin    | ✅           | Irreversible                           |
| **Live**             |          |              |                                        |
| `live_note`          | write    | ✅           | Write                                  |
| `live_read`          | read     | ✅           | Read                                   |
| `live_search`        | read     | ✅           | Read                                   |
| **Bank**             |          |              |                                        |
| `bank_read`          | read     | ✅           | Read                                   |
| `bank_read_all`      | read     | ✅           | Read                                   |
| `bank_list`          | read     | ✅           | Read                                   |
| `bank_consolidate`   | write*   | ✅           | *write: auto-detects caller. manage if agent≠caller or global consolidation |
| **Graph**            |          |              |                                        |
| `graph_connect`      | write    | ✅           | Configures Graph Memory connection     |
| `graph_push`         | write    | ✅           | Pushes bank into the graph             |
| `graph_status`       | read     | ✅           | Connection status + graph stats        |
| `graph_disconnect`   | write    | ✅           | Removes connection config              |
| **Backup**           |          |              |                                        |
| `backup_create`      | write    | ✅           | Creates a snapshot                     |
| `backup_list`        | read     | filter       | Only shows accessible backups          |
| `backup_restore`     | admin    | ✅           | Potentially destructive                |
| `backup_download`    | read     | ✅           | Read                                   |
| `backup_delete`      | admin    | ✅           | Irreversible                           |
| **Admin**            |          |              |                                        |
| `admin_create_token` | admin    | —            | Token management                       |
| `admin_list_tokens`  | admin    | —            | Token management                       |
| `admin_revoke_token` | admin    | —            | Token management                       |
| `admin_update_token` | admin    | —            | Token management                       |
| `admin_gc_notes`     | admin    | —            | Maintenance (orphaned note GC)         |
| **System**           |          |              |                                        |
| `system_health`      | public   | —            | No auth required                       |
| `system_about`       | public   | —            | No auth required                       |

### Summary: Who Can Do What

| Action                          | Reader | Writer | Admin |
| ------------------------------- | :----: | :----: | :---: |
| Read the bank                   |   ✅   |   ✅   |  ✅   |
| Read live notes                 |   ✅   |   ✅   |  ✅   |
| Write notes                     |   ❌   |   ✅   |  ✅   |
| Consolidate own notes           |   ❌   |   ✅   |  ✅   |
| Consolidate all notes           |   ❌   |   ❌   |  ✅   |
| Create a space                  |   ❌   |   ✅   |  ✅   |
| Delete a space                  |   ❌   |   ❌   |  ✅   |
| Connect/push to Graph Memory    |   ❌   |   ✅   |  ✅   |
| View Graph Memory status        |   ✅   |   ✅   |  ✅   |
| Create a backup                 |   ❌   |   ✅   |  ✅   |
| Restore a backup                |   ❌   |   ❌   |  ✅   |
| Manage tokens                   |   ❌   |   ❌   |  ✅   |
| GC orphaned notes               |   ❌   |   ❌   |  ✅   |

---

## 4. Security

### 4.1 Check in Every Tool

Standard pattern at the top of each tool:

```python
@mcp.tool()
async def live_note(space_id: str, category: str, content: str, ...) -> dict:
    try:
        # 1. Verify space access
        access_err = check_access(space_id)
        if access_err:
            return access_err
        
        # 2. Verify write permission
        write_err = check_write_permission()
        if write_err:
            return write_err
        
        # 3. Business logic...
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

### 4.2 Authentication Helpers (auth/context.py)

4 functions based on `contextvars`:
- `check_access(resource_id)` — verifies access to a space
- `check_write_permission()` — verifies write permission
- `check_admin_permission()` — verifies admin permission
- `get_current_agent_name()` — returns the agent name (token's client_name, or "anonymous")

### 4.3 Audit Logging

Each HTTP request is logged to `stderr` via `LoggingMiddleware`:

```
19:05:12 INFO  [live_mem.auth] GET /mcp → 200 (45.2ms)
19:05:15 INFO  [live_mem.auth] POST /mcp → 200 (120.5ms)
```

### 4.4 Recommendations

| Recommendation                                                       | Priority          |
| -------------------------------------------------------------------- | ----------------- |
| Change `ADMIN_BOOTSTRAP_KEY` in production (≥ 32 random characters)  | 🔴 Critical       |
| TLS in production (HTTPS via Let's Encrypt)                          | 🔴 Critical       |
| Agent tokens restricted by `space_ids`                               | 🟠 High           |
| Reader tokens for read-only agents                                   | 🟡 Medium         |
| Periodic token rotation                                              | 🟡 Medium         |
| Automatic token expiration (`expires_in_days`)                       | 🟢 Best practice  |
| Regular note GC (`admin_gc_notes`)                                   | 🟢 Best practice  |

---

*Document updated April 25, 2026 — Live Memory v1.6.0*
