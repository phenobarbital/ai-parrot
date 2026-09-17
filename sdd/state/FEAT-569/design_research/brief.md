<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
Today `wikitoolkit` is consumed **locally**: the CLI opens a plane on disk
(SQLite under `.parrot/wiki/`) or connects **directly** to ArangoDB when
`backend: arangodb` is resolved (base `wiki.json` or a per-env overlay,
FEAT-461), and `wikitoolkit mcp` exposes the same plane to Claude Code /
Codex as a **stdio** MCP server (FEAT-403). Every team member — and every
coding agent — that wants the shared plane therefore needs network reach
to ArangoDB plus its credentials (`ARANGODB_*` via navconfig). That is the
pain point: sharing the graph means **exposing the database** (VPN, per-user
DB credentials, driver/analyzer version drift on every laptop).

We want a **remote wikitoolkit MCP server** that owns the ArangoDB
connection (and the SDD work ledger, FEAT-566) and that clients reach over
HTTPS with a bearer token. Three concrete actions are in scope:

1. **Expose wikitoolkit as an HTTP MCP** — a `wikitoolkit serve` process
   speaking MCP Streamable HTTP, serving one or more wikis, connected to
   ArangoDB behind it.
2. **`wikitoolkit` CLI (and the stdio `wikitoolkit mcp`) act as a proxy**
   to that remote server when the repo is configured for it — same
   commands, same output, no local DB credentials.
3. **Install wikitoolkit as a remote HTTP MCP** in Claude Code and Codex
   via the existing installers (`parrot claude install`, `parrot codex
   install`), so agents call the shared graph natively.

**Affected users**: developers running Claude Code / Codex against shared
wikis (parrot, fieldsync, issues), ops (one deployable instead of N DB
clients), and the SDD dev-loop agents that write to the ledger.

### Constraints and goals
Decisions taken in discovery (Rounds 0–2) are binding for the spec:

- **Flow**: `type: feature`, `base_branch: dev`.
- **Topology**: **standalone `wikitoolkit serve`** process (aiohttp), small
  container deployed next to ArangoDB. Not mounted in the ai-parrot server
  app (may be added later; must not be required).
- **Auth**: **static bearer token from an env var** on the server
  (`WIKITOOLKIT_SERVER_TOKEN`) and on clients (`WIKITOOLKIT_TOKEN`).
  OAuth2 explicitly out of scope for v1.
