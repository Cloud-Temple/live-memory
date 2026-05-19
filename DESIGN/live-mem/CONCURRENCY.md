# Multi-Agent Concurrency Management — Live Memory

> **Version**: 1.6.0 | **Date**: 2026-04-25 | **Author**: Cloud Temple

---

## 1. Problem Statement

Multiple AI agents can interact simultaneously with the same memory space. Data consistency must be guaranteed without blocking common operations.

---

## 2. Analysis by Operation Type

### 2.1 Live Notes — ✅ CONFLICT-FREE (by design)

Each note = **a separate S3 file** with a unique name (timestamp + agent + UUID):

```
20260220T170001_cline-dev_observation_a1b2c3d4.md
20260220T170001_claude-rev_observation_e5f6a7b8.md  ← same second, different agents
```

Two agents writing at the same instant create two different files → **zero conflict**.

The UUID8 suffix (`uuid.uuid4().hex[:8]`) guarantees uniqueness even if two agents with the same name write in the same category at the same second.

**Conclusion**: `live_note` requires no locking mechanism.

---

### 2.2 Bank Files — FIFO QUEUE

Only `bank_consolidate` writes to the bank (agents never write directly). However, two agents could trigger `bank_consolidate` simultaneously.

**Solution**: an in-memory FIFO queue **per space** plus the existing `asyncio.Lock` **per space** for the actual bank mutation.

```python
async def bank_consolidate(space_id: str, agent: str = "") -> dict:
    # Permissions and effective agent scope are resolved before enqueue.
    return await get_consolidation_queue().enqueue(
        space_id=space_id,
        agent=effective_agent,
        requested_by=caller,
    )
```

**Behavior**:
- The MCP call returns quickly with `status="running"` or `status="queued"`
- A queued request is processed FIFO for the same `space_id`
- Job status is observable via `bank_consolidation_status(job_id)` and `space_info`
- Two different spaces can be consolidated in parallel (independent locks)
- PR 1 queue durability is `in_memory_best_effort`: jobs are not persisted across process restart

---

### 2.3 tokens.json File — ⚠️ POSSIBLE CONFLICT

Two admins creating/modifying tokens simultaneously could overwrite each other's changes.

**Solution**: A single `asyncio.Lock` for the tokens file.

```python
async with get_lock_manager().tokens:
    tokens_data = await storage.get_json("_system/tokens.json")
    modified = modifier_fn(tokens_data)
    await storage.put_json("_system/tokens.json", modified)
```

---

### 2.4 _meta.json File — ⚠️ POSSIBLE CONFLICT

Updated during consolidation and `graph_push`. Protected by the consolidation lock for consolidations. Graph operations use sequential read-modify-write.

---

## 3. Summary Matrix

| Operation | Risk | Solution | Performance Impact |
|---|---|---|---|
| `live_note` (N simultaneous agents) | None | Unique files (timestamp+UUID) | **Zero** |
| `live_read` / `live_search` (parallel reads) | None | Parallel S3 reads | **Zero** |
| `bank_read` / `bank_read_all` (parallel reads) | None | Parallel S3 reads | **Zero** |
| `bank_consolidate` (2 agents, same space) | Overwrite | In-memory FIFO + `asyncio.Lock` per space | 2nd is queued |
| `bank_consolidate` (2 agents, different spaces) | None | Independent locks | **Zero** |
| `admin_create_token` (2 admins) | tokens.json overwrite | Single `asyncio.Lock` for tokens | Serialization (~200ms) |
| `graph_connect` / `graph_push` | _meta.json update | Sequential (long operations) | **Zero** |
| `backup_create` (same space) | Read-only of the space | No lock needed (snapshot) | **Zero** |

---

## 4. Lock Pattern

### 4.1 In-memory Locks (asyncio.Lock)

The MCP server is a **single process** (one Python instance). All requests go through the same asyncio event loop. `asyncio.Lock` is therefore sufficient.

