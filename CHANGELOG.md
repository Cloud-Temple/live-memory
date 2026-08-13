# Changelog — Live Memory

All notable changes to this project are documented here.
Based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [2.7.1] — 2026-08-13

### Fixed

- **Consolidation failures are now atomic and attributable** (#40, PR #41).
  The complete LLM edit plan, including a textual `synthesis`, is validated
  before the first mutation. `create` cannot overwrite an existing bank file
  and `rewrite` requires one. Any operation or storage failure restores and
  exactly verifies the batch bank/synthesis snapshot (plus metadata outside
  normal batched mode) before source notes are touched.
- Partial live-note deletion is no longer accepted as success. Every source
  note is restored from the collected batch when possible, then re-read;
  `notes_deleted`, `notes_restored`, `notes_unrestored`, `notes_lost`, and the
  missing keys remain visible in the failed job result. A lost source is never
  counted as processed work.
- A later multi-file compaction persistence failure rolls back every planned
  bank file. The rollback restores and verifies only `bank/`, preserving live
  notes created concurrently after the backup; rollback failure remains
  explicit with the backup id required for manual recovery.
- No fallible batch operation capable of triggering output rollback remains
  after the irreversible source-note deletion. Final metadata/audit I/O still
  runs after committed batches, but its failure never rolls them back: it
  returns `partial` with their metrics instead of a generic queue error.
- Terminal consolidation and compaction job payloads are persisted before the
  terminal state is exposed or the per-space lane is released. Results remain
  available after a service restart; persistence failure is explicit through
  `audit_persistence_error`.

### Tests

- Added adversarial coverage for invalid late edit operations, storage failure
  on a later bank file, `create` overwrite, non-textual synthesis, partial note
  deletion/restoration, exact rollback keysets, concurrent live-note creation,
  multi-file compaction rollback, final metadata failure, and terminal-result
  persistence/restart behavior.
- Validation: 474 passed, 1 expected failure; independent reviewer GO after
  four passes and 65 targeted tests.

### Changed

- `README.md`, `README.fr.md`, and the consolidation, concurrency, S3, MCP tool,
  and architecture specifications document the v2.7.1 atomicity and durable
  terminal-audit contract.

---

## [2.7.0] — 2026-08-12

### Fixed

- **`bank_compact` can no longer persist a truncated LLM response while
  reporting success** (#37). The LLM now returns only a short JSON plan made
  of `replace_section` and `delete_section` operations. The server rejects
  non-terminal or invalid responses, applies the complete plan in memory, and
  verifies a real semantic reduction between 5% of the original logical size
  and 75% of the UTF-8 byte limit before writing. A full-space backup is
  created first; writes are read back and any mismatch triggers a rollback
  attempt. A rollback failure is explicit and retains the backup id for manual
  restore. Reports expose byte sizes, reduction, operation count, reasons,
  hashes, model result and backup id.
- The consolidator understands split families: it reconstructs the logical
  Markdown file, applies surgical edits once, then losslessly re-splits it.
  `create` and `rewrite` are refused on split files. Bank reads reassemble the
  logical document, while manual write/delete refuse every marked split family,
  including a one-part family.
- All bank mutations now share the per-space consolidation lock. Split target
  collisions and incomplete families fail closed; stale-part deletion and
  rollback failures are reported explicitly.
- Existing manually named workaround files (for example `progress-2.md`) are
  not inferred as split parts: they must be explicitly reassembled once before
  enabling consolidation with this release. Automatic split families remain
  machine-readable and are compacted as one logical document.
- Manual compaction now uses the existing per-space FIFO. Its queued/running/
  failed/succeeded state and final audit report are visible through the
  consolidation status tools.
- Failed surgical operations now expose `operation_failures` (file, section,
  operation and reason) and make the final consolidation status `partial`
  instead of `ok`.

### Tests

- Added adversarial coverage for UTF-8 byte drift, truncated/repaired LLM
  responses, forbidden plans, real logical reduction, mandatory backup,
  post-write rollback, logical split-file editing, queue visibility, and
  failed-operation observability.

### Changed

- `README.md`, `README.fr.md`, `FAQ.md`, `FAQ.fr.md`, the CLI readme, and the
  architecture specifications now document semantic LLM compaction, logical
  UTF-8 byte limits, durable split families, backup/rollback, and shared queue
  observability.

### Notes

- Minor bump: this release changes server-side compaction semantics and adds
  asynchronous queue visibility to `bank_compact`. It consumes the `2.7.0`
  slot previously targeted by the still-blocked `graph_push` volatile
  guardrail (PR #29), which moves to a later minor release.

---

## [2.6.0] — 2026-07-08

### Fixed

- **LLMaaS health probes now honor `PROXY_URL`** (#31, @aelttil). In a
  proxied deployment, the `/health` endpoint and the `system_health` MCP tool
  probed LLMaaS **directly**, while every real consolidation call goes through
  `PROXY_URL`. The health check therefore reported a network path that
  production traffic never takes — a false "unhealthy" when the proxy is the
  only egress, or a false "healthy" when only the direct route works. Both
  probes now build an explicit `httpx.AsyncClient(proxy=...)` when `PROXY_URL`
  is set (same pattern as `ConsolidatorService`) and close it in a `finally`
  block. No-proxy behavior is unchanged.

### Changed

- `DESIGN/live-mem/ARCHITECTURE.md` — documents `PROXY_URL` in the optional
  environment variables and notes that the outbound proxy now covers S3,
  LLMaaS consolidation, **and** the health probes.
- `README.md` / `README.fr.md` — version badge bumped to 2.6.0.

### Notes

- Minor bump: this is a server-side behavior change on the outbound network
  path. It consumes the `2.6.0` slot previously earmarked for the `graph_push`
  volatile guardrail (Wave B, PR #29); that work moves to the next minor once
  its blocking review items are resolved.

---

## [2.5.4] — 2026-07-08

### Fixed

- **Consolidation no longer reports a `succeeded` job when a batch fails**
  (#32, PR #33). A failed batch (LLM error or bank write error) used to break
  out of the batch loop while the final result was still built with a
  hardcoded `"status": "ok"` — the async queue then exposed the job as
  `succeeded` even with `0/N` batches completed. Uncovered by a production
  incident where every LLM call was rejected (context-length error) and the
  failure stayed invisible for 6 days. `consolidate()` now returns:
  - `ok` — no failure (unchanged contract);
  - `error` — failure with zero completed batches (nothing was integrated);
  - `partial` — failure after at least one applied batch (integrated work and
    metrics are preserved);
  - failed runs expose `failed_batch` and a `message` embedding the upstream
    error plus the number of notes left in `live/`. The queue lane `phase`
    now reflects the real outcome (`done`/`failed`).
- **Web UI `/live`: stale `selectBank()` responses are ignored** (#24, PR #28,
  @moul). `selectBank()` captures the requested space and filename before the
  async load and drops the response — on both the success and error render
  paths — if the user switched space or bank file meanwhile. Same guard family
  as the `refresh()` stale-guard introduced in v2.5.1.

### Added

- **Startup guard on the LLM output budget** (#32). Configuration is rejected
  at startup when `LLMAAS_MAX_TOKENS >= LLMAAS_CONTEXT_WINDOW`: such a budget
  can never produce a valid call on a large prompt (the backend rejects
  `input + max_tokens > window` before inference).
- Adversarial regression tests replaying the incident (first batch rejected
  with the real 262144 context-length error): `status="error"`, zero metrics,
  `_meta.json` untouched, no bank write attempted, `failed` job end-to-end
  through the queue (`tests/test_consolidation_batch_failure.py`, 7 tests) —
  plus 4 config-guard tests and 2 static UI race-guard tests. Suite:
  **426 passed + 1 xfailed** (was 413 + 1).

### Changed

- `README.md` / `README.fr.md` — stale version badge (stuck at 2.5.1)
  refreshed to 2.5.4.

---

## [2.5.3] — 2026-07-01

### Added

- **New RULES template: `RULES/company.steering.memory.bank.md` (Company
  Steering).** Memory Bank template for an AI agent assisting an executive
  (CEO/DG) in steering the whole company — finance, sales, business units,
  legal, HR, risk & compliance.
  - **11 mandatory files**: `companyBrief`, `governance`, `financeContext`,
    `salesContext`, `marketIntelligence`, `legalContext`, `hrContext`,
    `riskCompliance`, `stakeholders`, `activeContext`, `steeringProgress`.
  - **Dynamic files**: one `bu-[name].md` per business line (e.g. `bu-csp`,
    `bu-msp`) and one `dossier-[name].md` per strategic initiative, each with
    a mandated template and a lifecycle (created on first mention, archived
    with an outcome summary in `steeringProgress.md`).
  - **Absolute data-reliability rules** injected into the consolidator prompt:
    figures are never invented or extrapolated and always carry date + source
    (otherwise flagged `[à confirmer]`); HR data is aggregated only (no
    individual/personal data); legal exposure is quoted as assessed by
    counsel, never re-qualified by the LLM.
  - **Steering-grade conventions**: confidentiality notice (dedicated space,
    restricted tokens), ADR decision log in `steeringProgress.md`,
    "deadlines never go stale" rule for certifications, audits, and contract
    expiries.

### Changed

- `RULES/README.md` / `RULES/README.fr.md` — template tables updated with the
  new Company Steering entry.
- `README.md` / `README.fr.md` — repository structure tree now lists the
  `RULES/` template directory; stale `VERSION` annotation refreshed.

---

## [2.5.2] — 2026-06-07

### Fixed

- **Admin console — space creation no longer fails with "Empty response".**
  - **Root cause (infrastructure, not application code).** The admin console
    proxies every tool call through `POST /api/tool`, which is routed
    **through** the Coraza WAF (OWASP CRS). When creating a space with
    Markdown rules, that content travels in the request body and trips CRS
    XSS/SQLi heuristics — notably the `<` characters in the default rules
    (`activeContext.md < 8 KB`, `< 15 KB`) and the word `delete`
    (`delete sections superseded…`). The cumulative anomaly score crossed
    the threshold (5), Coraza returned a **403 with an empty body**, and the
    web UI surfaced it as `space_create` failing with *"Empty response"*.
    This is why `space_list` worked but `space_create` (with rules) did not.
  - **Fix.** `waf/Caddyfile` now excludes the **request body** of
    `/api/tool` from CRS inspection
    (`ctl:requestBodyAccess=Off` scoped to `REQUEST_URI @beginsWith
    /api/tool`). The endpoint is already gated by an HttpOnly cookie **and**
    the `write` permission and only proxies structured `{tool, arguments}`
    calls, so this mirrors the trust rationale already applied to `/mcp*`.
    Rate-limiting, body-size limits, and URI/header inspection (path
    traversal, scanners) remain active.
  - ⚠️ **Requires restarting/recreating the WAF container** for the change
    to take effect (`docker compose restart waf`). The Caddyfile is
    bind-mounted (`./waf/Caddyfile:/etc/caddy/Caddyfile:ro`), so **no image
    rebuild is needed** — Caddy re-reads it on restart.

### Added

- **Admin console — Owner field on "Create Space" is now a suggestion list.**
  - The free-text `Owner` input is paired with a `<datalist>` populated from
    **active token holders** (names deduplicated and sorted). Free-text entry
    is still allowed for owners that have no token.
  - Stored value is the **token name** (consistent with the Owner column
    rendering). `owner` remains optional and purely informational
    server-side — it has never been able to cause a creation failure.

### Changed

- `waf/Caddyfile` — new Coraza rule `id:900500` scoping
  `requestBodyAccess=Off` to `/api/tool`.
- `src/live_mem/static/js/admin-app.js` — new `ownerOptionsHtml()` helper;
  `showCreateSpace()` renders the Owner `<datalist>`.
- `DESIGN/live-mem/DEPLOIEMENT_PRODUCTION.md` — §5 "WAF Routes" documents the
  `/api/tool` body-inspection exception.

---

## [2.5.1] — 2026-06-05

### Added

- **Web UI `/live` — selected space persisted in URL query string.**
  - The dropdown selection is now reflected in `?space=<space_id>` on the
    current page via `history.replaceState` — no extra history entry is
    pushed per change.
  - On page load (whether via cookie auto-resume or fresh login), if the
    URL carries `?space=<id>` **and** the space appears in the user's
    accessible list, the dropdown is pre-selected and the space is loaded
    automatically.
  - Enables: refresh-safe selection, multi-tab workflows (one space per
    tab), and shareable links between devices/teammates.
  - Logging out clears the query string so a stale `?space=` does not
    survive across sessions on the same device.
  - Unknown / unauthorized space IDs in the URL are silently ignored
    (dropdown stays on `-- Space --`).

### Changed

- `src/live_mem/static/js/app.js` — `fillSpaceSelect` is now paired with a
  new `applySpaceFromUrl()` helper called once after the initial space list
  load in both `doLogin` and `checkToken`. The recurring `refreshSpaceList`
  still preserves the in-memory selection unchanged.

### Fixed

- **No double refresh cycle at startup.** `applySpaceFromUrl()` is now
  `async` and reports whether it loaded a space; `doLogin` / `checkToken`
  arm the recurring refresh themselves only when the URL did **not**
  auto-load a space (otherwise `loadSpace()` already armed it).
- **Stale-response guard in `refresh()`.** The target `space_id` is captured
  before the notes/bank/info calls fire and re-checked before the results are
  applied, so a late response for a space the user already switched away from
  is dropped instead of rendering into the current space's UI.

---

## [2.5.0] — 2026-06-03

### Added

- **Advanced workspace rules template** (`WORKSPACE_CLINE_ADVANCE_RULES.md`)
  rewritten as a **generic template** for workspaces connected to **both**
  Live Memory and Graph Memory. Four placeholders (`{LIVE_MCP_SERVER}`,
  `{SPACE}`, `{GRAPH_MCP_SERVER}`, `{GRAPH_MEMORY_ID}`); no ontology /
  entity classification declared on the agent side (Graph Memory server
  concern); no tokens or endpoints. The `{LIVE_MCP_SERVER}` placeholder
  was added to disambiguate when two MCP servers expose homonym tools.
  Now includes an explicit rule **"Never push `activeContext.md` or
  `progress.md` to Graph Memory"** and a complete responsibility
  separation table (Memory Bank / Graph Memory / repository files).
- **Evolution chantier doc** (`DESIGN/live-mem/EVOLUTION_LIVE_GRAPH_INTEGRATION.md`):
  documents the Live ↔ Graph integration evolution, the doctrinal vague A
  applied in this release, and proposed waves B (server-side guardrail
  inside `graph_push`) and C (new `canonical_ingest` config + tool) to be
  reviewed by codex before implementation.
- **Live ↔ Graph architecture note** added to README, README.fr, and
  `DESIGN/live-mem/ARCHITECTURE.md` (§4.4 Graph Push). Codifies the two
  invariants: *"Graph Memory complements the bank; it does not replace it."*
  and *"Graph Memory localizes; canonical repository files confirm."*

### Changed

- **`graph_push` MCP tool docstring** clearly marks it as
  **"Advanced / debug — NOT for routine flows"**, explains why the Memory
  Bank must not be indexed wholesale into Graph Memory, points to the
  canonical-repository-document agent-side ingestion pattern, and lists
  the two acceptable usages (one-off graph bootstrap, explicit debug /
  migration). Behaviour is **unchanged**: this is doctrinal only — a
  follow-up release will introduce a server-side guardrail (tracked in
  `DESIGN/live-mem/EVOLUTION_LIVE_GRAPH_INTEGRATION.md`).
- **Integration guides** (Cline / Claude Code / Codex, EN + FR) now
  surface the two workspace rules templates and tell the agent **which
  one to pick** depending on whether Graph Memory is wired in.
- **Project metadata**: VERSION bumped to `2.5.0`, README badges, footers,
  and ARCHITECTURE/Graph-bridge section updated accordingly.

### Notes

- **No runtime behaviour change** in this release. The Live Memory
  consolidator still updates only the Memory Bank; `graph_push` is
  unchanged at the code level. v2.5.0 is purely a doctrinal /
  documentation release that finalises the Live Memory + Graph Memory
  responsibility separation before the server-side guardrail work
  scheduled for v2.6.0+.

---

## [2.4.0] — 2026-05-22

### Added

- **`bank_stale_spaces` MCP tool** — read-only supervision tool that identifies
  memory banks whose consolidation has fallen behind:
  - Signature: `bank_stale_spaces(min_notes: int = 5, min_age_days: int = 5, space_ids: str = "")`.
  - A space is `stale` iff `live_notes_count >= min_notes` **AND**
    `oldest_note_age_days >= min_age_days` (both inclusive).
  - Lightweight S3 listing (`list_objects`, no content fetched). Oldest note
    age derived from the deterministic timestamp prefix of the filename
    (`YYYYMMDDTHHMMSS_…`), not S3 `LastModified`.
  - Returns `spaces` (filtered + sorted by notes_count DESC, age DESC),
    `scanned` (every inspected space with `is_stale` flag), and `denied_spaces`.
  - Displayed `oldest_note_age_days` is **truncated** (never round-to-nearest),
    so the UI cannot show an age that exceeds the real age at the threshold
    boundary.
- **CLI `bank stale-spaces`** (Click and interactive shell):
  - Flags: `--min-notes N`, `--min-age-days N`, `--space-ids CSV`, `--consolidate`, `--json`.
  - `--consolidate` chains `bank_consolidate` over every space reported stale.
- **Admin web console `/admin` → 🚨 Stale Banks**:
  - New sidebar category with live filter inputs (`Min notes`, `Min age (days)`)
    and Refresh button.
  - Table of stale spaces with color-coded age badges (blue / orange / red
    above 7d / 14d).
  - Per-row `▶ Consolidate` action and global `▶ Consolidate all stale` action
    (with confirmation + bulk-result modal showing per-space job IDs).
- **Bank tool count**: 10 → 11 tools. Total MCP tools: 42 → **43** (7 categories).

### Changed

- **DESIGN/live-mem/MCP_TOOLS_SPEC.md** — added missing sections for
  `bank_consolidation_queues` (latent gap from PR #21) and `bank_stale_spaces`,
  plus permission rows in the matrix.
- **DESIGN/live-mem/ARCHITECTURE.md** and **DEPLOIEMENT_PRODUCTION.md** — tool
  count refreshed to 43.
- **README inventories** — refreshed Admin and Bank tool counts so the main
  MCP matrix and repository tree both match the 43-tool server inventory.
- **`.env.example` and configuration docs** — aligned consolidation defaults
  with code (`CONSOLIDATION_MAX_NOTES=200`, `CONSOLIDATION_BATCH_SIZE=5`) and
  documented cooldown, validation, response, and admin API body-size settings.
- **MCP `serverInfo.version`** — now reports Live Memory's application version
  from `VERSION` instead of falling back to the installed `mcp` SDK package
  version.

### Tests

- New `tests/test_bank_stale_spaces.py` — **24 tests** including 8 explicitly
  anti-complacent assertions:
  - Boundary inclusivity on both axes (`>=`, not `>`).
  - Just-below-threshold isolation (no over-rounding into the stale set).
  - AND vs OR combination check (separate spaces failing each criterion).
  - Storage exception → safe error (no exception propagation, no internal
    string leak).
  - Denied spaces do NOT trigger S3 listing (no information leak / no wasted call).
  - Non-admin path passes `allowed_resources` to `list_spaces`, even when empty
    (v1.5.0 semantics: empty allowed = zero spaces, not all spaces).
  - Oldest filename actually matches the oldest timestamp (independent of S3
    return order).
- A new test discovered and fixed a real UI bug: previously the displayed
  `oldest_note_age_days` used `round(x, 2)`, which could display `5.0` while
  `is_stale=False` (true age `4.998`). Now uses truncation.
- New `tests/test_cli_surface_sync.py` — pins parity between `mcp_cli.py`,
  Click commands, interactive shell dispatch, and the `/admin` bank supervision
  tools (`bank_stale_spaces`, `bank_consolidation_queues`).
- Suite: **413 passed + 1 xfailed** (vs 384 baseline).

---

## [2.3.0] — 2026-05-21

### Added

- **`bank_consolidate` no-auto-polling contract** (PR #22) — the async job
  acknowledgement now carries a machine-readable contract telling callers not to
  watch/poll automatically:
  - New payload fields: `next_action="return_to_user_without_polling"` and
    `polling={recommended:false, mode:"manual_only", status_tool:"bank_consolidation_status", instruction:…}`.
  - Human-readable `message` field rephrased to make the call-once intent
    explicit on both `running` and `queued` payloads.
  - `bank_consolidation_status` is reclassified as a manual-only status check;
    clients must not call it automatically after every `bank_consolidate`.
  - Docs updated: `MCP_TOOLS_SPEC.md`, `CONCURRENCY.md`, `CONSOLIDATION_LLM.md`,
    `FAQ.md`, `README.md`, integration guides (Claude Code, Cline, Codex).

### Changed

- **FR docs retranslated** from latest EN sources (drift accumulated since v1.9.0):
  `FAQ.fr.md`, `README.fr.md`, `CLAUDE_CODE_INTEGRATION.fr.md`,
  `CLINE_INTEGRATION_GUIDE.fr.md`, `CODEX_INTEGRATION.fr.md`.

### Tests

- 384 passed + 1 xfailed. 2 new assertions cover the no-auto-polling contract
  on `running` and `queued` payloads (`tests/test_consolidation_queue.py`).

---

## [2.2.0] — 2026-05-19

### Added

- **Async consolidation queue** (PR #21 by @b1pb1p, issue #20) — `bank_consolidate`
  is now asynchronous: it enqueues a background job and returns immediately with a
  `job_id` and `queue_position`. Jobs are processed FIFO per space with one background
  worker per active space. Same-space requests are serialized instead of rejected with
  `conflict`. Duplicate pending jobs for the same agent/space are coalesced.
  - New `ConsolidationQueueService` singleton (`core/consolidation_queue.py`, 327 lines):
    FIFO queue, coalescing, worker per space, progress callbacks.
  - New `progress_callback` and `enforce_cooldown` parameters on `ConsolidatorService.consolidate()`.
  - `space_info` now includes `consolidation_queue` summary.
  - Queue durability is `in_memory_best_effort`: jobs are not persisted across process restart.
- **`bank_consolidation_status`** (42nd MCP tool) — Tracks an in-memory consolidation
  job returned by `bank_consolidate`. Returns `queued`, `running`, `succeeded`, `failed`,
  or `not_found`. Read permission required on the job's space.
- **`bank_consolidation_queues`** (42nd MCP tool) — Read-only view of consolidation
  lanes per space: lane state, running job, queued jobs, latest history, batch config.
  Accepts optional CSV `space_ids` filter. Exposed via `/admin` UI.
- **Admin console — Consolidation Lanes UI** — Dashboard and Explorer in `/admin` now
  display per-space consolidation lanes with lane state badges, running job progress
  (notes/batches), queue depth, and Consolidate buttons (all notes / my notes).
  Screenshots: `DESIGN/live-mem/assets/admin-consolidation-lanes-*.png`.
- **CLI support** — New Click commands `bank consolidation-status <job_id>` and
  `bank consolidation-queues [space_ids]`. Shell subcommands `bank consolidation-status`
  and `bank consolidation-queues`. Rich display functions `show_consolidation_job` and
  `show_consolidation_queues`.
- **12 tests** (`tests/test_consolidation_queue.py`) — Covers enqueue, coalescing,
  FIFO ordering, worker lifecycle, progress callbacks, trim history.

### Changed

- **Bank tool count**: 8 → 10 tools (+ `bank_consolidation_status`, `bank_consolidation_queues`).
  Total MCP tools: 40 → **42** (7 categories).
- **`bank_consolidate` behavior**: returns `{"status": "running"|"queued"}` with `job_id`
  instead of blocking until completion. Caller contract: call once at session end and
  return to the user — do not wait for completion and do not watch/poll automatically.
  `bank_consolidation_status(job_id)` and `space_info` remain available for explicit
  manual status checks only (see PR #22 for the machine-readable contract).
- **FAQ.md**: "conflict" → "queued" language updated.
- **DESIGN docs updated**: `CONCURRENCY.md`, `CONSOLIDATION_LLM.md`, `MCP_TOOLS_SPEC.md`
  reflect the async queue model.

### Tests

- Global suite: **384 passed + 1 xfailed** (+ 12 new queue tests). No regression.

---

## [2.1.0] — 2026-05-18

### Added

- **`S3_SIGNATURE_MODE` setting** — New configurable S3 signature strategy
  (PR #19 by @b1pb1p). Two modes:
  - `dual` (default, unchanged behavior): SigV2 for PUT/GET/DELETE/COPY,
    SigV4 for HEAD/LIST. Required for Dell ECS Cloud Temple.
  - `sigv4`: SigV4 for all operations. Required for MinIO (no SigV2 support),
    AWS S3 (SigV2 deprecated since 2018), and any modern S3-compatible provider.
  Strictly retrocompatible — default `dual` preserves byte-identical boto3
  client configuration. Internal refactor: `_client_v2`/`_client_v4` renamed
  to `_client_data`/`_client_meta` for clarity. 4 new tests in
  `TestS3SignatureMode`.
- **Claude Code integration guide** (FR/EN) — `CLAUDE_CODE_INTEGRATION.md`
  and `.fr.md` (PR #18 by @b1pb1p). Covers CLI method, JSON config, tool
  whitelisting, `CLAUDE.md` template, multi-agent workflows, troubleshooting,
  and Claude Desktop configuration.
- **Codex integration guide** (FR/EN) — `CODEX_INTEGRATION.md` and `.fr.md`.
  Covers `.codex/config.toml` configuration, `AGENTS.md` instructions, and
  the 3-step workflow (startup/work/consolidate).

### Fixed

- **1Password / LastPass pollution on `/admin` and `/live`** — Password managers
  injected icons and popups into form fields, cluttering the UI. All 17 `<input>`
  elements now carry `data-1p-ignore` (1Password) and `data-lpignore="true"`
  (LastPass) attributes across `admin.html`, `admin-app.js`, and `live.html`.

---

## [2.0.2] — 2026-05-16 (Admin Console Security Hardening)

**🔒 Security Audit & Remediation** — 10 findings identified, 7 fixed, 3 risk-accepted.
Full report: `DESIGN/live-mem/AUDIT_ADMIN_CONSOLE_2026-05-16.md`.

### Fixed

- **ADM-01 🔴 CRITICAL — XSS via attribute injection**: `esc()` in `admin-app.js`
  now escapes `"` → `&quot;` and `'` → `&#x27;`, preventing token names or
  descriptions from breaking out of HTML attributes.
- **ADM-02 🟠 HIGH — Exception message leakage**: `/api/tool` now uses
  `safe_error()` instead of bare `str(e)`, preventing exposure of internal
  file paths, S3 endpoints, and stack traces to the client.
- **ADM-03 🟠 HIGH — No CSP without WAF**: `_serve_file()` now adds
  `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options`,
  `Referrer-Policy`, and `Permissions-Policy` headers on all HTML responses
  (defense-in-depth, protects direct port 8002 access).
- **ADM-05 🟡 MEDIUM — No body size limit**: `/api/tool` now enforces
  `API_TOOL_MAX_BODY_BYTES` (default 1 MB, configurable). Returns `413`
  if exceeded, preventing memory exhaustion without WAF.
- **ADM-06 🟡 MEDIUM — No permission gate**: `/api/tool` now requires
  `write` permission minimum. Read-only tokens get `403 Forbidden`.
  ⚠️ **Breaking change** for read-only tokens using the admin console
  (use `/live` for read-only viewing instead).
- **ADM-08 🟡 MEDIUM — Incomplete audit trail**: `/api/tool` now emits a
  dedicated `admin_tool_call` audit entry with tool name, argument keys,
  and client identity before execution.
- **ADM-09 🔵 LOW — Internal API regression**: Added regression tests for
  `call_tool_direct()` covering unknown tools and uninitialized state.

### Added

- **`tests/test_admin_console_security.py`** — 13 non-complaisant tests
  (7 classes) covering all fixed findings. Convention: each test tries to
  *break* the fix, not validate the happy path.
- **`API_TOOL_MAX_BODY_BYTES`** setting in `config.py` (default 1 MB).
- **`DESIGN/live-mem/AUDIT_ADMIN_CONSOLE_2026-05-16.md`** — Full audit report
  with findings, remediations, risk acceptances, and test coverage matrix.

### Risk Accepted (Not Fixed)

- **ADM-04 🟠 HIGH** — Raw token in cookie (HttpOnly+SameSite=Strict sufficient
  for internal tool; server-side session store deferred to backlog).
- **ADM-07 🟡 MEDIUM** — Admin console HTML publicly visible (Swagger UI on `/`
  already exposes same information; login form requires public access).
- **ADM-10 🔵 LOW** — No CSRF token mechanism (SameSite=Strict + JSON
  Content-Type per OWASP guidelines for internal APIs).

---

## [2.0.1] — 2026-05-16 (Admin Console `/admin`)

**⚙️ Admin Console** — Full web administration interface for all 40 MCP tools,
with Dashboard improvements and maintenance UX overhaul.

### Added

- **Admin Console (`/admin`)** — New web interface exposing all 40 MCP tools via
  an internal proxy (`call_tool_direct()`). Backend: `POST /api/tool` route with
  auth middleware. Frontend: 4 files (`admin.html`, `admin.css`, `admin-api.js`,
  `admin-app.js`), dark theme, 7 sidebar categories (Dashboard, Spaces, Tokens,
  Explorer, Backups, Graph Bridge, Maintenance), dynamic typed forms, pretty
  modal results, CSP-compliant (event delegation via `data-action`).
- **Dashboard identity bar** — Compact 1-line bar showing current client name,
  auth type badge, and permission badges. Non-redundant with stat cards.
- **Health drill-down** — Health card is now clickable, opening a pretty modal
  with detailed service status (S3/LLM latency, model, bucket).
- **Upload Rules** — "📤 Upload New Rules" button in the Rules modal for each
  space. Supports file picker (`.md`) via FileReader or direct paste in textarea.
  Calls `space_update_rules` via the admin proxy.
- **Backup enrichments** — `backup_list` enriched with `files_count`,
  `total_size`, `description` from `_meta.json`. Dynamic columns in table.
  "Backup All" button for global snapshots.
- **Space chips** — Visual checkbox grid for token space management, with delta
  auto-calculation (add/remove).

### Changed

- **System section removed from sidebar** — Health/About/WhoAmI info merged
  into Dashboard (System was 8th category, now 7). No more redundant data.
- **Maintenance refactored** — Replaced 5 independent cards (with 4 duplicate
  space selectors) by a compact action list: 1 shared space selector in header,
  each tool = 1 row with icon + description + inline options + action button.
  Separated by accent dividers between bank ops / GC / token purge.
- **Pretty modals** — `renderPretty()` for `space_info`, `space_rules`,
  `space_summary`, and maintenance results. Structured key/value tables instead
  of raw JSON dumps.

---

## [2.0.0] — 2026-05-15 (Web UI improvements, branch `v2.0.0`)

**🖥️ Web UI improvements & E2E hardening** — CSP compliance, dynamic space
list, health indicator, bank tab overflow fix, and E2E test updates for v2.0.0
breaking changes.

### Fixed

- **CSP violation in `bank.js`** — inline `onclick="selectBank(...)"` handlers
  replaced with `addEventListener` + `data-filename` attributes to comply with
  `script-src 'self'` Content Security Policy (LM2-19 related).
- **Bank tabs overflow** — `.bank-tabs` now uses `flex-wrap: wrap` with
  `max-height: 4.5rem` and vertical scroll, replacing the invisible horizontal
  scroll. Handles spaces with 20+ bank files gracefully.
- **Space list not dynamic** — new `refreshSpaceList()` function in the
  auto-refresh cycle. New/deleted spaces appear automatically without page
  reload. Timer now starts on both `doLogin()` and `checkToken()` (page reload
  with valid cookie), and `loadSpace('')` no longer kills the timer.
- **Missing favicon** — added inline SVG emoji (🧠) `<link rel="icon">` to
  prevent 404 on `/favicon.ico`.
- **E2E test `bank_delete`** — added `confirm=True` parameter to match v2.0.0
  breaking change requiring explicit confirmation for destructive operations.

### Added

- **Version display in header** — `v2.0.0` badge loaded from `/health` endpoint
  (public, no auth needed), displayed next to "Live Memory" in the header bar.
- **Health status indicator** — the status dot now reflects the real `/health`
  endpoint status: 🟢 healthy, 🟠 degraded, 🔴 unhealthy. Clock always visible.
- **Health tooltip on hover** — hovering the status dot/clock shows a floating
  tooltip with full service details (S3, LLMaaS status, latency, bucket/model
  info, version).
- **`--pause N` flag in E2E test script** — `python scripts/test_recette.py
  --pause 10` inserts a N-second delay between key steps (space creation, notes,
  consolidation, bank read, cleanup), allowing real-time observation on `/live`.
  Compatible with `--step` (interactive) and `--no-cleanup`.

### Changed

- **Auto-refresh runs globally** — the refresh timer now persists across space
  selection/deselection. Only `doLogout()` stops it.
- **Web UI fully translated to English** — all user-facing strings in `live.html`,
  `app.js`, `api.js`, `bank.js`, `timeline.js`, `dashboard.js` switched from French
  to English (~40 strings). Date labels use `en-US` locale. HTML `lang="en"`.

---

## [2.0.0+] — 2026-05-15 (post-2.0.0, branch `v2.0.0`)

**🔬 Issue #17 — Consolidator backlog** : implementation of the 2 mitigations
left in backlog by v1.9.0 (post-pass validation `unattributed_claims_count`
+ `[inféré]` marker for inference traceability). No version bump: these
additions are **opt-in** (zero impact for existing deployments).

### Added

- **Post-consolidation validation pass** (`src/live_mem/core/consolidator.py`):
  new `_validate_unattributed_claims()` function comparing the bank
  before/after each consolidated batch and counting "claims" (numeric
  metrics, dates, versions, PR/issue refs, strong status keywords) that
  are neither sourced from a batch note nor explicitly tagged `[inféré]`.
  **Code-only approach** (regex + per-line diff): deterministic, zero
  additional LLM tokens, observable via the `validation` field of the
  `bank_consolidate` response.
- **SYSTEM_PROMPT rule #8 — `[inféré]` markers**: the LLM consolidator
  must now annotate every fact produced by transitive inference (rule #7)
  with the `[inféré]` marker. The marker serves as explicit attribution
  and ensures the validation pass does not flag those lines as unsourced.
  Note: the SYSTEM_PROMPT is kept in French for consistency with the
  7 other anti-hallucination rules already defined in French in v1.9.0.
- **New opt-in ENV vars** (safe defaults, disabled by default):
  - `CONSOLIDATION_VALIDATION_ENABLED=false` — enables the validation pass
    and the addition of the `validation` block in the MCP response.
  - `CONSOLIDATION_VALIDATION_MAX_EXAMPLES=20` — bounds the number of
    unsourced-claim examples returned (protects the payload size).

### Tests

- **`tests/test_issue17_validation.py`**: 53 non-complacent tests covering
  the helpers (`_extract_claim_tokens`, `_has_strong_status_claim`,
  `_normalize_for_match`, `_INFERRED_MARKER_RE`), the
  `_validate_unattributed_claims` function (happy paths, hallucination
  detection by counter-proof, example bounding, diff-only), the presence
  of rule #8 in the SYSTEM_PROMPT, and the opt-in configuration.
- **Global suite**: **346/346 PASS** (293 existing + 53 new). No
  regression on `test_security_hardening_v2.py` (122 v2.0.0 tests),
  `test_tokens.py`, `test_proxy.py`, or other suites.

### Fixed

- **`_METRIC_RE` regex**: added `(?=\W|$)` to correctly match metrics
  ending with `%` (e.g. `80%`), since `\b` is inoperative between `%`
  and a space. Added `[.,/]\d+` in the numeric pattern to match
  `171/171` as a single metric.
- **`_STATUS_KEYWORDS`**: enriched with French inflected forms (feminine
  singular/plural: `fermée`, `résolue`, `mergée`, `publiée`, `déployée`,
  `validée`, etc.) because Python's `\b` requires a `\w↔non-\w` boundary
  at word-end, which does not work for accented roots followed by `e`.

---


## [2.0.0] — 2026-05-15


**🛡️ Security Hardening Release** — full remediation of the 2026-05-15
internal audit (`DESIGN/live-mem/AUDIT_SECURITE_2026-05-15.md`). All 27
new findings (LM2-01 to LM2-31) are now addressed in a single release.
Breaking change: requires `mcp[cli]>=1.27.0`, drops `httpx-sse`, and
introduces a new `/api/login` + `/api/logout` cookie auth flow for the
web UI (the bearer header still works for agents).

### Security fixes (audit 2026-05-15)

#### Critical
- **LM2-01 — Stored XSS via bank filename** (`static/js/bank.js`) :
  filename was injected unescaped into `innerHTML`. Now `esc(name)` is
  applied systematically, and the server refuses dangerous chars
  (`< > " ' \\` + control chars) in `bank_write` filenames (LM2-12).

#### High
- **LM2-02 — SSRF in `graph_connect`** : new helper `_validate_gm_url()`
  blocks non-HTTP schemes, private/loopback/link-local IPs and cloud
  metadata endpoints (169.254.169.254) before any HTTP call or S3 persistence.
- **LM2-03 — Graph Memory token leak in space_export/backup_download** :
  new `mask_meta_secrets()` helper applied to every code path exposing
  `_meta.json` (REST API, `space_export`, `backup_download`).
- **LM2-04 — Token bearer in localStorage** : migrated to HttpOnly cookie
  via `/api/login` + `/api/logout`. The raw token never leaves the
  network → server; an XSS can no longer exfiltrate it.
- **LM2-05 — CSP `'unsafe-inline'` on `script-src`** : removed.
  CDN whitelist (`unpkg`, `jsdelivr`) also removed.
- **LM2-06 — CDN dependency for marked.js** : vendored locally in
  `static/vendor/` (marked@12.0.2 + DOMPurify@3.1.6) with SHA-384 hashes
  documented in `static/vendor/README.md`.
- **LM2-10 — Broken `gc.py`** : `live.write_note(agent=...)` removed
  in v0.8.1 but still called by GC. Replaced with new
  `_write_gc_notice()` writing directly to S3 with the orphan agent's
  identity in the front-matter.
- **LM2-19 — `marked.parse()` without sanitization** : DOMPurify applied
  systematically to all output of `marked.parse()`. Eliminates the second
  XSS vector (malicious Markdown in notes or bank files).

#### Medium
- **LM2-07 — `_fresh_token_store` ghost permissions** : new
  `invalidate_token_in_store()` called after every token mutation
  (revoke, delete, purge, update, bulk_update) prevents long-running
  operations from seeing stale permissions post-revocation.
- **LM2-08 — Bootstrap key asymmetry doc** : added explicit comment
  in `update_fresh_token()` explaining the volontary fallback.
- **LM2-09 — `backup_id` regex validation** : new `_parse_backup_id()`
  validates `space_id` regex + ISO timestamp format before any S3 access.
- **LM2-13 — Anti-erasure rewrite guard** : the consolidator now
  refuses any `rewrite` operation that shrinks the file by more than 70 %
  (suspect prompt injection). The original file remains untouched and the
  event is logged for audit.
- **LM2-14 — `CONSOLIDATION_MAX_NOTES` lowered** : default 500 → 200 to
  cap LLM budget exhaustion. Notes still bounded by 100 KB each.
- **LM2-15 — S3 Server-Side Encryption** : new `S3_SSE` env var
  (default off for Dell ECS compat). Set `S3_SSE=AES256` or `S3_SSE=aws:kms`
  + `S3_SSE_KMS_KEY_ID` to enable.
- **LM2-17 — X-Forwarded-For in audit logs** : new `_client_ip_from_scope()`
  reads `X-Forwarded-For` (or `X-Real-IP`) before falling back to
  `scope["client"]`. Audit logs now show real client IPs behind WAF.
- **LM2-18 — `bank_consolidate` cooldown** : new
  `CONSOLIDATION_COOLDOWN_SECONDS` env var (default 60s) prevents an
  agent from looping on `bank_consolidate` and saturating LLM budget.
- **LM2-24 — `str(e)` in public `/health`** : replaced by generic
  message ("S3 unreachable" / "LLMaaS unreachable"). Server-side
  warning log keeps the full exception. Same fix applied to
  `system_health` MCP tool for defense in depth.
- **LM2-25 — `str(e)` in consolidator responses** : LLM call and
  `test_connection` errors now return generic messages (full exception
  logged server-side). Debug mode (`MCP_SERVER_DEBUG=true`) keeps the
  legacy verbose behavior.
- **LM2-29 — Cross-tenant backup access** : `backup_restore` and
  `backup_delete` now call `check_access(space_id)` in addition to
  `check_manage_permission()`. A `manage` operator restricted to
  `["project-a"]` can no longer restore/delete a `project-b` backup.
- **LM2-31 — Missing `confirm=True`** : added to `bank_delete`
  (irreversible) and `admin_purge_tokens(revoked_only=False)` (the
  total-purge variant, otherwise leaves only the bootstrap key).

#### Low
- **LM2-12 — Filename validation** : see LM2-01 (combined fix).
- **LM2-22/21 — Egress filter + TLS internal** : documented in
  `DEPLOIEMENT_PRODUCTION.md` (no code change — operational guidance).
- **LM2-26 — Lower bounds bumped in `pyproject.toml`** :
  `mcp[cli]>=1.27.0` (CVE-2026-32871), `httpx>=0.28`, `boto3>=1.40`,
  `openai>=1.50`. `uv.lock` was already correct; this protects
  `pip install live-memory` builds.
- **LM2-27 — `httpx-sse` removed** from `pyproject.toml` (no longer
  imported since the Streamable HTTP migration).

### Breaking changes
- **Cookie auth required for web UI** : the `/live` frontend now uses
  `/api/login` (POST `{"token": "lm_..."}`) which sets a `livemem_auth`
  HttpOnly cookie. The legacy `localStorage` storage is auto-purged at
  first load. The bearer header keeps working for `/api/*` and `/mcp`.
- **`bank_delete` requires `confirm=True`** : add `confirm=True` to
  any CLI/automation call (alignment with `space_delete`, etc.).
- **`admin_purge_tokens(revoked_only=False)` requires `confirm=True`**.
- **`graph_connect` rejects private/loopback URLs** : if you used a
  loopback URL for local development, switch to a public address or
  add a temporary DNS entry. The error message points to the precise
  IP class blocked.
- **`pip install live-memory`** now requires `mcp[cli]>=1.27.0` (no
  longer compatible with mcp<1.27 due to CVE-2026-32871).

### Added
- New ENV vars : `CONSOLIDATION_COOLDOWN_SECONDS`, `S3_SSE`,
  `S3_SSE_KMS_KEY_ID`. See `.env.example` for examples.
- `src/live_mem/static/vendor/` — local copies of marked.min.js and
  purify.min.js with SHA-384 hashes documented (see vendor/README.md).
- `/api/login` and `/api/logout` REST endpoints (public, web UI auth).

### Removed
- `httpx-sse` dependency.
- `localStorage.livemem_auth_token` (legacy token storage, auto-purged
  at first load by `purgeLegacyTokenStorage()`).

### Validation
- **Audit summary** : 27/27 new findings addressed. 15/15 v1.0.0 fixes
  confirmed non-regressed in v1.9.0 source code review.
- **Tests** : 152/152 existing test suite expected to pass (no behavioral
  regression). New tests should be added for SSRF, XSS escaping, cookie
  auth and rewrite guard (next iteration).

### Files modified (summary)
| Domain | Files |
| ------ | ----- |
| Auth & middleware | `auth/middleware.py`, `auth/context.py`, `core/tokens.py` |
| Tools | `tools/graph.py`, `tools/bank.py`, `tools/backup.py`, `tools/admin.py`, `tools/system.py` |
| Core | `core/consolidator.py`, `core/storage.py`, `core/space.py`, `core/backup.py`, `core/gc.py`, `core/models.py`, `core/live.py` |
| Web UI | `static/live.html`, `static/js/bank.js`, `static/js/config.js`, `static/js/api.js`, `static/js/app.js`, `static/vendor/*` |
| Infra | `waf/Caddyfile`, `pyproject.toml`, `config.py` |
| Versioning | `VERSION` (1.9.0 → 2.0.0), `src/live_mem/__init__.py` |

---

## [1.9.0] — 2026-05-15

### Added
- **Anti-hallucination rules in LLM consolidator** (Issue #17) — 7 new rules in the SYSTEM_PROMPT to prevent the LLM from inventing content not derived from source notes:
  1. **Strict source attribution**: every factual claim in the bank MUST be derivable from at least one note. Empty sections stay empty or are marked "TBD".
  2. **Domain vocabulary preservation**: project-specific terms are used verbatim from notes, never reinterpreted via LLM priors.
  3. **Metrics gating**: numbers (LoC, test counts, percentages) only appear if explicitly sourced from a note. Sourced metrics are always carried over.
  4. **No invented structures**: file trees are NOT generated if notes don't describe them.
  5. **Agent/task isolation**: facts from different agents or independent tasks are NEVER merged into the same sentence.
  6. **Replaced items removal**: when a `decision` note introduces a new plan, old plan items are removed from the backlog.
  7. **Transitive status inference**: if Step N+1 is completed → Step N is marked as completed.
- **Note metadata in LLM prompt** — `_build_prompt()` now includes `[agent=X, category=Y, tags=Z]` metadata for each note, extracted from S3 filenames. Enables the LLM to properly isolate notes by agent/task.
- **Hallucination test suite** — `scripts/test_hallucination.py` with 5 scenarios and 25 assertions covering invented file structures, invented metrics, domain term reinterpretation, replaced plans, and stale statuses.

### Changed
- **Default language switched to English** — `README.md` is now in English (default for GitHub). French version moved to `README.fr.md`. Same for `FAQ.md` (EN) and `FAQ.fr.md` (FR).
- CHANGELOG language switched to English.
- **CLI fully translated to English** — All user-facing output (shell commands, Rich display labels, error messages, help strings, docstrings, comments) in `scripts/cli/` switched from French to English. 242+ string replacements across `shell.py`, `display.py`, and `commands.py`.
- **`bank_consolidate` cross-agent permission lowered: admin → manage** — Consolidating another agent's notes or all notes now requires `manage` instead of `admin`. Consistent with `manage` already allowing `bank_write` (direct bank modification). Write tokens still auto-detect their own agent.

### Removed
- `scripts/translate_cli.py` — One-shot translation script, no longer needed.
- `scripts/test_dedup_fix.py` — Deduplication tests redundant with `tests/` suite.

### Files modified
| File | Changes |
| --- | --- |
| `src/live_mem/core/consolidator.py` | SYSTEM_PROMPT: +7 anti-hallucination rules. `_build_prompt()`: note metadata (agent, category, tags) |
| `src/live_mem/tools/bank.py` | `bank_consolidate`: cross-agent permission `check_admin` → `check_manage` |
| `scripts/test_hallucination.py` | New: 5 scenarios (A-E), 25 assertions, reproducible hallucination detection |
| `README.md` | Now English (was French). Updated to v1.9.0, 40 tools, accurate counts |
| `README.fr.md` | New: French README (was `README.md`). Updated to v1.9.0 |
| `FAQ.md` | Now English (was French). +3 entries: anti-hallucination, bank_compact, proxy |
| `FAQ.fr.md` | New: French FAQ (was `FAQ.md`). +3 entries |
| `CHANGELOG.md` | Switched to English, added v1.9.0 entry |
| `VERSION` | 1.8.1 → 1.9.0 |
| `src/live_mem/__init__.py` | 1.8.1 → 1.9.0 |
| `DESIGN/live-mem/AUTH_AND_COLLABORATION.md` | Updated permission matrix: bank_consolidate cross-agent manage (was admin) |
| `DESIGN/live-mem/MCP_TOOLS_SPEC.md` | Updated bank_consolidate spec: manage for cross-agent |
| `scripts/cli/shell.py` | Full EN translation: SHELL_COMMANDS dict, docstrings, comments, messages (~70 replacements) |
| `scripts/cli/display.py` | Full EN translation: Rich panel titles, labels, column headers, docstrings (~120 replacements) |
| `scripts/cli/commands.py` | Full EN translation: Click help, docstrings, error/warning messages (~54 replacements) |
| `scripts/cli/client.py` | EN translation (previous session) |
| `scripts/cli/__init__.py` | EN translation (previous session) |

---

## [1.8.1] — 2026-05-14

### Ajouté
- **Support proxy HTTP sortant (`PROXY_URL`)** — Nouvelle variable d'environnement optionnelle pour router les appels sortants (S3 et LLM) via un proxy HTTP. Utilise une variable custom (`PROXY_URL`) plutôt que `HTTP_PROXY`/`HTTPS_PROXY` pour ne pas affecter les autres bibliothèques Python qui lisent automatiquement les variables d'environnement OS.
  - `storage.py` : proxy injecté dans les deux clients boto3 (SigV2 et SigV4) via `Config(proxies=...)`.
  - `consolidator.py` : proxy injecté dans `AsyncOpenAI` via un `httpx.AsyncClient(proxy=...)` pré-configuré.
  - `graph_bridge.py` : non supporté (limitation du SDK MCP `streamablehttp_client` — documenté dans le code).
  - Validation au démarrage : si `PROXY_URL` est défini, l'URL doit commencer par `http://` ou `https://`.

### Fichiers modifiés
| Fichier | Changements |
| --- | --- |
| `src/live_mem/config.py` | Nouveau champ `proxy_url: str = ""` + validation dans `_validate_config` |
| `src/live_mem/core/storage.py` | Construction de `_proxies` depuis `proxy_url`, injection dans `Config()` SigV2 et SigV4, log au démarrage |
| `src/live_mem/core/consolidator.py` | Import `httpx`, construction `httpx.AsyncClient(proxy=...)` si `proxy_url`, passage à `AsyncOpenAI(http_client=...)` |
| `src/live_mem/core/graph_bridge.py` | Note de limitation dans la docstring de `GraphMemoryClient.__init__` |
| `.env.example` | Nouvelle entrée `#PROXY_URL=http://10.185.132.250:3128` (commentée) |
| `README.md`, `README.en.md` | Ligne `PROXY_URL` dans le tableau des variables optionnelles |

---

## [1.8.0] — 2026-05-11

### Review PR #14 — second tour (2026-05-13)

Corrections apportées aux 4 points soulevés par Guillaume Lesur (`b1pb1p`) le 12/05 sur la PR #14 :

#### 1. Documentation explicite AND vs OR
- Toutes les docstrings (serveur, MCP tool, CLI Click `--help`) clarifient maintenant que **les filtres de `admin_bulk_update_tokens` sont combinés en AND**. Le piège `names="a,b,c" + name_contains="agent"` (exclusion silencieuse d'entrées qui ne matchent qu'un seul filtre) est désormais documenté à chaque niveau.

#### 2. Nouveau filtre `has_space` dans `admin_bulk_update_tokens`
- Match exact, case-**sensitive** (cohérent avec `admin_list_tokens`). Asymétrie volontaire vs `name_contains` (case-insensitive) : les noms sont libres, les `space_ids` sont des identifiants techniques.
- Cas d'usage cible : *"retirer `old-project` de tous les tokens qui l'ont"* en un seul appel, là où il fallait avant `list_tokens(has_space=…)` → parser → reconstruire `names=…` → `bulk_update`.
- Combinable en AND avec `names` et `name_contains`. **Au moins un** des trois filtres reste requis.
- CLI/shell : nouveau flag `--has-space` / `-s` sur `token bulk-update`.

#### 3. `include_revoked=False` par défaut dans `admin_bulk_update_tokens`
- **Asymétrie volontaire** avec `admin_list_tokens` (qui reste à `True` pour rétrocompat). Justification : on **observe** vs on **mute**. Modifier un token révoqué n'a aucun effet pratique mais peut créer des permissions fantômes en cas de ré-activation manuelle.
- Les tokens révoqués matchés par les filtres mais sautés sont retournés dans un nouveau champ **`skipped_revoked: [{name, hash}, …]`** — l'opérateur voit ce qu'il aurait pu rater.
- Opt-in pour modifier les révoqués : `include_revoked=True` (CLI : `--include-revoked`).
- Cas particulier : si TOUS les matches sont révoqués, le retour est `status=ok, updated=0, skipped_revoked=[…]` avec un message d'info explicite suggérant `--include-revoked`.

#### 4. Audit logging structuré
- Nouveau helper `_emit_bulk_update_audit()` qui émet un événement JSON sur le logger **`live_mem.audit`** (déjà utilisé par `AuditMiddleware`) **après** `_save_store` — uniquement pour les opérations effectivement persistées (les échecs de validation ne polluent pas l'audit).
- Contenu de l'event : `event=bulk_update_tokens`, `request_id` (depuis `ContextVar`), `caller` (`client_name` du token appelant), `filters`, `operations`, `updated`, `token_hashes` (liste complète des hash impactés), `skipped_revoked_count`.
- Permet la rejouabilité et l'audit a posteriori même si le retour MCP est perdu côté client.

#### Bonus FYI (non bloquants chez Guillaume)
- **Cas dégénéré `_add=X, _remove=X`** : test paramétrique explicite ajouté pour documenter que l'ordre `_remove` avant `_add` produit `X` présent en queue de liste finale (effet net intuitif).
- **Lock mono-process** : docstring de `bulk_update_tokens` précise désormais que l'atomicité est garantie *au sein d'une instance MCP*, et qu'un déploiement HA multi-instances nécessiterait un verrou externe (Redis/etcd, non implémenté).
- **Asymétrie case-sensitivity** : justification documentée dans les docstrings (noms libres → case-insensitive, identifiants techniques → case-sensitive).

#### Tests anti-régression ajoutés (+16, total `test_tokens.py` : 86 PASS)
| Test | Cible |
|------|-------|
| `test_bulk_update_by_has_space_only` | Cas d'usage Guillaume (retrait `old-proj` en un appel) |
| `test_bulk_update_has_space_case_sensitive` | Contrat case-sensitivity documenté |
| `test_bulk_update_three_filters_combined_AND` | AND-combinaison sur les 3 filtres simultanés |
| `test_bulk_update_requires_at_least_one_of_three_filters` | Message d'erreur cite les 3 filtres |
| `test_bulk_update_has_space_only_no_op_when_no_match` | Atomicité (no save_store si 0 match) |
| `test_bulk_update_excludes_revoked_by_default` | Asymétrie include_revoked False par défaut |
| `test_bulk_update_include_revoked_true_modifies_them` | Opt-in fonctionne |
| `test_bulk_update_filters_block_reflects_include_revoked` | Traçabilité dans la réponse |
| `test_bulk_update_only_revoked_matched_returns_skipped_zero_updated` | Cas tout révoqué — message UX |
| `test_bulk_update_skipped_revoked_carries_hash_for_audit` | Hash complet propagé |
| `test_bulk_update_emits_audit_log_on_success` | Anti-régression : log audit émis |
| `test_bulk_update_no_audit_on_validation_error` | Échec validation ≠ audit |
| `test_bulk_update_audit_records_skipped_revoked_count` | Tracabilité skipped_revoked dans audit |
| `test_apply_space_delta_degenerate_add_and_remove_same[×3]` | Cas dégénéré paramétrique |

**Suite complète : 152/152 PASS** (vs 136 avant ; +16 nouveaux tests, 0 régression).

#### Fichiers modifiés (review PR #14)
| Fichier | Changements |
|---------|-------------|
| `src/live_mem/core/tokens.py` | Import `json`/`logging` + `_audit_logger`. Refonte de `bulk_update_tokens` : nouveaux params `has_space` + `include_revoked`, sélection AND-combinée, gestion `skipped_revoked`, appel audit après save_store. Nouveau helper `_emit_bulk_update_audit()`. |
| `src/live_mem/tools/admin.py` | `admin_bulk_update_tokens` : nouveaux `Field` MCP pour `has_space` et `include_revoked` avec descriptions documentant l'asymétrie. Docstring refondue (AND, asymétries, audit). |
| `scripts/cli/commands.py` | `token bulk-update` : nouveaux flags `--has-space`/`-s` et `--include-revoked`. Validation client mise à jour (3 filtres acceptés). Dry-run client passe le filtre `has_space` et respecte `include_revoked`. |
| `scripts/cli/shell.py` | Handler `token bulk-update` : parsing des nouveaux flags `--has-space`/`--include-revoked`. Validation 3-filtres. Autocomplétion enrichie. |
| `tests/test_tokens.py` | +16 tests anti-complaisance (voir tableau ci-dessus). |
| `CHANGELOG.md` | Ce bloc. |

---

### Ajouté (issue #13 — workflow admin tokens)

- **`admin_update_token` : mode delta additif** — Nouveaux paramètres `space_ids_add` et `space_ids_remove` (CSV) pour ajouter/retirer des spaces à un token **sans avoir à reconstruire la liste complète**. Élimine la classe de bugs "révocation silencieuse par remplacement" : ajouter un nouveau space à un token qui en a déjà 7 ne demande plus de relire les 7 actuels. Idempotent (no-op si déjà présent/absent). `_remove` est appliqué avant `_add` (sémantique documentée).
  - Le mode legacy `space_ids` (remplacement complet) reste supporté pour la rétrocompat. Combiner remplacement et delta est **rejeté** avec une erreur explicite.
  - Le sucre `*`/`all` n'est **pas** accepté dans `_add`/`_remove` (sémantique ambiguë sur un delta).
  - La réponse en mode delta inclut `space_ids_before`, `space_ids_after`, `space_ids_added`, `space_ids_removed`, `space_ids_noop` pour traçabilité.
- **`admin_bulk_update_tokens` (8e outil admin, 40e outil MCP global)** — Met à jour N tokens en une seule opération, avec atomicité naturelle (tokens.json est un fichier S3 unique sauvé d'un bloc sous lock). En cas d'erreur de validation, aucune modification n'est persistée.
  - **Filtres** (au moins un requis) : `names` (CSV exacts) ou `name_contains` (sous-chaîne, case-insensitive). Combinables en AND.
  - **Opérations** (au moins une requise) : `space_ids_add`, `space_ids_remove`, `permissions`, `email`.
  - **Volontairement** : pas de mode `space_ids` (remplacement) — trop dangereux à propager sur N tokens.
  - Retour détaillé `{updated, tokens: [{name, hash, before, after, ...}], filters, operations}` pour audit post-opération.
- **`admin_list_tokens` : filtres serveur** — Nouveaux paramètres `name_contains`, `has_space`, `include_revoked` (défaut `True` pour rétrocompat). Évite de charger toute la liste côté client pour filtrer quelques tokens.

### CLI / Shell

- **CLI Click** :
  - `token update <hash>` : nouveaux flags `--add-spaces` / `-a`, `--remove-spaces` / `-r`. Garde-fou client pour rejeter `--space-ids` combiné avec un delta.
  - `token list` : nouveaux flags `--name-contains` / `-n`, `--has-space` / `-s`, `--no-revoked`.
  - **Nouvelle commande** `token bulk-update` avec dry-run par défaut (affichage des cibles via filtre `list`), `--confirm` requis pour appliquer.
- **Shell interactif** :
  - `token update` : flags `--add-spaces` / `--remove-spaces`.
  - `token list` : flags `--name-contains` / `--has-space` / `--no-revoked`.
  - Nouvelle sous-commande `token bulk-update` (avec dry-run).
  - Autocomplétion enrichie pour tous les nouveaux flags.
- **Affichage Rich** : nouvelle fonction `show_bulk_update_result()` qui affiche un tableau `before/after` par token modifié (ajouts, retraits, no-op).

### Tests (anti-complaisance — focus pièges réels)

- **50 nouveaux tests unitaires** (`tests/test_tokens.py`, total : 70 tests, 100% PASS) — chaque test cible un **piège concret** :
  - **Helpers** : `_apply_space_delta` (idempotence, ordre `remove avant add`, non-mutation input — anti-aliasing Python, doublon dans `to_remove` — anti `ValueError`), `_parse_csv_spaces` (dedup + strip), `_validate_update_mutex` (matrice paramétrée de **12 cas** combinant replace/add/remove/sucre).
  - **Atomicité `update_token`** : 4 scénarios d'échec où `_save_store` NE doit PAS être appelé (mutex replace+delta, sucre `*` dans delta, hash inconnu, permissions invalides combinées avec delta). Si un futur refactor place la validation après l'écriture, ces tests le détectent.
  - **Cohérence `bulk_update` before/after ↔ store** : test explicite qu'`after` reflète l'état mémoire réel (détecte un bug d'alias mutable où `before` finirait égal à `after`).
  - **Isolation `bulk_update_by_names_exact`** : 3 tokens, 2 matchés, vérifie que le 3e n'est PAS touché.
  - **AND vs OR sur filtres** : 2 tests construits pour piéger une logique OR (`list_tokens_combined_filters_are_AND`, `bulk_update_combined_filters_AND`).
  - **Idempotence E2E** : 2 appels successifs `bulk_update` avec même `space_ids_add` → 2e en no-op total, **un seul** "new-space" final (pas de doublon).
- **Total suite : 136 tests PASS** (aucune régression sur les 86 tests pré-existants).

### Décisions de design (challengeables)

- **Pas de remplacement complet en bulk** : volontairement absent. Propager un `space_ids="x,y"` sur N tokens est une opération destructive trop facile à mal utiliser. Si le besoin émerge, il faudra l'ajouter explicitement avec un garde-fou (ex: `--allow-replace`).
- **Sucre `*`/`all` interdit dans les deltas** : `space_ids_add="*"` voudrait dire "ajouter tous les spaces existants" — mais ce serait un snapshot figé incohérent avec la sémantique stricte v1.5.0. Pour cet usage, utiliser `space_ids="*"` en remplacement complet (sur un seul token).
- **`include_revoked=True` par défaut** : préserve strictement le comportement antérieur de `admin_list_tokens`. Aucun script existant n'est cassé.
- **Atomicité = naturelle** : pas de logique de rollback complexe. `tokens.json` est mono-fichier S3 — toutes les modifs sont en mémoire, puis une seule écriture finale. Si une validation échoue (permissions invalides détectées avant `_save_store`), rien n'est persisté.

### Fichiers modifiés

| Fichier | Changements |
| --- | --- |
| `src/live_mem/core/tokens.py` | Helpers `_parse_csv_spaces`, `_validate_update_mutex`, `_apply_space_delta`. Enrichissement de `update_token` (mode delta) et `list_tokens` (filtres). Nouvelle méthode `bulk_update_tokens`. |
| `src/live_mem/tools/admin.py` | Enrichissement `admin_update_token` (paramètres `space_ids_add`/`_remove`), `admin_list_tokens` (3 filtres). Nouveau tool `admin_bulk_update_tokens`. Compteur 7 → 8. |
| `scripts/cli/commands.py` | Enrichissement `token update`, `token list`. Nouvelle commande `token bulk-update` avec dry-run client. |
| `scripts/cli/display.py` | Nouvelle fonction `show_bulk_update_result()`. Affichage des filtres actifs dans `show_token_list()`. |
| `scripts/cli/shell.py` | Handler `_handle_token` enrichi : flags delta, filtres list, nouvelle sous-commande `bulk-update`. Autocomplétion mise à jour. |
| `tests/test_tokens.py` | **+42 tests** (helpers, update delta, list filtres, bulk_update). |
| `README.md`, `README.en.md`, `DESIGN/live-mem/ARCHITECTURE.md`, `DESIGN/live-mem/MCP_TOOLS_SPEC.md`, `DESIGN/live-mem/DEPLOIEMENT_PRODUCTION.md` | Compteur 39 → 40 outils MCP. |
| `VERSION`, `__init__.py`, `CHANGELOG.md` | Bump 1.7.4 → 1.8.0. |

---


## [1.7.4] — 2026-05-10

### Ajouté
- **Réparation automatique de JSON LLM tronqué** — Nouvelle fonction `_repair_json()` dans `consolidator.py` qui détecte les erreurs "Unterminated string" (fréquentes avec qwen3.x, `finish_reason=stop`) et répare le JSON avant de retomber sur le retry coûteux. Stratégie : tronquer au point de l'erreur, fermer les structures JSON ouvertes via `_close_json_structure()`, supprimer la dernière opération tronquée. Économise ~100s et ~50K tokens par occurrence.
- **Garde-fou retry sur repair vide** — Si la réparation JSON réussit mais produit 0 `file_edits` (troncature très précoce), le code retombe sur le retry LLM au lieu d'accepter silencieusement un résultat vide (évite la perte de données).
- **29 tests unitaires** (`tests/test_json_repair.py`) — Couvrent `_close_json_structure` (10 tests : niveaux imbriqués, strings avec accolades, échappements, backslash) et `_repair_json` (19 tests : comptage exact d'opérations, troncature dans content/heading/filename, create tronqué, guillemets échappés, scénario réaliste qwen3.6, intégrité JSON).

### Fichiers modifiés
| Fichier | Changements |
| --- | --- |
| `src/live_mem/core/consolidator.py` | `_call_llm()` : tentative de repair avant retry, garde-fou `repaired_files > 0`. Nouvelles fonctions `_repair_json()` et `_close_json_structure()` |
| `tests/test_json_repair.py` | **Nouveau** — 29 tests unitaires (5 classes) |
| `DESIGN/live-mem/CONSOLIDATION_LLM.md` | Section 8.4 : réparation automatique JSON |
| `VERSION`, `__init__.py`, `CHANGELOG.md` | Bump 1.7.3 → 1.7.4 |

---

## [1.7.3] — 2026-05-07

### Amélioré
- **Logging diagnostic consolidation** — Le WARNING `LLM: JSON invalide` dans `_call_llm()` logge maintenant `finish_reason`, `completion_tokens` et `visible_tokens_est` en plus des champs existants. Permet de diagnostiquer les JSON tronqués (thinking tokens consommant le budget de sortie, cap API côté serveur, ou arrêt prématuré du modèle) sans avoir à deviner la cause.

### Fichiers modifiés
| Fichier | Changements |
| --- | --- |
| `src/live_mem/core/consolidator.py` | `_call_llm()` : capture `finish_reason` et `completion_tokens` après chaque appel LLM, ajout de `visible_tokens_est` dans le WARNING |
| `VERSION`, `__init__.py`, `CHANGELOG.md` | Bump 1.7.2 → 1.7.3 |

---

## [1.7.2] — 2026-05-05

### Corrigé
- **Issue #11 — Token UX traps** — Trio cohérent de bugs UX autour des tokens (pas une faille de sécurité, mais source garantie de friction à chaque onboarding).
  - **Documentation contradictoire avec v1.5.0** : les `Field.description` et docstrings de `admin_create_token` (`tools/admin.py`) et `TokenService.create_token` (`core/tokens.py`) disaient encore "vide = tous les espaces", alors que la sémantique stricte v1.5.0 stipule "vide = aucun accès" pour les non-admin. Corrigé pour refléter la réalité du code.
  - **Tokens "muets" créés silencieusement** : `admin_create_token(space_ids="")` produisait un token techniquement valide mais incapable d'accéder à aucun espace existant (403 systématique). La réponse contient désormais un champ `warning_no_access` explicite quand le token résultant n'a aucun espace autorisé et n'est pas admin.
  - **Sucre syntaxique `*` / `all`** : `admin_create_token(space_ids="*")` ou `space_ids="all"` prend désormais un **snapshot** des espaces existants au moment de la création (les futurs nouveaux spaces ne sont pas inclus, pour rester aligné avec la sémantique stricte v1.5.0). La réponse inclut `snapshot_taken: true` et un message `info` détaillant la liste matérialisée.
  - **Préfixe `sha256:` non documenté** : `_find_token_by_hash` exigeait que le hash passé à `admin_revoke_token` / `admin_delete_token` / `admin_update_token` inclue le préfixe `sha256:` retourné par `admin_list_tokens`. Si l'utilisateur copiait juste la partie hex, l'opération retournait silencieusement `Token introuvable`. La méthode normalise désormais l'entrée et accepte les deux formes (`sha256:abc...` ou `abc...`). La validation min 16 chars s'applique maintenant sur le hex pur, et le message d'erreur indique la longueur du hex pur (review #12).
  - **Cohérence `admin_update_token`** (review #12) : le sucre `*`/`all` et le `warning_no_access` sont également appliqués à `update_token` (extraction d'un helper privé `_resolve_space_ids`), évitant que la même trappe UX réapparaisse lors d'une mise à jour.

---

## [1.7.1] — 2026-05-04

### Corrigé
- **Bug critique : contextvars stale dans les sessions MCP Streamable HTTP** — Les `check_access()`, `check_write_permission()`, `check_manage_permission()` et `check_admin_permission()` lisaient `current_token_info` depuis un contextvar figé à l'initialisation de la session MCP. Le SDK MCP Python crée un task `anyio` long-running par session (`streamable_http_manager.py:243-276`) ; les tool handlers s'exécutent dans ce task avec une copie du contexte asyncio de l'initialisation. Les mises à jour de `space_ids` (via `add_space_to_token` lors de `space_create`) ou de permissions (via `admin_update_token`) étaient invisibles jusqu'au redémarrage de la session MCP.
  - **Fix** : Ajout d'un `_fresh_token_store` (dict global mutable) dans `auth/context.py`, alimenté par `AuthMiddleware` à chaque requête HTTP. Les fonctions `check_xxx()` utilisent désormais `_get_effective_token_info()` qui priorise le store frais sur le contextvar stale.
  - **Impact** : les `space_ids` et permissions sont immédiatement visibles après modification, sans reconnexion MCP.
- **CLI `token list` : hash tronqué inutilisable** — Rich tronquait le hash SHA-256 (73 chars) à ~10 chars (`sha256:f9…`), rendant impossible le copier-coller pour `token update/revoke/delete` (minimum 16 chars requis par `_find_token_by_hash`). Fix : troncature explicite à 24 chars (`sha256:f97fbf7c3b4460ff…`), suffisant pour identifier un token de manière unique. Hash complet toujours disponible via `--json`.
- **`space_list` : données stale** — Utilisait `current_token_info.get()` directement au lieu de `_get_effective_token_info()`, souffrant du même bug de contextvar stale.

### Fichiers modifiés
| Fichier | Changements |
| --- | --- |
| `src/live_mem/auth/context.py` | +56 lignes : `_fresh_token_store`, `update_fresh_token()`, `_get_effective_token_info()`. Les 4 `check_xxx()` utilisent `_get_effective_token_info()` |
| `src/live_mem/auth/middleware.py` | `AuthMiddleware.__call__()` : appel `update_fresh_token()` après validation |
| `src/live_mem/tools/space.py` | `space_list()` : utilise `_get_effective_token_info()` |
| `scripts/cli/display.py` | `show_token_list()` : hash tronqué à 24 chars au lieu de laisser Rich tronquer |
| `VERSION`, `__init__.py`, `README.md`, `README.en.md`, `CHANGELOG.md` | Bump 1.7.0 → 1.7.1 |

---

## [1.7.0] — 2026-04-27

### Corrigé
- **Issue #8 — Web UI : descriptions d'espaces non tronquées dans le dropdown** — Sur l'interface `/live`, le sélecteur `<select id="spaceSelect">` affichait `space_id — description` complète. Quand un espace avait une description longue (plusieurs phrases), le dropdown s'étirait au-delà du viewport et cassait la mise en page du header. Les `<option>` HTML natifs ne supportant pas `text-overflow: ellipsis`, la troncature doit se faire côté JS.
  - **Fix JS** (`src/live_mem/static/js/app.js` — `fillSpaceSelect`) : description tronquée à `MAX_DESC = 70` caractères avec suffixe `…`. Description complète conservée en `option.title` (tooltip natif au survol). La valeur `option.value = s.space_id` reste intacte (zéro impact fonctionnel).
  - **Fix CSS** (`src/live_mem/static/css/live.css`) : ajout de `#spaceSelect { max-width: 360px; text-overflow: ellipsis; }` pour borner la largeur du sélecteur fermé, même quand un `space_id` lui-même est très long.

### Fichiers modifiés
| Fichier                                | Changements                                                                                       |
| -------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `src/live_mem/static/js/app.js`        | `fillSpaceSelect()` : troncature à 70 chars + `option.title` avec description complète           |
| `src/live_mem/static/css/live.css`     | Règle `#spaceSelect` : `max-width: 360px` + `text-overflow: ellipsis`                            |
| `VERSION`, `__init__.py`, `README.md`, `README.en.md`, `CHANGELOG.md` | Bump 1.6.1 → 1.7.0 |

---

## [1.6.1] — 2026-04-25


### Corrigé
- **Audit middleware "unauthenticated"** — `AuditMiddleware` wrappait `AuthMiddleware`, son `finally` s'exécutait après le `reset()` du contextvar → le client apparaissait toujours comme `"unauthenticated"` dans les logs d'audit. Fix : réordonnancement de la pile middleware (Audit maintenant wrappé PAR Auth). Ajout d'un audit log directement dans `AuthMiddleware` pour les rejets 401.
- **Diagnostic consolidation JSON** — Ajout du logging de la réponse brute du LLM (tronquée à 500 chars) en cas d'échec de parsing JSON (`json_error`, `raw_len`, `raw_preview`). Permet de diagnostiquer la cause racine des échecs de consolidation.

### Modifié
- **Pile middlewares ASGI** — Corrigée : RequestId → Metrics → Auth → **Audit** → Logging → ResponseLimit → StaticFiles → MCP. L'audit est désormais wrappé par Auth pour accéder au `current_token_info` avant son `reset()`. Les rejets 401 sont audités par Auth directement.

---

## [1.6.0] — 2026-04-25

### Ajouté (PR #7 — BeArchiTek/Benoit Kohler)
- **Health probe enrichi** — `/health` teste désormais S3 **et** LLMaaS, retourne `healthy`/`degraded`/`unhealthy` avec détail par service, latence et disponibilité du modèle configuré. Probe LLMaaS via `models.list()` (zéro consommation de tokens).
- **4 middlewares ASGI** — `RequestIdMiddleware` (UUID `X-Request-Id`), `MetricsMiddleware` (`/metrics` Prometheus + JSON), `AuditMiddleware` (trail JSON structuré), `ResponseLimitMiddleware` (512 KB sur `/api/*`, paths MCP exclus).
- **MCP tool annotations** — `readOnlyHint`, `destructiveHint`, `idempotentHint` sur les 39 outils MCP, conforme au standard MCP.
- **Config validation fail-fast** — Le serveur refuse de démarrer si la configuration est invalide (port hors range, S3 partiel, URL malformée, bootstrap key par défaut, etc.).
- **37 tests unitaires** — Couverture des middlewares, de la validation de config et du health probe (`tests/test_config.py`, `tests/test_middleware.py`).
- **Logging JSON structuré** — Format JSON pour l'agrégation de logs en production (ELK, Loki).
- **Docker Compose profiles** — MinIO en `profiles: [dev]` : `docker compose up` = prod (S3 distant), `docker compose --profile dev up` = dev (MinIO local).

### Modifié
- **Migration dépendances** — `requirements.txt` → `pyproject.toml` + `uv.lock`. ⚠️ **Breaking change** : `pip install -r requirements.txt` ne fonctionne plus, utiliser `uv sync --frozen`.
- **Dockerfile** — Multi-stage avec `uv sync --frozen`, layer caching séparé deps/source.
- **CLI health** — Utilise HTTP `/health` directement au lieu du handshake MCP complet (plus rapide, pas d'auth nécessaire).
- **Pile middlewares ASGI** — Réordonnée : Audit → Auth → RequestId → Metrics → ResponseLimit → Logging → StaticFiles → MCP. L'audit middleware est placé avant l'auth pour capturer les rejets 403.
- **CLI `token update`** — Fix du bug `--permissions` avec `default=None` au lieu de `default=""` (Click.Choice rejetait la valeur vide).

### Corrigé
- **ResponseLimitMiddleware** — Paths MCP (`/mcp`) exclus de la troncature pour protéger `space_export` et `backup_download` (archives base64 > 512 KB).

---

## [1.5.1] — 2026-04-22

### Corrigé
- **Détection hiérarchique des doublons** — `_detect_duplicates()` comparait les headings de façon plate : deux `### X` sous des `## A` et `## B` différents étaient faussement détectés comme doublons et fusionnés via LLM, corrompant la bank à chaque consolidation. Fix : chemin hiérarchique complet (`## Parent A > ### Child > #### Grandchild`), supportant la profondeur arbitraire.
- **Optimisation performance dédup** — Ajout de 2 fast-paths dans `_deduplicate_content()` qui évitent l'appel LLM quand c'est inutile : (1) versions identiques → garder la dernière, (2) sous-ensemble de lignes → garder la version la plus complète. Comparaison au niveau des lignes (`issubset`) et non des sous-chaînes (`in`) pour éviter les faux positifs.
- **Tests obsolètes corrigés** — 7 tests dans `test_bank_compact.py` mis à jour pour refléter la limite universelle `BANK_FILE_MAX_SIZE=15360` et les instructions de compaction génériques (v1.4.0+).

### Ajouté
- **14 tests unitaires de détection hiérarchique** dans `test_dedup_fix.py` — couvrent : faux doublons (### sous ## différents), vrais doublons (même parent), profondeur 3 niveaux, mix vrais/faux, algorithme itératif, préservation du contenu non-dupliqué.
- **Template Product Management Memory Bank v1.1.0** (PR #4) — Nouveau modèle de rules `RULES/product.management.memory.bank.md` (390 lignes) pour les équipes Produit (Product Management, Product Design, UX Writing). Hiérarchie de 10+ fichiers obligatoires (`productVision`, `portfolio`, `marketIntelligence`, `userKnowledge`, `stakeholders`, `designSystem`, `communicationGuide`, `engineeringContext`, `discoveryPlaybook`, `activeContext`, `roadmapProgress`) + fichiers dynamiques (`persona-[name].md`, `framework-[name].md`). **6 templates de rules** disponibles dans `RULES/` (était 5).

### Amélioré
- **CLI : unwrap ExceptionGroup/TaskGroup** (PR #5) — Le SDK MCP utilise des `anyio.TaskGroup` qui encapsulent les erreurs HTTP (ex: 401) dans un `ExceptionGroup`. L'erreur réelle était masquée par un message générique. La CLI déroule désormais récursivement les `BaseExceptionGroup` pour afficher la cause racine.
- **CLI : acceptation du statut `degraded`** (PR #5) — `_run_tool()` considère désormais `degraded` comme un statut de succès (en plus de `ok`, `healthy`, `created`, etc.), évitant un faux message d'erreur quand le health check retourne un service partiellement disponible.

### Fichiers modifiés (8)
- `src/live_mem/core/consolidator.py` — `_detect_duplicates()` hiérarchique, `_deduplicate_content()` fast-paths
- `scripts/test_dedup_fix.py` — 14 tests unittest (réécriture complète)
- `scripts/test_bank_compact.py` — 7 tests corrigés (limites universelles)
- `scripts/cli/client.py` — Unwrap `BaseExceptionGroup` dans le handler d'erreur MCP (PR #5)
- `scripts/cli/commands.py` — Ajout de `degraded` dans les statuts de succès (PR #5)
- `RULES/product.management.memory.bank.md` — Nouveau template Product Management (PR #4)
- `RULES/README.md` — Ajout du template Product Management dans le catalogue
- `VERSION`, `__init__.py`, `CHANGELOG.md`, `README.md`, `README.en.md`

---

## [1.5.0] — 2026-04-15

### Ajouté
- **Permission `manage`** — 4ème niveau de permission dans la hiérarchie : `admin ⊃ manage ⊃ write ⊃ read`.
  - `manage` donne accès aux opérations de maintenance : `bank_write`, `bank_delete`, `bank_repair`, `bank_compact`, `space_delete`, `space_update_rules`, `backup_restore`, `backup_delete`.
  - Un agent standard (`write`) ne peut plus manipuler directement les fichiers bank ni supprimer des espaces.
  - `admin` reste requis pour la gestion des tokens et le GC.
- **`check_manage_permission()`** dans `auth/context.py` — nouveau helper de vérification.
- **Migration automatique v1.5.0** au démarrage du serveur — les tokens non-admin ayant `space_ids=[]` se voient assigner tous les espaces existants.
- **Timeout 600s documenté** dans `GUIDE_INTEGRATION_CLINE.md` — toutes les configurations MCP (Cline et Claude Desktop) incluent désormais `"timeout": 600`.

### Modifié
- **Sémantique de `space_ids=[]`** — signifie désormais "aucun accès" pour les non-admin (au lieu de "tous"). Un token fraîchement créé n'a accès à rien d'existant — il crée ses propres espaces (auto-ajoutés via `add_space_to_token`).
- **`add_space_to_token()`** — ajoute toujours le space, même si `space_ids` est vide (anciennement skippé).
- **`space_list`** — retourne une liste vide pour les non-admin avec `space_ids=[]` (au lieu de tout lister).
- **`backup_list`** — filtrage adapté pour les non-admin avec `space_ids=[]`.
- **8 outils remontés en `manage`** :
  - De `write` → `manage` : `bank_delete`, `bank_repair`, `bank_compact`
  - De `admin` → `manage` : `bank_write`, `space_delete`, `space_update_rules`, `backup_restore`, `backup_delete`
- **CLI et shell** — support complet du niveau `manage` dans la validation des permissions et l'autocomplétion.

### Fichiers modifiés (15)
- `src/live_mem/auth/context.py` — `check_manage_permission()`, docstring 4 niveaux, `check_access()` inversé
- `src/live_mem/core/tokens.py` — `VALID_PERMISSIONS` + `manage`, `migrate_empty_space_ids()`, `add_space_to_token()` simplifié
- `src/live_mem/tools/bank.py` — 4 outils passés en `check_manage`
- `src/live_mem/tools/space.py` — `space_delete` et `space_update_rules` en `check_manage`, `space_list` filtrage
- `src/live_mem/tools/backup.py` — `backup_restore` et `backup_delete` en `check_manage`, `backup_list` filtrage
- `src/live_mem/server.py` — migration v1.5.0 au démarrage
- `scripts/cli/commands.py` — `VALID_PERMISSIONS` mis à jour
- `scripts/cli/shell.py` — `_VALID_PERMS`, autocomplétion, messages d'aide
- `VERSION`, `__init__.py`, `CHANGELOG.md`, `GUIDE_INTEGRATION_CLINE.md`

---

## [1.4.1] — 2026-04-11

### Corrigé
- **Anti-doublon sémantique dans le consolidateur** — Après une compaction, le consolidateur ne reconnaissait pas que les entrées résumées (format court) et les nouvelles notes (format détaillé) décrivaient le même travail. Résultat : doublons massifs dans `progress.md` (ex: "Phase B — LiveMemoryService créé" ET "Session du 10/04 — Phase B COMPLÈTE"). Ajout d'une instruction explicite dans le `SYSTEM_PROMPT` pour détecter les jalons sémantiquement équivalents et enrichir l'existant au lieu de créer de nouvelles sections.
- **Migration du modèle LLM par défaut** — Remplacement de `qwen3-2507:235b` par `qwen3.5:27b` dans toute la codebase (config, descriptions MCP, documentation). Les descriptions MCP utilisent désormais des références génériques (`LLMAAS_MODEL`) au lieu de noms de modèles en dur.

---

## [1.4.0] — 2026-04-11

### Ajouté — Bank Compaction (auto-compaction + outil MCP `bank_compact`)

#### Outil MCP `bank_compact` (39ème outil, admin only)
Expose la mécanique de compaction (implémentée dans le consolidateur depuis v1.4.0-beta) comme outil MCP autonome. Analyse chaque fichier bank et compare sa taille à la limite configurée (`activeContext.md`: 8KB, `progress.md`: 20KB, autres: 15KB).

- Mode **dry-run** (par défaut) : rapporte les fichiers surdimensionnés et leur ratio, sans modification.
- Mode **apply** : compacte effectivement via appel LLM dédié, protégé par le lock de consolidation.
- Permission **admin** requise (cohérent avec `bank_write` et `bank_repair` qui modifient la bank directement).
- **CLI Click** : `bank compact <space_id> [--apply] [--json]`.
- **Shell interactif** : `bank compact <space> [--apply]` avec autocomplétion.
- **Affichage Rich** (`show_bank_compact_result`) : panel résumé + tableau détaillé par fichier (taille, limite, ratio coloré vert/jaune/rouge, statut de compaction avec % de réduction).
- Catégorie Bank : 7 → **8 outils MCP**.

#### Auto-compaction intégrée au pipeline de consolidation
- Déclenchement automatique si la bank dépasse `compact_threshold` (60%) du `max_tokens` avant consolidation.
- Méthode publique `compact_bank(space_id, dry_run)` dans `ConsolidatorService`.
- 5 nouveaux paramètres de configuration : `compact_threshold`, `bank_file_max_size`, `bank_active_context_max_size`, `bank_progress_max_size`.
- **Budget de sortie dynamique** (`_call_llm`) : `output_budget = max(8192, context_window - estimated_input_tokens)` — évite les dépassements de context window.
- **SYSTEM_PROMPT anti-accumulation** : instructions explicites pour nettoyer l'obsolète et résumer les sections anciennes.
- Tests automatisés : `scripts/test_bank_compact.py` — 20/20 PASS.

### Corrigé
- **Bug CLI `--json` : ANSI pollution** — `show_json()` utilisait `Rich.Syntax` qui injectait des codes ANSI dans le JSON, rendant la sortie `--json` non-parseable quand redirigée ou pipée. Corrigé par un `print(json.dumps(...))` brut sur stdout. Le JSON est désormais machine-readable et pipeable (`| jq`, `| python -c "import json..."`, etc.).

---

## [1.3.1] — 2026-04-01

### Corrigé
- **Bug `IndexError: list index out of range` dans `_deduplicate_content()`** — La méthode de déduplication des sections dupliquées crashait quand un fichier bank contenait **plusieurs headings dupliqués différents** (ex: 5 doublons dans `activeContext.md`). La cause : les indices des doublons étaient calculés une seule fois au début (`_detect_duplicates`), puis utilisés dans une boucle `for` qui modifiait la liste de sections (`pop()`). Après le traitement du premier doublon, les indices des doublons suivants pointaient vers des positions invalides dans la liste raccourcie → `IndexError`.
- **Fix** : remplacement de la boucle `for` par une boucle `while` qui **re-détecte les doublons** sur le contenu mis à jour à chaque itération. Chaque itération ne traite qu'un seul doublon, reconstruisant le contenu entre chaque fusion. Sécurité anti-boucle infinie (max 50 itérations) et vérification défensive des indices avant accès.

### Ajouté
- **Script de test `scripts/test_dedup_fix.py`** — 17 tests unitaires reproduisant le bug exact (5 doublons simultanés, heading triplé, fichier sans doublons) et validant le nouveau comportement. Confirme que l'ancien algorithme crashe et que le nouveau fonctionne sans perte de contenu.

---

## [1.3.0] — 2026-03-28

### Ajouté
- **Fix anti-doublons consolidateur** (3 niveaux de protection) :
  - **Fix A — Prévention** : `_op_add_section()` vérifie si le heading existe déjà et convertit automatiquement en `replace_section` avec WARNING dans les logs. Empêche la création de doublons à la source.
  - **Fix B — Détection + Fusion LLM** : nouvelles méthodes `_deduplicate_content()` et `_merge_sections_via_llm()` dans `ConsolidatorService`. Après chaque action `edit` ou `rewrite`, détecte les sections dupliquées et les fusionne intelligemment via un appel LLM dédié (prompt court, température 0.1). Fallback mécanique (garder la dernière occurrence) si le LLM échoue.
  - **Fix C — Guidance LLM** : instruction explicite dans le `SYSTEM_PROMPT` interdisant `add_section` sur un heading déjà existant.
- Fonction utilitaire `_detect_duplicates()` : détecte les headings dupliqués dans un fichier Markdown.

### Modifié
- `test_recette.py` : mise à jour des références de version v0.7.5 → v1.2.0, 32/33 → 38 outils MCP.

### Corrigé
- **Bug récurrent de doublons de sections** dans les Memory Banks : les sections comme "État technique V2" ou les phases dans `progress.md` pouvaient être dupliquées par le consolidateur LLM lors d'opérations `add_section` sur des headings existants. Le bug était auto-renforçant (les doublons dans la bank étaient reproduits par le LLM lors des consolidations suivantes).

---

## [1.2.0] — 2026-03-27

### Ajouté
- **Outil MCP `space_update_rules`** (38ème outil, admin only) : permet de mettre à jour les rules d'un espace sans le supprimer/recréer. Implémenté dans `core/space.py`, `tools/space.py`, CLI Click, shell interactif et affichage Rich.
- **Template RULES v1.2.0** (`RULES/live-mem.standard.memory.bank.md`) : 3 nouvelles règles de consolidation anti-duplication :
  - Règle 7 : "Mettre à jour, ne pas dupliquer" (remplace "Enrichir, ne pas écraser")
  - Règle 9 : "Nettoyer l'obsolète" (retirer les items terminés des backlogs, corriger les métriques)
  - Règle 10 : "Garder les fichiers concis" (activeContext < 8 KB, autres < 15 KB)
- Limites de taille dans les descriptions de fichiers bank : taille cible pour `activeContext.md`, instruction de remplacement pour `systemPatterns.md`, items terminés à retirer dans `progress.md`.

### Modifié
- Catégorie Space : 8 → 9 outils MCP.
- Règle de consolidation n°1 nuancée : "Ne jamais perdre d'information **pertinente**" — les données obsolètes, remplacées ou dupliquées DOIVENT être nettoyées.

---

## [1.1.0] — 2026-03-26

### Ajouté
- **Rules par défaut (`DEFAULT_RULES_FILE`)** — Nouveau paramètre `.env` permettant de spécifier un fichier de rules Markdown utilisé par défaut quand `space_create` est appelé sans paramètre `rules`. Élimine le besoin de passer manuellement les rules à chaque création d'espace.
- **Paramètre `rules` optionnel dans `space_create`** — Si vide, le serveur charge automatiquement les rules depuis le fichier configuré dans `DEFAULT_RULES_FILE`. Message d'erreur explicite si aucun fichier par défaut n'est configuré.
- **Dossier `RULES/` inclus dans l'image Docker** — Ajout de `COPY RULES/ RULES/` dans le Dockerfile pour que les templates de rules soient disponibles dans le conteneur.

### Modifié
- `src/live_mem/config.py` — Ajout du champ `default_rules_file: str = ""` dans `Settings`.
- `src/live_mem/tools/space.py` — `rules` rendu optionnel avec fallback sur `DEFAULT_RULES_FILE`.
- `.env.example` — Documentation du nouveau paramètre `DEFAULT_RULES_FILE`.
- `Dockerfile` — Copie du dossier `RULES/` dans l'image.

---

## [1.0.0] — 2026-03-24

### Sécurité — Audit complet et 15 remédiations

**Audit de sécurité complet** réalisé sur la v0.9.0, couvrant 10 domaines (authentification, validation des entrées, S3, LLM, web, réseau, cryptographie, configuration, gestion d'erreurs, supply chain). Rapport : `DESIGN/live-mem/AUDIT_SECURITE_2026-03-24.md` (27 constats, correspondance OWASP API Security Top 10).

**15 vulnérabilités corrigées** — 56/56 tests PASS.

#### 🔴 Critiques (3)
- **VULN-01 — Race condition tokens.json** — `validate_token()` ne fait plus de `_save_store()` pour `last_used_at`. Le champ est mis en cache mémoire (`_last_used_cache`), éliminant la race condition avec `create_token()`/`revoke_token()` qui sont sous lock.
- **VULN-02 — API REST sans contrôle d'accès par espace** — `check_access(space_id)` ajouté dans les 5 endpoints `/api/*` (`_api_space_info`, `_api_live_notes`, `_api_bank_list`, `_api_bank_file`). Un token restreint ne peut plus lire les données d'un autre espace via l'interface web.
- **VULN-07 — Validation de taille sur content/rules/description** — Limites implémentées : `MAX_NOTE_CONTENT_SIZE=100000` (live_note), `MAX_RULES_SIZE=50000` (space_create), `MAX_DESCRIPTION_SIZE=500` (space_create). Empêche le DoS par épuisement S3.

#### 🟠 Élevés (6)
- **VULN-03 — Correspondance hash tokens sécurisée** — Nouveau helper `_find_token_by_hash()` avec minimum 16 caractères de préfixe et détection d'ambiguïté (erreur si plusieurs tokens matchent). Appliqué à `revoke_token`, `delete_token`, `update_token`.
- **VULN-08 — Validation space_id dans check_access()** — Regex `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$` vérifiée dans `check_access()` avant la vérification des permissions. Empêche les path traversal via `_system`, `_backups`, `../`.
- **VULN-12 — Token Graph Memory masqué** — Le token Graph Memory dans `_meta.json` est masqué dans les réponses API (8 premiers caractères + `...`). Empêche l'escalade de privilèges read → write sur Graph Memory.
- **VULN-17 — CORS supprimé** — Le header `Access-Control-Allow-Origin: *` a été supprimé de `_send_json()`. L'interface `/live` est servie par le même serveur (même origine), aucun CORS nécessaire.
- **VULN-25 — Bootstrap key obligatoire** — Le serveur refuse de démarrer si `ADMIN_BOOTSTRAP_KEY` est dans la liste des clés faibles (`change_me_in_production`, `changeme`, `admin`, `password`, vide) ou fait moins de 32 caractères (warning).

#### 🟡 Moyens (5)
- **VULN-04 — Comparaison constant-time bootstrap key** — `hmac.compare_digest()` remplace `==` pour la comparaison du bootstrap key.
- **VULN-09 — Validation filename contre path traversal** — Rejet des filenames contenant `..` ou commençant par `/` dans `_api_bank_file`.
- **VULN-10 — Paramètre limit borné** — `live_read` limite le `limit` à `MAX_LIVE_READ_LIMIT=500`.
- **VULN-13 — Logging des erreurs dans delete_many()** — Les erreurs de suppression S3 sont loggées (`logger.warning`) au lieu d'être ignorées silencieusement.
- **VULN-27 — Erreurs masquées en production** — Nouveau helper `safe_error()` dans `auth/context.py` : message générique en prod (`MCP_SERVER_DEBUG=false`), message complet en debug. 34 blocs `except` remplacés dans 6 fichiers tools.

#### 🟢 Faible (1)
- **VULN-11 — bank_relpath dans API REST** — `_api_bank_list` utilise `bank_relpath()` au lieu de `split("/")[-1]` pour supporter les sous-dossiers.

### Fichiers modifiés
| Fichier                                        | Changements                                                                                                                  |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `src/live_mem/core/tokens.py`                  | VULN-01 (`_last_used_cache`), VULN-03 (`_find_token_by_hash`, min 16 chars)                                                  |
| `src/live_mem/auth/context.py`                 | VULN-08 (regex space_id), VULN-27 (`safe_error()` helper)                                                                    |
| `src/live_mem/auth/middleware.py`              | VULN-02 (check_access API), VULN-04 (hmac), VULN-09 (filename), VULN-11 (bank_relpath), VULN-12 (mask token), VULN-17 (CORS) |
| `src/live_mem/core/live.py`                    | VULN-07 (MAX_NOTE_CONTENT_SIZE), VULN-10 (MAX_LIVE_READ_LIMIT)                                                               |
| `src/live_mem/core/space.py`                   | VULN-07 (MAX_RULES_SIZE, MAX_DESCRIPTION_SIZE)                                                                               |
| `src/live_mem/core/storage.py`                 | VULN-13 (logging delete_many)                                                                                                |
| `src/live_mem/server.py`                       | VULN-25 (bootstrap key check au démarrage)                                                                                   |
| `src/live_mem/tools/*.py` (×6)                 | VULN-27 (34 blocs `safe_error()`)                                                                                            |
| `DESIGN/live-mem/AUDIT_SECURITE_2026-03-24.md` | Rapport d'audit complet (nouveau)                                                                                            |

---

## [0.9.0] — 2026-03-19

### Changé — Support natif des sous-dossiers dans la Memory Bank

**Refonte architecturale** — La bank supporte désormais les fichiers dans des sous-dossiers (ex: `personaProfiles/acheteur.md`). Auparavant, tous les `split("/")[-1]` dans le code ne gardaient que le basename des clés S3, ce qui causait des doublons quand le LLM créait des fichiers dans des sous-répertoires définis par les rules.

- **Cause racine identifiée** — Bug découvert sur le space `presales` : les rules mentionnent `personaProfiles/` comme dossier et `1.MEMORY_BANK/` comme répertoire racine. Le LLM créait des fichiers aux chemins `presales/bank/personaProfiles/acheteur.md` et `presales/bank/1.MEMORY_BANK/personaProfiles/acheteur.md`, mais le code extrayait uniquement `acheteur.md` → doublons avec perte de correspondance → `bank_read("acheteur.md")` retournait "not_found".
- **`bank_relpath(s3_key, space_id)`** — Nouvelle fonction utilitaire dans `storage.py`. Extrait le chemin relatif complet depuis le préfixe `{space_id}/bank/`. Ex: `presales/bank/personaProfiles/acheteur.md` → `personaProfiles/acheteur.md`.
- **21 occurrences de `split("/")[-1]` remplacées** par `bank_relpath()` dans 6 fichiers : consolidator.py, bank.py (tools), space.py, graph_bridge.py.
- **`_sanitize_filename()` enrichi** — Garde les `/` (sous-dossiers légitimes). Supprime les préfixes parasites que le LLM invente en lisant les rules (`1.MEMORY_BANK/`, `MEMORY_BANK/`, `bank/`). Nettoie les `/` en début/fin et les doubles `//`.
- **Nettoyage auto des doublons** — Lors de chaque écriture bank (create/edit/rewrite), le consolidateur supprime automatiquement les anciennes clés S3 qui sanitisent vers le même nom de fichier.
- **`bank_read` avec fallback** — Si la clé directe n'existe pas, scanne les clés S3 réelles et cherche par correspondance sanitisée.

### Ajouté — 2 nouveaux outils MCP : `bank_write` et `bank_delete`

- **`bank_write`** 👑 (admin) — Écrit ou remplace un fichier bank directement, sans passer par la consolidation LLM. Utile pour les corrections manuelles, les migrations, et les cas où la consolidation échoue. Nettoie automatiquement les doublons Unicode.
- **`bank_delete`** 👑 (admin) — Supprime un fichier bank et tous ses doublons (clés S3 avec le même nom sanitisé). Irréversible.
- **37 outils MCP** (était 35) — catégorie Bank passe de 5 à 7 outils.

### Fichiers modifiés
| Fichier                             | Changements                                                                                                                                                  |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/live_mem/core/storage.py`      | + `bank_relpath()` — extraction chemin relatif bank depuis clé S3                                                                                            |
| `src/live_mem/core/consolidator.py` | `_sanitize_filename()` : garde `/`, supprime préfixes parasites. `_build_prompt()` + `_write_results()` : utilisent `bank_relpath`. Nettoyage auto doublons. |
| `src/live_mem/tools/bank.py`        | `bank_read_all`/`bank_list` : retournent chemins relatifs. + `bank_write` et `bank_delete` (admin). `bank_read` avec fallback Unicode. 7 outils (était 5).   |
| `src/live_mem/core/space.py`        | `get_info()` et `get_summary()` : utilisent `bank_relpath`                                                                                                   |
| `src/live_mem/core/graph_bridge.py` | `push()` : utilise `bank_relpath`                                                                                                                            |
| `VERSION`                           | 0.8.2 → 0.9.0                                                                                                                                                |

### ⚠️ À compléter (follow-up)
- CLI Click : ajouter commandes `bank write`, `bank delete`, `bank repair`
- Shell interactif : ajouter handlers correspondants
- Web UI bank.js : affichage raccourci des noms longs dans les onglets (cosmétique, fonctionnel en l'état)

---

## [0.8.2] — 2026-03-16

### Ajouté — Nouveau template de rules `book.memory.bank.md` et fix shell `space create`

- **`RULES/book.memory.bank.md`** — Nouveau modèle de rules pour **l'écriture de livres**. 6 fichiers obligatoires (bookbrief, bookContext, narrativeDesign, writingContext, activeContext, progress). Conçu pour les agents IA assistant d'écriture : suivi narratif, voix et ton, compteurs de mots, tracking par chapitre, retours de relecture. Instructions de consolidation spécialisées avec mapping adapté (ex: `decision` → `narrativeDesign.md` si c'est un choix structurant).
- **Renommage `standard.memory.bank.md` → `live-mem.standard.memory.bank.md`** — Le modèle standard porte désormais un nom plus explicite.
- **5 templates de rules** disponibles dans `RULES/` (était 3) : standard, medical, presales, book, live-mem.standard.

### Amélioré — Template Custom Instructions (lecture des notes non consolidées au démarrage)
- **Étape 3 ajoutée dans la procédure de démarrage** — `live_read(space_id="{SPACE}")` est désormais obligatoire au lancement de chaque tâche. Permet de récupérer les notes écrites entre deux sessions qui n'ont pas encore été consolidées dans la bank.
- **Justification** : sans cette étape, l'agent rate du contexte récent (notes d'autres agents, notes de sessions précédentes non consolidées). Risque de refaire du travail déjà fait ou de rater des décisions récentes.
- **Procédure de démarrage** : 5 étapes (était 4) — `space_rules` → `bank_read_all` → **`live_read`** → lire le contenu → identifier le focus.
- **Note explicative** ajoutée sous le bloc d'avertissement pour expliquer le "pourquoi" aux agents.

### Corrigé — Shell interactif `space create` (parsing des options)
- **Bug : `space create -d "desc" -r rules.md id` échouait** — Le shell utilisait un parsing purement positionnel (`args[1]` = space_id, `args[2]` = description, `args[3:]` = rules). Les options nommées (`-d`, `-r`) étaient interprétées comme le space_id → erreur `"space_id invalide : '-d'"`.
- **Nouveau parsing** — Support complet des options nommées, aligné sur la CLI Click :
  - `-d` / `--description` — Description de l'espace
  - `-r` / `--rules-file` — Chemin vers un fichier rules (.md), lu automatiquement
  - `--rules` — Contenu rules en ligne (inline)
  - `-o` / `--owner` — Propriétaire
- **Rétrocompatibilité** — La forme positionnelle `space create <id> <desc> <rules>` fonctionne toujours.
- **Autocomplétion enrichie** — `-d`, `-r`, `-o`, `--description`, `--rules-file`, `--rules`, `--owner`, `--email`, `-e` ajoutés aux mots-clés du shell.

### Fichiers modifiés
| Fichier                                  | Changements                                                                     |
| ---------------------------------------- | ------------------------------------------------------------------------------- |
| `RULES/book.memory.bank.md`              | Nouveau — Modèle écriture de livre (6 fichiers, suivi narratif, compteurs mots) |
| `RULES/live-mem.standard.memory.bank.md` | Renommé — Ancien `standard.memory.bank.md`                                      |
| `RULES/README.md`                        | Table des templates mise à jour (5 templates)                                   |
| `scripts/cli/shell.py`                   | Handler `space create` refactoré (options nommées), aide et autocomplétion MAJ  |
| `.clinerules/standard.memory.bank.md`    | Étape 3 `live_read` ajoutée au démarrage + note explicative                     |
| `clinerules.md`                          | Idem — template racine mis à jour avec `live_read` au démarrage                 |
| `scripts/README.md`                      | Version v0.8.1 → v0.8.2                                                         |
| `scripts/README.en.md`                   | Version v0.7.5 → v0.8.2                                                         |
| `GUIDE_INTEGRATION_CLINE.md`             | v0.7.4 → v0.8.2 : template + workflow + minimaliste + 30→35 outils              |

---

## [0.8.1] — 2026-03-16

### Changé — Token = Agent (suppression du paramètre `agent` dans `live_note`)

**Inversion de la décision v0.2.0** — Le découplage Token / Agent (v0.2.0) permettait de passer un `agent` libre dans `live_note`, indépendamment du token utilisé. Cette liberté causait des problèmes critiques à la consolidation :

- **Notes orphelines silencieuses** — Si l'agent écrivait sous un nom différent du `client_name` de son token, le consolidateur (qui filtre par pattern `_{agent}_` dans le nom de fichier S3) ne trouvait jamais ces notes. Aucune erreur affichée → perte de données invisible.
- **Usurpation d'identité** — Un agent pouvait écrire des notes sous le nom d'un autre agent.
- **Notes éparpillées** — Un agent écrivant parfois avec `agent=""` et parfois avec `agent="mon-nom"` créait deux identités distinctes.

**Nouveau comportement (v0.8.1)** :
- Le paramètre `agent` est **supprimé** de `live_note` (outil MCP + core + CLI)
- L'identité de l'agent est **toujours** le `client_name` du token d'authentification
- Chaque token = une identité unique = un agent
- `live_read(agent=...)` conserve son paramètre de filtre (utile pour lire les notes d'autres agents)
- `bank_consolidate(agent=...)` inchangé (admin peut cibler un agent spécifique)

### Fichiers modifiés
| Fichier                                     | Changements                                                         |
| ------------------------------------------- | ------------------------------------------------------------------- |
| `src/live_mem/tools/live.py`                | Paramètre `agent` supprimé de `live_note`                           |
| `src/live_mem/core/live.py`                 | Paramètre `agent` supprimé de `write_note()`, auto-détection forcée |
| `scripts/cli/commands.py`                   | Option `--agent/-a` retirée de `live note` CLI                      |
| `DESIGN/live-mem/AUTH_AND_COLLABORATION.md` | Section 1.5 réécrite : Token = Agent (v0.8.1)                       |
| `DESIGN/live-mem/MCP_TOOLS_SPEC.md`         | Signature `live_note` mise à jour (sans `agent`)                    |

---

## [0.8.0] — 2026-03-13

### Ajouté — Consolidation par lots et protection Unicode

- **Consolidation par lots (batches)** — Les notes sont désormais traitées par lots de `CONSOLIDATION_BATCH_SIZE` (défaut 5) au lieu d'être envoyées toutes en une seule passe au LLM. Chaque lot relit la bank à jour depuis S3 (intégration incrémentale). Si un lot échoue, les précédents sont déjà intégrés (résilience). Avec 60 notes → 12 batches de 5 → 12 appels LLM courts au lieu d'1 énorme.
- **Sanitisation des filenames LLM (`_sanitize_filename`)** — Supprime automatiquement 20 types de caractères Unicode invisibles (ZWSP, BOM, Soft Hyphen…) et normalise 10 types de tirets Unicode vers le tiret ASCII standard, avant chaque écriture S3. Corrige le bug de "drift Unicode" du LLM sur les réponses JSON longues (fichiers bank illisibles par `bank_read` et l'interface `/live`).
- **Outil `bank_repair`** 👑 (admin) — 35ème outil MCP. Scanne les fichiers bank existants, détecte les noms corrompus par des caractères Unicode invisibles, et les répare (dry_run par défaut).
- **Test de cohérence bank** dans `test_recette.py` — Après consolidation, vérifie que chaque fichier retourné par `bank_list` est lisible via `bank_read` (étape 7/8 de la suite recette).
- **`CONSOLIDATION_BATCH_SIZE`** dans `config.py` — Nouvelle variable d'environnement configurable (défaut 5).
- **Nouvelles métriques de consolidation** : `batches_total`, `batches_completed`, `batch_size` dans la réponse de `bank_consolidate`.

### Corrigé

- **Bug filenames Unicode invisibles** — Le LLM `qwen3.5:27b` insère parfois des caractères Unicode invisibles dans les noms de fichiers à partir du ~8ème fichier dans les réponses JSON longues, rendant ces fichiers illisibles. Corrigé par la sanitisation systématique + la consolidation par lots qui produit des réponses plus courtes.

### Modifié

- **`_write_results()` accepte `skip_meta=True`** — En mode batch, le meta est mis à jour une seule fois à la fin de la consolidation (pas à chaque lot).
- **35 outils MCP** (était 34) — catégorie Bank passe de 4 à 5 outils.

---

## [0.7.7] — 2026-03-13

### Ajouté — Outil MCP `space_update` (modification des métadonnées d'un espace)
- **Nouvel outil `space_update`** ✏️ (write) — Permet de modifier la description et/ou le owner d'un espace existant. Les rules restent immuables.
- **34 outils MCP** (était 33) — catégorie Space passe de 7 à 8 outils.
- Méthode `SpaceService.update()` dans `core/space.py` : GET + PUT sur `_meta.json`, modification sélective des champs fournis.

### Amélioré — CLI et affichage
- **CLI Click** : `space update <id> -d "desc" [-o "owner"]` avec aide contextuelle et exemples
- **Shell interactif** : `space update <id> -d "desc" [-o "owner"]` avec parsing flags nommés, autocomplétion, aide contextuelle
- **Affichage Rich** : `show_space_updated()` — panel avec champs modifiés
- **Colonne Owner dans `space list`** — le champ owner était absent de l'affichage (corrigé)
- **Owner dans `space info`** — ajouté entre Description et Notes live
- **Test de recette** : `space_update` ajouté dans la suite qualité (21/21 PASS)

### Fichiers modifiés
| Fichier                       | Changements                                                                                |
| ----------------------------- | ------------------------------------------------------------------------------------------ |
| `src/live_mem/core/space.py`  | Nouvelle méthode `update()` — modification sélective de `_meta.json`                       |
| `src/live_mem/tools/space.py` | Nouvel outil `space_update` — check_access + check_write, 3 params annotés                 |
| `scripts/cli/commands.py`     | Commande Click `space update` avec `--description/-d`, `--owner/-o`                        |
| `scripts/cli/shell.py`        | Handler `space update` + SHELL_COMMANDS + import `show_space_updated`                      |
| `scripts/cli/display.py`      | `show_space_updated()`, colonne Owner dans `show_space_list`, Owner dans `show_space_info` |
| `scripts/test_recette.py`     | Test `space_update` ajouté dans la suite qualité                                           |

---

## [0.7.6] — 2026-03-13

### Ajouté — Répertoire `RULES/` : modèles de rules pour la création d'espaces
- **Nouveau répertoire `RULES/`** avec des modèles de rules (templates) prêts à l'emploi pour créer des espaces mémoire via `space_create`.
- **`RULES/standard.memory.bank.md`** — Modèle **general purpose** pour tout projet logiciel. 6 fichiers obligatoires (projectbrief, productContext, activeContext, systemPatterns, techContext, progress). C'est le modèle utilisé par le space `live-mem`.
- **`RULES/medical.memory.bank.md`** — Modèle **suivi médical**. 7 fichiers obligatoires (profilGeneral, histoireDiagnostic, contexteSante, medicamentationTraitements, specialistesSuivi, profilSante, progression) + 2 optionnels (visualisationDonnees, protocoleUrgence). Inclut une **règle de fiabilité absolue** pour les données biologiques (double vérification, fidélité parfaite, unités conservées).
- **`RULES/presales.memory.bank.md`** — Modèle **avant-vente B2B**. 5 fichiers de base (proposalContext, activeAnalysis, analysisProgress, rulesLearned, methodologieAnalyse) + fichiers **personas dynamiques** (un par décideur : dirigeant, acheteur, DSI, RSSI, expert). Gestion des contradictions, capitalisation des patterns argumentaires, tracking visuel avec ✅🔄⏱️❓.
- **`RULES/README.md`** — Documentation complète : explication du rôle des rules, catalogue des modèles, guide d'utilisation, instructions pour créer un modèle personnalisé.
- **Section "Pourquoi les Rules sont critiques"** dans le README — Explique que les rules sont **injectées mot pour mot dans le prompt du LLM consolidateur** à chaque `bank_consolidate`. Ce n'est pas de la documentation passive — c'est un contrat direct avec le modèle.

### Fichiers ajoutés/modifiés
| Fichier                         | Changements                                                                                                   |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `RULES/standard.memory.bank.md` | Nouveau — Copie des rules du space `live-mem` (general purpose)                                               |
| `RULES/medical.memory.bank.md`  | Nouveau — Modèle médical adapté pour Live Memory (7+2 fichiers, fiabilité absolue, mapping consolidation)     |
| `RULES/presales.memory.bank.md` | Nouveau — Modèle avant-vente B2B (5+N fichiers, personas dynamiques, gestion contradictions, tracking visuel) |
| `RULES/README.md`               | Nouveau — Documentation des templates de rules avec explication du lien rules → LLM                           |
| `README.md`                     | Badge version 0.7.6, mention du répertoire RULES/ dans la structure du projet                                 |

---

## [0.7.5] — 2026-03-13

### Ajouté — Outil MCP `system_whoami` (identité du token courant)
- **Nouvel outil `system_whoami`** — Permet à tout agent ou utilisateur de connaître l'identité avec laquelle il contacte le serveur MCP. Retourne : `client_name`, `auth_type` (bootstrap/token), `permissions`, `allowed_spaces`, et pour les tokens S3 : `email`, `token_hash`, `created_at`, `expires_at`, `last_used_at`.
- **CLI Click** : `python scripts/mcp_cli.py whoami` (avec `--json` pour le JSON brut)
- **Shell interactif** : `whoami` (avec autocomplétion)
- **Affichage Rich** : panel coloré `👤 Qui suis-je ?` avec icônes de permissions (🔑 read, ✏️ write, 👑 admin)
- **33 outils MCP** (était 32) — catégorie System passe de 2 à 3 outils

### Fichiers modifiés
| Fichier                        | Changements                                                                                                                             |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `src/live_mem/tools/system.py` | Nouvel outil `system_whoami` — lit le contextvar `current_token_info`, enrichit avec les métadonnées du TokenService pour les tokens S3 |
| `scripts/cli/display.py`       | `show_whoami_result()` — panel Rich avec identité, type, droits, espaces, métadonnées token                                             |
| `scripts/cli/commands.py`      | Commande Click `whoami` au niveau racine (comme `health` et `about`)                                                                    |
| `scripts/cli/shell.py`         | Commande `whoami` dans le dispatcher, SHELL_COMMANDS et autocomplétion                                                                  |

---

## [0.7.4] — 2026-03-13

### Corrigé — Sécurité `bank_consolidate` (incohérence permissions)
- **`agent=""` avec write consolidait TOUTES les notes** — Un token `write` (non-admin) pouvait consolider les notes de tous les agents en passant `agent=""`, contournant l'isolation par agent. C'était un fallback de rétrocompatibilité v0.2.0 qui créait une incohérence de sécurité.
- **Nouveau comportement** :
  - `write` + `agent=""` → auto-détecte le `client_name` du token et consolide **uniquement ses propres notes**
  - `write` + `agent=caller` → OK (même chose explicitement)
  - `write` + `agent=autre` → REFUSÉ (admin requis)
  - `admin` + `agent=""` → consolide TOUTES les notes (inchangé)
  - `admin` + `agent=xxx` → consolide les notes de l'agent xxx (inchangé)
- **Matrice des permissions** clarifiée dans le code avec commentaires détaillés.

### Amélioré — Template Custom Instructions simplifié (suppression de `{AGENT}`)
- **Le paramètre `agent` n'est plus nécessaire** dans le template — il est auto-détecté depuis le token d'authentification, tant pour `live_note` (déjà en place) que pour `bank_consolidate` (nouveau).
- Le template ne contient plus qu'**une seule variable** : `{SPACE}` (le nom du space).
- Suppression de la règle "toujours passer agent=..." — l'agent est implicite.
- Simplification de la documentation : les utilisateurs sont invités à copier le template directement dans leurs Custom Instructions globales, sans mentionner explicitement l'arborescence locale `.clinerules`.

### Fichiers modifiés
| Fichier                                     | Changements                                                                                                  |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `src/live_mem/tools/bank.py`                | Logique d'autorisation `bank_consolidate` réécrite — auto-set `agent=caller` pour les tokens write non-admin |
| `GUIDE_INTEGRATION_CLINE.md`                | Mise à jour v0.7.4, template simplifié sans agent, focus sur les Custom Instructions                         |
| `README.md` et `README.en.md`               | Nettoyage des exemples, lien direct vers le guide d'intégration                                              |
| `scripts/test_recette.py`                   | +3 tests isolation (consolidation permissions) : write+agent='', write+agent=autre, reader consolidate       |
| `DESIGN/live-mem/AUTH_AND_COLLABORATION.md` | Matrice permissions mise à jour (bank_consolidate auto-détection)                                            |
| `DESIGN/live-mem/MCP_TOOLS_SPEC.md`         | Spec bank_consolidate mise à jour (v0.7.4 agent auto-détecté)                                                |

---

## [0.7.3] — 2026-03-13

### Amélioré — Template `.clinerules/standard.memory.bank.md` (DRY)
- **Centralisation de la configuration** — Le nom du space (`SPACE`) et de l'agent (`AGENT`) ne sont plus hardcodés à chaque ligne. Ils sont définis **une seule fois** dans un bloc de configuration en haut du fichier, puis référencés partout via les placeholders `{SPACE}` et `{AGENT}`.
- **Avant** : `live-mem` apparaissait 12 fois et `cline-dev` 9 fois — chaque exemple, règle et commande devait être modifié manuellement pour réutiliser le template.
- **Après** : 2 lignes à modifier pour adapter le template à n'importe quel projet/agent.
- **Exemples simplifiés** — Les 6 exemples `live_note` répétitifs (un par catégorie) sont remplacés par un seul exemple générique avec `<catégorie>`.
- **Guide d'intégration Cline** (`GUIDE_INTEGRATION_CLINE.md`) mis à jour pour référencer le nouveau format template avec `{SPACE}/{AGENT}`.

### Fichiers modifiés
| Fichier                               | Changements                                                                               |
| ------------------------------------- | ----------------------------------------------------------------------------------------- |
| `.clinerules/standard.memory.bank.md` | Refactoring complet : config centralisée + placeholders `{SPACE}`/`{AGENT}`               |
| `GUIDE_INTEGRATION_CLINE.md`          | Version 0.7.3, section Custom Instructions mise à jour avec le template `{SPACE}/{AGENT}` |
| `README.md`                           | Badge version 0.7.3                                                                       |
| `README.en.md`                        | Badge version 0.7.3                                                                       |

---

## [0.7.2] — 2026-03-12

### Corrigé — Bug CLI `token create` (parsing des options)
- **`permissions` transformé de `click.argument` (positionnel) en `click.option` (nommé)** — Quand on tapait `token create KSE --email kevin@... --permissions read,write`, Click interprétait `--email` comme la valeur positionnelle de `permissions` → erreur `"Permissions invalides : '--email'"`. Le paramètre est maintenant une option nommée `--permissions/-p` (required), cohérente avec `token update`.
- **Shell interactif corrigé** — Le handler `token create` du shell parsait `args[2]` en dur comme permissions. Réécrit avec un parsing de flags nommés (`--permissions/-p`, `--email/-e`, `--space-ids/-s`, `--expires-in-days`) — même pattern que `token update`. Rétrocompatibilité préservée : la forme positionnelle `token create KSE read,write` fonctionne encore dans le shell.
- **Aide enrichie** — Exemples ajoutés dans le help de `token create` (CLI et shell).

### Nouvelle syntaxe
```bash
# CLI Click
token create KSE -p read,write --email kevin@cloud-temple.com
token create bot-ci --permissions read
token create admin-ops -p read,write,admin

# Shell interactif (rétrocompat positionnelle)
token create KSE -p read,write --email kevin@cloud-temple.com
token create KSE read,write    # ← fonctionne encore
```

### Fichiers modifiés
| Fichier                   | Changements                                                                             |
| ------------------------- | --------------------------------------------------------------------------------------- |
| `scripts/cli/commands.py` | `permissions` : `click.argument` → `click.option("--permissions", "-p", required=True)` |
| `scripts/cli/shell.py`    | Handler `token create` réécrit avec parsing de flags nommés                             |
| `scripts/README.md`       | Syntaxe `token create` mise à jour (v0.7.2)                                             |
| `scripts/README.en.md`    | Syntaxe `token create` mise à jour (v0.7.2)                                             |

---

## [0.7.1] — 2026-03-12

### Sécurité — Alignement des droits avec Graph Memory
- **Auto-ajout du space au token à la création** — Quand un client restreint (`space_ids: ["A"]`) crée un space "B", le space B est automatiquement ajouté à ses `space_ids` dans `tokens.json`. Élimine le deadlock UX où le client ne pouvait pas accéder au space qu'il venait de créer. Nouvelle méthode `TokenService.add_space_to_token()`.
- **Filtrage `backup_list` par space_ids du token** — Un client ne voit plus que les backups des spaces auxquels il a accès. Corrige une fuite d'information où un client pouvait lister tous les backups de tous les espaces.
- **Confirmation `backup_download` sécurisé** — Vérifié que `check_access(space_id)` est déjà en place (extrait le space_id du backup_id). Aucune modification nécessaire.
- **Script de recette unifié** — `scripts/test_recette.py` refait avec 4 suites sélectionnables par CLI (`--suite recette,isolation,qualite,graph`). Suite `isolation` : ~20 tests vérifiant l'isolation multi-tenant (accès inter-espaces refusé, filtrage backup_list, écriture read-only refusée, auto-ajout space au token).
- **Champ `email` dans les tokens** — Alignement Graph Memory : `admin_create_token(email=)` optionnel pour la traçabilité. Affiché dans `token list` (colonnes : Nom, Email, Hash, Permissions, Espaces, Créé le, Expire). CLI : `--email/-e`, Shell : `--email`.
- **CLI complète (32/32 outils)** — Ajouté : `space summary`, `space export`, `backup download`, `gc` en Click et Shell interactif.
- **WAF rate limits ×3** — MCP 200→600 req/min, API 60→120, Global 500→1500 (résout les TaskGroup errors).
- **Nettoyage scripts/** — 5 scripts supprimés (test_qualite, test_multi_agents, test_gc, test_graph_bridge, test_markdown_engine), tout intégré dans `test_recette.py`.

---

## [0.6.0] — 2026-03-11

### Changé — Consolidation chirurgicale (édition par section Markdown)
- **Refonte majeure du consolidateur LLM** — Passage du mode "réécriture complète" au mode "édition chirurgicale". Le LLM produit désormais des **opérations d'édition par section Markdown** (`replace_section`, `append_to_section`, `prepend_to_section`, `add_section`, `delete_section`) au lieu de réécrire les fichiers entiers.
- **Zéro perte de matière** — Ce qui n'est pas touché explicitement reste intact byte-for-byte. Test A/B validé : l'ancien mode perdait 28 lignes, le nouveau mode n'en perd aucune (hors `replace_section` attendu sur le focus).
- **Moteur d'édition Markdown** — Nouveau moteur dans `consolidator.py` : `_parse_sections()`, `_find_section_index()` (matching flexible 3 niveaux : exact → sans # → case-insensitive), `_reconstruct_from_sections()`, `_apply_operation()`.
- **Prompts LLM mis à jour** — Le prompt système et utilisateur demandent des opérations d'édition au format JSON structuré, avec 3 actions par fichier : `edit` (opérations chirurgicales), `create` (nouveau fichier), `rewrite` (fallback justifié).
- **Rétrocompatibilité** — Si le LLM retourne l'ancien format `bank_files`, conversion automatique via `_convert_legacy_format()`.

### Ajouté
- **Métriques de consolidation enrichies** — `operations_applied` et `operations_failed` dans le retour de `bank_consolidate` et dans le front-matter de `_synthesis.md`.
- **77 tests unitaires** — `scripts/test_markdown_engine.py` couvre le moteur d'édition : parsing, reconstruction, idempotence, toutes les opérations, cas limites, scénarios réalistes.
- **Test E2E consolidation chirurgicale** — `test_surgical_consolidation.py` : 7 phases (création, consolidation create, snapshot, notes supplémentaires, consolidation chirurgicale, comparaison avant/après, nettoyage).
- **Test A/B** — `run_ab_test.py` : compare production (ancien mode) vs local (nouveau mode) sur les mêmes données.

### Gains mesurés (test A/B)
| Métrique                     | Ancien mode (réécriture) | Nouveau mode (chirurgical)      |
| ---------------------------- | ------------------------ | ------------------------------- |
| Lignes perdues (progress.md) | 10                       | **0**                           |
| Lignes perdues (total)       | 28                       | **1** (replace_section attendu) |
| Tokens completion LLM        | 4850                     | **3993** (-18%)                 |
| Durée consolidation          | 29s                      | **14.4s** (-50%)                |

### Fichiers modifiés
| Fichier                                | Changements                                                    |
| -------------------------------------- | -------------------------------------------------------------- |
| `src/live_mem/core/consolidator.py`    | Moteur d'édition Markdown + prompts chirurgicaux + rétrocompat |
| `DESIGN/live-mem/CONSOLIDATION_LLM.md` | Design doc v0.6.0 complet                                      |
| `scripts/test_markdown_engine.py`      | 77 tests unitaires (nouveau)                                   |

---

## [0.5.3] — 2026-03-09

### Corrigé — Validation des permissions tokens
- **Bug "permissions all"** — Le système acceptait n'importe quel texte comme permission (ex: `"all"`), mais `check_write_permission()` et `check_admin_permission()` ne reconnaissaient que `"read"`, `"write"` et `"admin"` individuellement. Un token créé avec `permissions="all"` était donc inutilisable pour les opérations write/admin.
- **Validation côté serveur** — `VALID_PERMISSIONS = {"read", "write", "admin"}` défini dans `core/tokens.py`. Les méthodes `create_token()` et `update_token()` rejettent désormais les permissions invalides avec un message explicite.
- **Validation côté CLI** — `token create` utilise `click.Choice(["read", "read,write", "read,write,admin"])` : plus de texte libre, Click rejette immédiatement les valeurs invalides.
- **Validation côté shell** — Le shell interactif valide aussi les permissions avant l'appel MCP.

### Ajouté — Commande `token update`
- **CLI Click** : `token update <hash> --permissions read,write --space-ids "p1,p2"` — permissions contraintes par `click.Choice`
- **Shell interactif** : `token update sha256:a8c5 --permissions read,write` avec parsing des flags `-p`/`-s`
- **Autocomplétion** enrichie dans le shell : `--permissions`, `--space-ids`, `read`, `read,write`, `read,write,admin`

### Fichiers modifiés
| Fichier                       | Changements                                                                                 |
| ----------------------------- | ------------------------------------------------------------------------------------------- |
| `scripts/cli/commands.py`     | `VALID_PERMISSIONS` (click.Choice), `token_create_cmd` contraint, `token_update_cmd` ajouté |
| `scripts/cli/shell.py`        | `_VALID_PERMS`, `_validate_permissions()`, handler `token update`, autocomplétion étendue   |
| `src/live_mem/core/tokens.py` | `VALID_PERMISSIONS`, validation dans `create_token()` et `update_token()`                   |

---

## [0.5.2] — 2026-03-09

### Ajouté — Suppression physique des tokens
- **`admin_delete_token`** 👑 — Supprime physiquement un token du registre `tokens.json` sur S3
- **`admin_purge_tokens`** 👑 — Purge en masse : tokens révoqués seuls (`revoked_only=True`) ou tous (`revoked_only=False`)
- **32 outils MCP** (était 30) — 7 catégories (admin passe de 5 à 7 outils)
- **Script `scripts/delete_tokens.py`** — Utilitaire CLI pour lister, révoquer et purger les tokens à distance
  - `list` : liste les tokens
  - `revoke_all` : révoque tous les tokens actifs
  - `purge` : supprime physiquement les tokens révoqués
  - `purge_all` : supprime physiquement TOUS les tokens

### Notes
- Le **bootstrap key** (variable d'environnement `ADMIN_BOOTSTRAP_KEY`) n'est jamais stocké dans `tokens.json` et ne peut pas être supprimé
- Les 2 nouveaux outils utilisent le pattern `Annotated[type, Field(description="...")]` pour les descriptions Cline
- Méthodes `delete_token()` et `purge_tokens()` ajoutées dans `TokenService` (`core/tokens.py`)