- **Build path**: `build` / `upsert` / `ingest` **stay local** (they need
  the repo's AST/tree-sitter scan); the resulting pages / edges / symbols
  are **pushed to the server through MCP** (bulk ingest tools), never by a
  client-side ArangoDB connection.
- **Tenancy**: **multi-wiki by path** — `/mcp/<wiki_name>`; clients
  register one MCP server per wiki they use.
- **Attribution**: writes carry the caller identity in an
  **`X-Wiki-Actor` header** (`human:<local-user>` — same identity scheme
  `sync` already uses), trusted from the client. Hosts that cannot send
  custom headers (Codex's native HTTP client) fall back to a server-side
  default actor — see Open Questions.
- **Mode switch**: a `remote` block in `.parrot/wiki.json` (overlayable per
  env like FEAT-461) plus a `WIKITOOLKIT_REMOTE_URL` env override;
  **fail-closed** — if the remote is unreachable the command errors, no
  silent fallback to the local SQLite plane.
- Transport is **MCP Streamable HTTP (2025-03-26)** — the revision both
  Claude Code (`"type": "http"`) and Codex (`url = ...`) consume; legacy
  SSE not required.
- Use **ai-parrot's own MCP stack** (`parrot.mcp.*`), not the `mcp` PyPI
  SDK — the SDK stays where it is today (optional extras + one interop
  test used as an independent client).
- Async-first, aiohttp only, Pydantic models, Google docstrings; no new
  runtime dependency for clients (core already ships aiohttp).
- Existing stdio installs (`.mcp.json` → `wikitoolkit mcp`) must keep
  working unchanged; MCP tool **names** (`wiki_query`, `ledger_open`, …)
  must not change so `.claude/settings.local.json` approvals stay valid.
- **Ledger backend v1**: SQLite on the server host; ArangoDB port is a
  follow-up feature, not a blocker.
- **CLI-only commands** (`link`, `memories`, `audit`, `ground`, `export`,
  `communities`, non-tool `ledger` subcommands) are **out of scope**: they
  are refused in remote mode until a separate spec exposes them as MCP
  tools.
- The server host has **no git checkout** of the wikis it serves: anything
  that today derives from `find_project_root()` / `find_shared_root()`
  (ledger location, build) needs an explicit server-side configuration.

---

### Recommended option / probable scope
**Option A** is recommended because:

- It delivers all three requested actions with a **single protocol and a
  single server surface** (`/mcp/<wiki>` speaking Streamable HTTP), reusing
  `StreamableHttpMCPServer` and the tool assembly that already exists for
  stdio. Option B's transparency is attractive, but it doubles the wire
  surface, exposes the store contract as a remote API and still needs a
  tool-level path for the ledger; Option C was ruled out in discovery;
  Option D does not satisfy the "CLI as proxy" requirement and cannot host
  the ledger.
- What we trade off: explicit command→tool mapping and a bulk-ingest
  protocol. Both are bounded and testable against a fake server, and the
  bulk tools double as the future home of `sync push/pull` (so the current
  client-side ArangoDB path in `sync._open_remote` can be retired).
- What we accept for v1 (decided 2026-09-17): the ledger remains a SQLite
  file **on the server host** (centralised, unexposed), not an ArangoDB
  collection — the port is the follow-up feature `wikitoolkit-ledger-arangodb`.
  CLI-only commands without an MCP tool are refused in remote mode; their
  tools arrive through a separate spec. The stdio pass-through is the
  intermediate install path, so the installer lane is optional polish
  rather than a prerequisite.

---

The remote server publishes exactly the tool set `wikitoolkit mcp` already
builds (`create_wiki_tools` + `create_structural_tools` + ledger tools) over
Streamable HTTP, once per wiki at `/mcp/<wiki_name>`. The CLI in remote
mode maps each command onto the matching MCP tool (`query` →
`wiki_query`, `remember` → `wiki_remember`, `symbols blast` →
`wiki_blast_radius`, `ledger claim` → `ledger_claim`, …) through a small
core-side Streamable HTTP JSON-RPC client, and renders the tool result with
the renderers it already has. `wikitoolkit mcp` (stdio) becomes a
pass-through when `remote` is configured: `tools/list` and `tools/call`
are forwarded verbatim, so hosts without HTTP-MCP support (and existing
`.mcp.json` entries) keep working. Local build results reach the server via
**two new bulk tools** — `wiki_ingest_batch` (source slices: pages + edges
+ symbols, chunked, delta by `page_hashes`) and `wiki_sync_push` /
`wiki_sync_pull` (authored knowledge, LWW — the `sync.py` engine run
server-side). CLI-only commands with no tool today (`link`, `memories`,
`audit`, `ground`, `export`, `communities`, `ledger acknowledge|blockers|
audit|export`) either gain a tool or return "not available in remote
mode" (see Open Questions).

✅ **Pros:**
- One wire protocol (MCP) and one auth path for agents and the CLI; the
  server has nothing to expose besides `/mcp/<wiki>`.
- Maximal reuse: the tool assembly in `create_wiki_mcp_server()` is
  refactored into a shared builder used by both stdio and HTTP; the
  Streamable HTTP server, session handling, origin checks and principal
  binding already exist (`StreamableHttpMCPServer`).
- Remote-mode CLI output is guaranteed identical to what agents see —
  easy to reason about, easy to test with a fake server.
- Keeps SQLite-specific behaviour (writer lock, checkpoints, pragmas) fully
  server-side; the client never learns about the backend.

❌ **Cons:**
- Command → tool mapping is explicit code per command (≈20 commands),
  and a handful of CLI-only commands need new tools or a scoped error.
- Bulk ingest over `tools/call` is heavier than a direct store write:
  needs chunking, payload caps and a delta protocol (`page_hashes`).
- Ledger stays **SQLite on the server's disk** (`LedgerStore` is a
  `SQLiteWikiStore` subclass); it is centralised and hidden, but not "in
  ArangoDB".

📊 **Effort:** Medium–High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` (already a core dep) | server app + client JSON-RPC calls | client parses `application/json` **or** SSE-wrapped responses |
| `ai-parrot-server` (workspace dist) | `StreamableHttpMCPServer`, `MCPServerConfig` | **server host only**, lazily imported by `wikitoolkit serve`; clear error if missing |
| `pydantic>=2` | `WikiRemoteConfig`, server config model | existing |
| `click` | `wikitoolkit serve`, `--remote` flags | existing |
| `mcp>=1.28.1,<2` (optional extra) | official client in an interop test only | precedent: `packages/ai-parrot-server/tests/mcp/test_streamable_http_interop.py` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` — `create_wiki_mcp_server()` tool assembly (store → federation → ledger overlay → tools); split into `build_wiki_tools()` + transport wrapper.
- `packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py` — `StreamableHttpMCPServer` (sessions, SSE buffers, `_principal`, origin checks).
- `packages/ai-parrot-server/src/parrot/mcp/transports/http.py` — `HttpMCPServer` standalone/parent-app mounting; `HttpMCPSession._read_sse_response` as reference for the core client.
- `packages/ai-parrot-server/src/parrot/mcp/parrot_server.py` — `_check_base_path_conflicts` precedent for mounting several MCP servers on one app.
- `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py` — `_sync_records` LWW core, `SyncReport`, `default_local_identity()`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` — `BaseWikiStore.replace_source_slice`, `upsert_symbols`, `page_hashes` for delta ingest.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` — `WikiProjectConfig` + `WikiEnvOverlay` + `load_effective_config` for the `remote` block.
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`, `codex/installer.py`, `claude_code/assets.py`, `codex/assets.py` — the managed `.mcp.json` / `.codex/config.toml` entries.

---

### Verified code anchors (paths only — open them yourself)
.mcp.json
.parrot/wiki.json
packages/ai-parrot-server/src/parrot/mcp/config.py
packages/ai-parrot-server/src/parrot/mcp/parrot_server.py
packages/ai-parrot-server/src/parrot/mcp/transports/http.py
packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py
packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py
packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
packages/ai-parrot/src/parrot/knowledge/wiki/coding_agents.py
packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py
packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
packages/ai-parrot/src/parrot/knowledge/wiki/project.py
packages/ai-parrot/src/parrot/knowledge/wiki/store.py
packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py
packages/ai-parrot/src/parrot/knowledge/wiki/sync.py
packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
packages/ai-parrot/src/parrot/mcp/adapter.py
packages/ai-parrot/src/parrot/mcp/integration.py
packages/ai-parrot/src/parrot/mcp/local_cli.py
packages/ai-parrot/src/parrot/mcp/local_server.py
packages/ai-parrot/src/parrot/mcp/server_base.py

### Questions still open in the exploration document
- [ ] **Server packaging**: make `ai-parrot-server` an optional extra of core (`ai-parrot[wikitoolkit-server]`) or move a dependency-light Streamable HTTP server into core? (Affects who can `pip install` the server image.) — *Owner: Jesus / spec*
- [ ] **Token gate implementation**: aiohttp middleware in `wikitoolkit serve` vs. `AuthMethod.API_KEY` with a one-token `api_key_store` (locate the `APIKeyStore` class first) — *Owner: spec*
- [ ] **Bulk-ingest limits**: max payload per `wiki_ingest_batch` call, slices per call, and whether embeddings (`upsert_embedding`) are pushed or recomputed server-side — *Owner: spec*
- [ ] **Federation in remote mode**: should `ns list` show the server's namespaces (read-only) so users understand what a remote `--ns` targets? — *Owner: Jesus*
- [ ] **Default actor when `X-Wiki-Actor` is absent** (only native-HTTP callers without header support, e.g. Codex registered directly, or curl): proposed default `agent:unknown` for writes, reads unaffected. Low priority now that the stdio pass-through is the recommended Codex path. — *Owner: spec*
- [ ] **TLS termination**: `wikitoolkit serve` speaks plain HTTP behind a reverse proxy, or supports `ssl_cert_path`/`ssl_key_path` from `MCPServerConfig` directly? — *Owner: ops*

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