```python
class LockManager:
    """Centralized asyncio lock manager."""
    
    def __init__(self):
        self._consolidation_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tokens_lock = asyncio.Lock()
    
    def consolidation(self, space_id: str) -> asyncio.Lock:
        """Per-space lock for consolidation."""
        return self._consolidation_locks[space_id]
    
    @property
    def tokens(self) -> asyncio.Lock:
        """Single lock for tokens.json."""
        return self._tokens_lock
```

### 4.2 Why Not S3 Locks?

S3 has no native locking mechanism. Alternatives add complexity for marginal gain:

- **S3 lock files**: Fragile (if the server crashes, the lock remains → deadlock)
- **Conditional ETags**: Dell ECS does not properly support `If-Match` on PUT
- **DynamoDB locks**: Out of scope

The in-memory `asyncio.Lock` is **sufficient** because:
1. The MCP server is a single process
2. No multi-instance deployment (one `mcp-service` container)
3. Critical operations are short (< 1 minute except consolidation)

### 4.3 Multi-instance Case (future)

If live-mem were to run in multi-instance mode (load balancing), it would require:
- Redis for distributed locks (`redlock`)
- Or an S3 lease system (lock file with TTL)
- Or space-based routing (each instance handles a subset of spaces)

This is **not planned** for v0.5.0.

---

## 5. Concrete Scenarios

### Scenario 1: 3 agents write simultaneously (nominal)

```
T+0s: Agent A → live_note("observation", "Build OK")          → PUT S3: note_A.md ✅
T+0s: Agent B → live_note("decision", "We'll use FastAPI")    → PUT S3: note_B.md ✅
T+0s: Agent C → live_note("todo", "Write tests")              → PUT S3: note_C.md ✅
```

3 distinct files, no conflict, no lock.

### Scenario 2: 2 agents consolidate at the same time

```
T+0s:  Agent A → bank_consolidate("project-alpha", agent="agent-A")
       → Lock acquired ✅, consolidation starts (takes 30s)

T+5s:  Agent B → bank_consolidate("project-alpha", agent="agent-B")
       → Lock already held → immediate return {"status": "conflict"} ⚡

T+30s: Agent A → consolidation complete, lock released ✅
T+31s: Agent B → bank_consolidate("project-alpha", agent="agent-B")
       → Lock acquired ✅, consolidation starts
```

### Scenario 3: Agent writes during a consolidation

```
T+0s:  Agent A → bank_consolidate("project-alpha", agent="agent-A")
       → Lock acquired, reads agent-A's live notes

T+5s:  Agent B → live_note("observation", "New finding")
       → PUT S3: note_new.md ✅ (no lock needed)
       → This note will NOT be included in the current consolidation
       → It will be processed in the NEXT consolidation

T+30s: Agent A → consolidation complete
       → Only agent-A notes collected at T+0 are deleted
       → note_new.md (agent-B) remains in live/
```

### Scenario 4: Graph push during a consolidation

```
T+0s:  Agent A → bank_consolidate("project-alpha")
       → Consolidation lock acquired

T+5s:  Agent B → graph_push("project-alpha")
       → No lock needed (read-only access to bank + MCP Streamable HTTP call)
       → Pushes the bank in its current state (not the one being updated)
```

---

## 6. Performance

| Operation | Typical Latency | Lock? | Impact |
|---|---|---|---|
| `live_note` | 50-100ms (1 PUT S3) | No | None |
| `live_read` (50 notes) | 200-500ms (1 LIST + N GETs) | No | None |
| `bank_read_all` (6 files) | 100-300ms (1 LIST + 6 GETs) | No | None |
| `bank_consolidate` | 20-60s (LLM + S3 I/O) | Yes (per space) | Blocks other consolidations for the same space |
| `graph_push` (6 files) | 60-180s (MCP Streamable HTTP) | No | None |
| `admin_create_token` | 100-200ms (1 GET + 1 PUT S3) | Yes (tokens) | Short serialization |

---

*Document updated April 25, 2026 — Live Memory v1.6.0*
