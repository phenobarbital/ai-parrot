---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: wikitoolkit as a remote (Streamable HTTP) MCP — server, CLI proxy, and coding-agent install

**Date**: 2026-09-17
**Author**: Jesus Lara (with Claude)
**Status**: accepted
**Recommended Option**: A

---

## Problem Statement

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

## Constraints & Requirements

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

## Options Explored

### Option A: Tool-level proxy — one MCP tool surface for agents *and* the CLI

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

### Option B: `RemoteWikiStore` — a `BaseWikiStore` backend over HTTP

Register a fourth backend (`backend: "remote"`) via `register_wiki_backend`.
The server exposes a **store RPC** (one endpoint or one private MCP tool
per `BaseWikiStore` method: `upsert_pages`, `add_edges`,
`replace_source_slice`, `search_fts`, `neighbors`, `get_page`,
`list_pages`, `stats`, `find_symbols`, …). `RemoteWikiStore` implements
the contract by calling them. Because `_open_store()` returns a
`BaseWikiStore`, **every** CLI command — including `build`, `upsert`,
`ingest`, `sync`, `export`, `communities` — works unchanged, and a new
`WikiNamespaceConfig` kind `url:` would federate remote wikis
client-side.

✅ **Pros:**
- Zero per-command proxy code; `build` writes straight through the store.
- Federation, `--ns`, `ns add url:` come for free through
  `FederatedWikiStore`.
- Cleanest conceptual model: "the plane is just somewhere else".

❌ **Cons:**
- A **second wire protocol** (store RPC) next to the MCP tool surface, each
  with its own auth, versioning and payload rules; ~25 methods to mirror,
  some unbounded (`dump_pages`, `dump_edges`) or SQLite-shaped
  (`_assert_writable`, checkpoints, `wiki_write_lock`).
- Very chatty during `build` (one round-trip per slice, thousands of
  slices) unless a batching layer is added anyway.
- The ledger does **not** go through `BaseWikiStore` (`LedgerStore` adds
  `ledger_transaction`, `read_cursor`), so ledger commands still need a
  tool-level proxy — two mechanisms in one CLI.
- Exposes the store contract as a remote API: any store refactor becomes a
  protocol change.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | store RPC transport (JSON) | existing |
| `pydantic>=2` | per-method request/response models | ~25 pairs |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` — `BaseWikiStore` contract, `register_wiki_backend`, `create_wiki_store` dispatch.
- `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` — `open_namespace_store`, `_open_arango` probe-under-timeout pattern.
- `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` — `ArangoDBWikiStore` as the model of a network-backed store.

---

### Option C: Server-side build from git — clients are read-only

The server clones/fetches each wiki's repository (webhook or cron) and runs
`build` / `upsert` itself against ArangoDB; clients only query and author
(memories, notes, ledger). No bulk ingest protocol at all.

✅ **Pros:**
- Simplest client; no delta/chunking protocol.
- One authoritative build per commit — no laptop-to-laptop drift.

❌ **Cons:**
- The server needs git credentials and a working tree for every wiki, plus
  the full scanner dependency set (tree-sitter, ast-grep, Roblox/Perl
  plugins…); the "small container next to ArangoDB" grows into a CI box.
- Worktree/branch semantics get complicated: which branch's build does a
  developer on a feature branch query?
- Rejected in discovery (Round 2) in favour of local build + push.

📊 **Effort:** Medium (code) / High (ops)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `gitpython` or plain `git` subprocess | fetch per wiki | new dependency or shell-out |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — `build`, `_changed_files_from_git`, `upsert`.

---

### Option D (unconventional): Sync-only — no live proxy, two MCP servers per repo

Keep every plane local (SQLite). A git `post-commit` / `post-merge` hook
(the installer already manages one) runs `wikitoolkit sync push` — over MCP
to the remote plane — and agents register **both** the local stdio
`wikitoolkit mcp` (repo plane, fresh) and the remote HTTP server (shared
plane, eventually consistent). The CLI never proxies; `sync` is the only
remote-aware command.

✅ **Pros:**
- Lowest effort: one server (read + sync tools) and one client
  (`sync`), nothing else changes.
- Local queries stay fast and work offline.

❌ **Cons:**
- Two sources of truth and two `wiki_query` tools with near-identical
  descriptions — agents pick the wrong one.
- The ledger cannot be eventually consistent (claims must be atomic), so
  ledger commands still need a live proxy — which brings back Option A's
  machinery for the hardest part.
- Does not deliver requirement 2 (CLI as proxy).

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiohttp` | sync transport | existing |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/sync.py`, `claude_code/installer.py::_install_git_hook`.

---

## Recommendation

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

## Feature Description

### User-Facing Behavior

**Server (ops)**

```bash
# one process, N wikis, ArangoDB + ledger behind it
WIKITOOLKIT_SERVER_TOKEN=... ARANGODB_HOST=... \
wikitoolkit serve --config /etc/wikitoolkit/server.yaml --host 0.0.0.0 --port 8765
```

`server.yaml` lists wikis by name; each entry points to a directory holding
a `.parrot/wiki.json` with `backend: arangodb` (so `load_effective_config`
is reused as-is) plus an explicit `ledger_dir`. The server mounts
`/mcp/parrot`, `/mcp/fieldsync`, … on one aiohttp app, each with `/info`.
Requests without `Authorization: Bearer <token>` get `401`; a wrong wiki
name gets `404`. Origin validation and session TTLs behave as they do today
for `StreamableHttpMCPServer`.

**Client repo configuration**

```jsonc
// .parrot/wiki.json (or .parrot/wiki.dev.json overlay)
"remote": { "url": "https://wiki.example.com/mcp/parrot",
            "token_env": "WIKITOOLKIT_TOKEN", "timeout": 30 }
```

`WIKITOOLKIT_REMOTE_URL` overrides the URL for one shell. When `remote` is
set, `wikitoolkit status` prints `mode: remote (<url>)`, and:

- `query`, `page`, `related`, `status`, `remember`, `note`, `symbols
  lookup|outline|blast`, `ledger open|ready|claim|close|context` run
  against the server and render exactly as today.
- `build`, `upsert`, `ingest` still scan the repo locally into
  `.parrot/wiki/`, then push the changed slices (delta by page hash) and
  print a push summary; `--no-push` keeps the run local.
- `sync push|pull` move authored knowledge through the server (no
  `ARANGODB_*` needed on the laptop).
- `ns add|list|remove`, `communities`, `export`, `--store`, `--backend`
  are refused with a clear "not available in remote mode; federation is
  configured on the server" message (v1).
- If the server is unreachable / rejects the token, every command fails
  with one typed error naming the URL and the HTTP status — never a silent
  fallback to the local plane.
- `wikitoolkit mcp` (stdio) detects `remote` and forwards `tools/list` /
  `tools/call` to the server, so an unchanged `.mcp.json` keeps working.

**Coding-agent install**

Two paths, both valid in v1:

- **Pass-through (default, zero migration).** Nothing to reinstall: the
  existing stdio entries keep launching `wikitoolkit mcp`, which forwards
  every `tools/list` / `tools/call` to the remote server when `remote` is
  configured, adding `X-Wiki-Actor`. Recommended for Codex (no custom
  headers in its native HTTP client) and for any repo already installed.
- **Native HTTP registration (optional, Claude Code).**

```bash
parrot claude install --remote            # reads remote.url from wiki.json
parrot codex  install --remote            # url + bearer_token_env_var; no actor header
```

writes an HTTP entry (`"type": "http"`, `url`, `Authorization` header from
`${WIKITOOLKIT_TOKEN}`) under the **same** server key `wikitoolkit`, so
the `mcp__wikitoolkit__*` approvals already written to
`.claude/settings.local.json` stay valid; Codex gets
`[mcp_servers.wikitoolkit] url = ... bearer_token_env_var = ...`.
`integration_status` reports `transport: http|stdio`. Uninstall removes the
entry either way.

### Internal Behavior

1. **Tool assembly split.** `create_wiki_mcp_server(root)` is refactored
   into `build_wiki_tools(root, config, *, ledger_dir=None) ->
   list[AbstractTool]` (store → namespaces → ledger overlay → wiki +
   structural + vault tools) and two thin wrappers: the existing
   `StdioMCPServer` one and a new `WikiHttpMCPServer` that wraps
   `StreamableHttpMCPServer` with `MCPServerConfig(transport=
   "streamable-http", base_path=f"/mcp/{wiki}", …)`, all mounted on one
   parent `web.Application`.
2. **Static bearer auth.** A tiny aiohttp middleware on the parent app
   compares `Authorization: Bearer` against the env token (constant-time)
   and attaches `request["mcp_user"] = {"user_id": <X-Wiki-Actor or
   "anonymous">}` so `StreamableHttpMCPServer._principal()` binds sessions
   to the acting identity. `MCPServerConfig.auth_method` stays `NONE` at
   the transport level (the middleware is the gate) — or an
   `AuthMethod.API_KEY` store with one token, whichever the spec finds
   cleaner.
3. **Actor propagation.** The middleware sets a `ContextVar` (`wiki_actor`)
   from `X-Wiki-Actor`; the identity resolution used by `wiki_remember`,
   `wiki_note`, `wiki_sync_push` and the ledger tools reads it before
   falling back to `default_local_identity()`. Ledger tools already take an
   explicit `actor` argument; the CLI proxy fills it from the same value.
4. **Core client.** `parrot.knowledge.wiki.remote.RemoteWikiClient`
   (aiohttp, core only): `initialize` → keep `Mcp-Session-Id` → `tools/call`;
   sends `Accept: application/json, text/event-stream` and decodes either a
   JSON body or the first `message` event of an SSE body; raises
   `RemoteWikiError(url, status, message)`; sends `X-Wiki-Actor`. Reused by
   the CLI proxy, the stdio pass-through and `sync`.
5. **CLI mode switch.** `_resolve_project_effective()` yields
   `config.remote`; a `_remote_or_none(root, config)` helper returns a
   client when configured (env override applied). Each proxied command
   branches once at the top: remote → call tool → render; else today's
   path. Commands not supported remotely raise a `click.UsageError`.
6. **Bulk ingest.** `wiki_ingest_batch` accepts a list of source slices
   (`rel_path`, pages, edges, symbols) and applies
   `replace_source_slice` + `upsert_symbols` under the server's write lock;
   `wiki_page_hashes` returns hashes for a list of ids so the client sends
   only changed slices. Payload capped (e.g. 1 MiB / 200 slices per call).
   `build`/`upsert`/`ingest` in remote mode: local build → diff hashes →
   chunked pushes → summary. `wiki_sync_push`/`wiki_sync_pull` wrap
   `sync._sync_records` with the remote plane being the server's own store.
7. **Installers.** `claude_code/assets.mcp_json_entry(root)` gains a remote
   variant; `_install_mcp_json` / `codex/_install_mcp` pick it when
   `--remote` (or `remote` present in config); `_is_managed_toolkit_entry`
   learns the HTTP shape so uninstall recognises it.

### Edge Cases & Error Handling

- **Remote configured but token env unset** → fail before any request:
  "`WIKITOOLKIT_TOKEN` is not set (remote mode)".
- **401 / 403** → typed error, exit code 2, hint to check the token; **404**
  on `/mcp/<wiki>` → "wiki `<name>` not served by <host>".
- **Timeouts** → per-call timeout from `remote.timeout`; bulk pushes retry a
  chunk once, then abort and print which slices were not pushed
  (`--resume` re-runs only those, based on hashes).
- **Session expiry (`Mcp-Session-Id` unknown)** → the client re-initialises
  once transparently.
- **Local plane absent in remote mode** → read commands do **not** require
  `is_built()`; build commands still create `.parrot/wiki/` locally.
- **Both `remote` and `--backend/--store`** → usage error (mutually
  exclusive).
- **Server: wiki dir without `.parrot/wiki.json` or backend ≠ arangodb** →
  refuse to start (fail-fast config validation); **ArangoDB unreachable at
  startup** → start anyway but `/info` reports `plane: unavailable` and
  tools return a typed error (so a DB restart does not require a server
  restart).
- **Ledger on server** → `LedgerService.from_root` requires a git-backed
  shared root; the server passes an explicit `ledger_dir` instead.
  `ledger acknowledge` remains human-only (actor prefix check) and is not
  exposed as a tool in v1.
- **Concurrent bulk pushes for the same wiki** → server serialises under
  the existing writer lock; `WikiStoreBusy` surfaces as a retryable error
  code.
- **Stdio pass-through**: if the remote fails mid-session the stdio server
  returns JSON-RPC errors (never exits), matching today's behaviour.

---

## Capabilities

### New Capabilities
- `wikitoolkit-http-server`: `wikitoolkit serve` — multi-wiki Streamable
  HTTP MCP server with static bearer auth, actor header, per-wiki mounts.
- `wikitoolkit-remote-client`: core aiohttp Streamable HTTP JSON-RPC client
  + `remote` config block + env override + typed errors.
- `wikitoolkit-cli-remote-proxy`: command→tool proxy for read, authoring,
  symbol and ledger commands; stdio `wikitoolkit mcp` pass-through.
- `wikitoolkit-bulk-ingest-tools`: `wiki_ingest_batch`, `wiki_page_hashes`,
  `wiki_sync_push`, `wiki_sync_pull` server tools + delta push in
  `build`/`upsert`/`ingest`/`sync`.
- `coding-agent-remote-mcp-install`: `--remote` for `parrot claude install`
  and `parrot codex install` (HTTP entry, same server key).

### Follow-up features (out of scope, referenced by this spec)
- `wikitoolkit-ledger-arangodb`: port `LedgerStore` (today a
  `SQLiteWikiStore` subclass with `ledger_transaction` / `read_cursor`)
  to an ArangoDB-backed store so the ledger lives in the same database as
  the wiki plane. Needs its own brainstorm/spec; this feature only keeps
  `LedgerService` construction backend-agnostic.
- Exposing the CLI-only commands (`link`, `memories`, `audit`, `ground`,
  `export`, `communities`, non-tool `ledger` subcommands) as MCP tools —
  separate spec owned by the user; the remote proxy adopts them
  automatically.

### Modified Capabilities
- `mcp-local-server-wikitoolkit` (FEAT-403): tool assembly extracted into a
  transport-agnostic builder; stdio server gains pass-through mode
  (**the v1 intermediate install path** — no installer change required).
- `wikitoolkit-env-support` (FEAT-461): `remote` joins the overlayable
  fields; `sync push/pull` gain an MCP path.
- `claude-install-mcp-autoenable` (FEAT-556): managed `.mcp.json` entry
  detection extended to the HTTP shape.
- `sdd-work-ledger` (FEAT-566): `LedgerService` constructible with an
  explicit ledger dir (no git root) for the server.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/mcp_server.py` | modifies | split `create_wiki_mcp_server` into builder + stdio wrapper; add pass-through |
| `parrot/knowledge/wiki/cli.py` | extends | `serve` command; remote branch in ~20 commands; refusals for unsupported ones |
| `parrot/knowledge/wiki/project.py` | extends | `WikiRemoteConfig`; `remote` on `WikiProjectConfig` + `WikiEnvOverlay` |
| `parrot/knowledge/wiki/remote.py` (new) | new | core Streamable HTTP client, errors, actor header |
| `parrot/knowledge/wiki/tools.py` | extends | `wiki_ingest_batch`, `wiki_page_hashes`, `wiki_sync_push/pull`; actor ContextVar in identity resolution |
| `parrot/knowledge/wiki/sync.py` | modifies | `_sync_records` reusable server-side; client path via MCP |
| `parrot/knowledge/wiki/ledger/service.py` | extends | explicit `ledger_dir` constructor path |
| `parrot/knowledge/wiki/claude_code/{assets,installer}.py` | extends | HTTP entry variant, `--remote`, managed-entry detection, status |
| `parrot/knowledge/wiki/codex/{assets,installer}.py` | extends | `url` + `bearer_token_env_var` table variant |
| `parrot/mcp/transports/streamable_http.py` (ai-parrot-server) | depends on | consumed as-is; only if a hook is missing would it change |
| `packages/ai-parrot/pyproject.toml` | extends | optional extra `wikitoolkit-server = ["ai-parrot-server"]` (or document the requirement) |
| Deployment | new | container image + `server.yaml`; token + `ARANGODB_*` secrets |
| Docs | extends | `docs/wiki/remote-mcp.md`, installer docs, CLAUDE.md wiki section |

No breaking change for local users: without `remote` every path is
byte-identical to today.

---

## Code Context

### User-Provided Code

_None — the user provided requirements in prose only._

Current managed `.mcp.json` entry (repo root, written by `parrot claude
install`):

```json
// Source: /home/jesuslara/proyectos/ai-parrot/.mcp.json (verified 2026-09-17)
"wikitoolkit": {
  "command": "/home/jesuslara/proyectos/ai-parrot/.venv/bin/wikitoolkit",
  "args": ["mcp"],
  "env": {}
}
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
_INVOCATION_CWD = os.getcwd()                                         # L44
def _ensure_stderr_logging() -> None                                   # L47
def _run_sync(coro: Any) -> Any                                        # L70
def create_wiki_mcp_server(root: Path) -> StdioMCPServer               # L94  (lazy-imports parrot.mcp.local_server / server_base)
    # store → resolve_namespaces → LedgerService.from_root (only if find_shared_root) →
    # ledger NamespaceHandle(read_only=True) → FederatedWikiStore → create_wiki_tools →
    # create_structural_tools → optional ObsidianToolkit/VaultIngestTool → StdioMCPServer(LocalServerConfig(name="wikitoolkit"))
def main() -> None                                                     # ~L300 (requires config.is_built(root))

# From packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
def create_wiki_tools(store: BaseWikiStore, root: Path | None = None,
                      config: WikiProjectConfig | None = None,
                      ledger_service: Union["LedgerService", None] = None) -> list[AbstractTool]   # L741-785
class WikiQueryTool(AbstractTool)      # L191   name "wiki_query"
class WikiPageTool(AbstractTool)       # L233   "wiki_page"
class WikiRelatedTool(AbstractTool)    # L270   "wiki_related"
class WikiRememberTool(AbstractTool)   # L302   "wiki_remember"
class WikiNoteTool(AbstractTool)       # L401   "wiki_note"
class WikiStatusTool(AbstractTool)     # L466   "wiki_status"
class VaultIngestTool(AbstractTool)    # L482
class LedgerOpenTool(AbstractTool)     # L626   "ledger_open"
class LedgerReadyTool(AbstractTool)    # L661   "ledger_ready"
class LedgerClaimTool / LedgerCloseTool("ledger_close" L~703) / LedgerContextTool("ledger_context" L~722)

# From packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py
def create_structural_tools(store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> list[AbstractTool]   # L225-263
    # tools: wiki_symbol_lookup, wiki_code_outline, wiki_blast_radius

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py
def register_wiki_backend(...)                                         # L511-522  (satellite backends, FEAT-449)
class BaseWikiStore(ABC):                                              # L525-818
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int   # L544
    async def add_edges(self, edges: list[tuple]) -> int               # L547
    async def replace_source_slice(...)                                # L550
    async def delete_page(self, concept_id: str) -> bool               # L558
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]   # L565
    async def list_pages(...)                                          # L568
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]   # L576
    async def neighbors(...)                                           # L582
    async def dump_pages(self) / dump_edges(self)                      # L590 / L593
    async def stats(self) -> dict[str, Any]                            # L596
    async def upsert_symbols(...)                                      # L687
    async def symbols_for(self, rel_path: str) -> list[SymbolRecord]   # L707
    async def find_symbols(...)                                        # L734
    async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]   # L782
    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]        # L803
class WikiStoreBusy(...)                                               # L264-286
def create_wiki_store(storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs: Any) -> BaseWikiStore   # L2247-2326

# From packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py
class ArangoDBWikiStore(BaseWikiStore)                                 # L135 (__init__ L170: arango_params, database, wiki_name, text_analyzer, read_only)

# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class ClaudeIntegrationConfig(BaseModel)                               # L134-144
class WikiNamespaceConfig(BaseModel)                                   # L181-277  fields: path | store(+backend) | database(+credentials_env) | vault; description, weight, overlay_prefixes
class WikiProjectConfig(BaseModel):                                    # L379-543
    wiki_name: str = "codebase"; storage_dir: str = ".parrot/wiki"
    backend: Literal["sqlite", "memory", "arangodb"] = "sqlite"
    arango_database / arango_credentials_env / arango_text_analyzer; namespaces: dict[str, WikiNamespaceConfig]
    sqlite_busy_timeout: float = 15.0; sqlite_performance_pragmas: bool = False   # FEAT-557
    def ledger_path(self, root: Path) -> Path                          # L507-517  (".parrot/ledger", FEAT-566)
    def storage_path(self, root: Path) -> Path                         # L519
    def is_built(self, root: Path) -> bool                             # L528
def resolve_arango_params(config) -> dict[str, Any]                    # L605-635
def find_project_root(start: Path) -> Path | None                      # L709-729
class WikiConfigError(Exception)                                       # L732
def load_project_config(root) / save_project_config(root, config)      # L736 / L761
class WikiEnvOverlay(BaseModel)                                        # L780-839  (all WikiProjectConfig fields as Optional)
class WikiEffectiveConfig(BaseModel): config; env; overlay_path        # ~L842-859
def resolve_wiki_env(env: str | None = None) -> str                    # ~L861  (explicit > WIKI_ENV > ENV > "local")
def overlay_path(root: Path, env: str) -> Path                         # ~L892  (".parrot/wiki.{env}.json")
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig   # L897-951
# also imported by mcp_server.py (verified import, line not recorded): find_shared_root, resolve_vault_dir, sqlite_policy_from_config (L682)

# From packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
class NamespaceHandle                                                  # L96-128   (name, store, config, storage_dir, read_only)
async def _open_arango(*, arango_params, database, wiki_name, text_analyzer, timeout, read_only) -> BaseWikiStore   # L306-357
def open_namespace_store(...)                                          # L360-436
async def resolve_namespaces(root, config) -> tuple[list[NamespaceHandle], list[NamespaceSkip]]   # L461-532
class FederatedWikiStore(BaseWikiStore)                                # L622-1547

# From packages/ai-parrot/src/parrot/knowledge/wiki/sync.py
class SyncError(Exception)                                             # L50
class SyncReport                                                       # L59-83
def default_local_identity() -> str                                    # L86-88   ("human:<local-user>")
def _open_plane(root: Path, config: WikiProjectConfig) -> BaseWikiStore   # L91-114 (mirrors cli._open_store)
async def _open_remote(root: Path, target_env: str) -> tuple[BaseWikiStore, WikiProjectConfig]   # L117-134 (client-side ArangoDB today)
async def _sync_records(...)                                           # L221-269 (select, filter, LWW-compare, write)
async def sync_push(...) / sync_pull(...)                              # L293-333 / L336-380

# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
class LedgerService:                                                   # L96-384
    @classmethod from_root(cls, root: Path) -> LedgerService           # L114-141 (uses find_shared_root; falls back to root)
    open_issue L166 · ready_work L199 · claim L209 · acknowledge L213 (human-only) · close_issue L235 ·
    get_context L247 · merge_blockers L280 · export_snapshot L325 · compact L353 · audit L357
# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py
class LedgerStore(SQLiteWikiStore)                                     # L24-123  (SQLite-only; ledger_transaction L54, read_cursor L75)

# From packages/ai-parrot/src/parrot/knowledge/wiki/cli.py  (click group `wiki`, L1328; console script main() L4952)
def _resolve_project(path) -> tuple[Path, WikiProjectConfig]           # L350
def _resolve_project_effective(path) -> tuple[Path, WikiEffectiveConfig]   # L375
def _require_built(root, config) -> BaseWikiStore                      # L391
def _open_store(root: Path, config: WikiProjectConfig) -> BaseWikiStore   # L398-433 (arangodb vs local branch)
def _resolve_read_store(...)                                           # L517  (--backend / --store / WIKI_STORE_BACKEND precedence, then _federate)
def _store_options(func)                                               # L588
def _render_results_table(rows, question, show_body)                   # L607
@wiki.command() def mcp() -> None                                      # L1349-1362
build L1401 · upsert L1670 · query L1824 · page L1895 · related L1943 · status L2017
symbols group L2195 (lookup L2208 · outline L2230 · blast L2266) · ns group L2397
ledger group L2638 (open L2650 · ready L2679 · claim L2696 · acknowledge L2715 · close L2730 · context L2747 ·
                    blockers L2759 · export L2775 · sync L2787 · rebuild L2802 · ingest-sdd L2828 · compact L2848 · audit L2860)
communities L2893 · export L2994 · def _authoring_identity(by) -> str L3027 · def _resolve_write_store(...) L3060
remember L3320 · note L3460 · link L3531 · memories L3588 · audit L3618 · ground L3671
sync group L3740 (push L3762 · pull L3805 · obsidian L3869) · ingest L4292 · ingest-jira L4744 · claude-hook (hidden) L4938
def _register_agent_command(name: str) -> None                         # L4966 (registers `wiki codex|claude|gemini|google install|hook`)

# From packages/ai-parrot/src/parrot/knowledge/wiki/coding_agents.py   (stdlib-only; hooks + skill + instruction block — NOT .mcp.json)
_AGENTS = {"codex": ("AGENTS.md", ".codex/hooks.json", ...), "claude": ("CLAUDE.md", ".claude/settings.json", ...), ...}   # L44
def install(agent: str, root: Path = Path.cwd()) -> list[str]          # L123-159
def hook(agent: str, stdin=None, stdout=None) -> int                   # L162-172

# From packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
MCP_JSON_ENTRY: dict = {"command": "wikitoolkit", "args": ["mcp"], "env": {}}   # L71-75
def resolve_wikitoolkit_bin(root: Path) -> str                         # L83
def mcp_json_entry(root: Path) -> dict                                 # L108-116 (absolute bin path)
# From packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _managed_server_names(root) -> list[str]                           # L304 (always includes "wikitoolkit")
def _install_mcp_approval(root) -> str                                 # L340 (settings.local.json approvals)
def _is_managed_toolkit_entry(entry, root, name) -> bool               # L420
def _install_mcp_json(root: Path) -> str                               # L462-551 (reconciles only "wikitoolkit" + "parrot-<name>" keys)
def _uninstall_mcp_json(root) -> tuple[str | None, list[str]]          # L552
def install_claude_integration(...)                                    # L770
def uninstall_claude_integration(root) -> list[str]                    # L855
def integration_status(root) -> dict[str, Any]                         # L985
# From packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py / installer.py
MCP_TABLE = "mcp_servers.wikitoolkit"                                  # assets.py L19
def mcp_block(root: Path, toolkit_block: str = "") -> str              # assets.py L93
def _install_mcp(root: Path) -> str                                    # installer.py L110-168 (marker-delimited managed block in .codex/config.toml)
def install_codex_integration(...)                                     # installer.py L202

# From packages/ai-parrot/src/parrot/mcp/server_base.py (core)
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")   # L17
def negotiate_protocol_version(requested: str | None) -> str           # L28
@dataclass class LocalServerConfig: name="parrot-mcp-local"; version="1.0.0"; description=""; log_level="WARNING"   # L48
class MCPServerBase(ABC): register_tool / register_tools / handle_initialize / handle_tools_list / handle_tools_call; abstract start/stop   # L57
# From packages/ai-parrot/src/parrot/mcp/local_server.py (core)
class LocalMCPServerBase(MCPServerBase)                                # L18
class StdioMCPServer(LocalMCPServerBase): start() reads stdin lines; _handle_request handles initialize / tools/list / tools/call / notifications/initialized   # L36
# From packages/ai-parrot/src/parrot/mcp/adapter.py (core)
class MCPToolAdapter: to_mcp_tool_definition() L27; async execute(arguments) -> dict L59; _toolresult_to_mcp L108   # L8-148
# From packages/ai-parrot/src/parrot/mcp/local_cli.py (core) — `parrot mcp-local <toolkit>` stdio precedent (FEAT-485)
# From packages/ai-parrot/src/parrot/mcp/integration.py (core)
class MCPToolProxy(AbstractTool)                                       # L50
class MCPClient: _detect_transport() -> "stdio"|"http"|"sse"|"unix"|"websocket"|"quic"; connect() L350; call_tool(tool_name, arguments, headers=None) L389   # L321
def create_http_mcp_server(...) L674 · create_api_key_mcp_server(...) L976 · async validate_mcp_http(config) L1848

# From packages/ai-parrot-server/src/parrot/mcp/config.py
class AuthMethod(str, Enum): NONE, API_KEY, OAUTH2_INTERNAL, OAUTH2_EXTERNAL, BEARER (navigator-auth session)   # L9-16
@dataclass class MCPServerConfig:                                      # L131-226
    transport: str = "stdio"  # "stdio"|"http"|"streamable-http"|"sse"|"unix"|"quic"
    host="localhost"; port=8080; auth_method: AuthMethod = AuthMethod.NONE
    api_key_header: str = "X-API-Key"; api_key_store: Optional[Any] = None
    base_path: str = "/mcp"; allowed_origins; allow_any_origin=False
    session_ttl=3600; event_buffer_size=1000; max_sessions=1000; max_streams_per_session=64
    ssl_cert_path / ssl_key_path / http_use_tls
@dataclass class TransportConfig: transport; enabled; host; port; url; name_suffix; socket_path; base_path   # L230-243
# From packages/ai-parrot-server/src/parrot/mcp/transports/http.py
class HttpMCPServer(...): __init__(self, config: MCPServerConfig, parent_app: Optional[web.Application] = None) L25; start() L38-92 (standalone or parent-app mount); _register_routes(router, base_route) L94
class HttpMCPSession: connect L337; _send_request L390; _read_sse_response L473-530; call_tool L580   # client, L203-610
# From packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py
class StreamableHttpMCPServer(HttpMCPServer):                          # L250-1125
    __init__(self, config: MCPServerConfig, parent_app: web.Application | None = None, session_store: SessionStore | None = None)   # L259
    _register_routes(router, base_route) → POST/GET/DELETE base_route + GET base_route/info   # L284
    _handle_info L309 · _principal(request) L325-349 (request["mcp_user"] → user_id/id/sub/username/email; else credential digest) · _credential_digest L351
# From packages/ai-parrot-server/src/parrot/mcp/parrot_server.py
class ParrotMCPServer: _check_base_path_conflicts() L121-147 (several HTTP-like transports on one app need distinct base paths)
```

#### Verified Imports
```python
from parrot.knowledge.wiki.project import (WikiConfigError, find_project_root, find_shared_root,
    load_effective_config, resolve_arango_params, resolve_vault_dir, sqlite_policy_from_config,
    WikiNamespaceConfig)                                   # used by mcp_server.py L22-27 and inline imports
from parrot.knowledge.wiki.store import create_wiki_store  # mcp_server.py L28
from parrot.knowledge.wiki.tools import create_wiki_tools, VaultIngestTool
from parrot.knowledge.wiki.structural import create_structural_tools   # mcp_server.py (re-exported from structural/tools.py)
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle, resolve_namespaces
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.mcp.local_server import StdioMCPServer        # core
from parrot.mcp.server_base import LocalServerConfig, MCPServerBase, SUPPORTED_PROTOCOL_VERSIONS
from parrot.mcp.adapter import MCPToolAdapter
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer   # ai-parrot-server (PEP 420 merge; only when installed)
from parrot.mcp.config import MCPServerConfig, AuthMethod, TransportConfig  # ai-parrot-server
from parrot.knowledge.wiki.claude_code import assets, installer
from parrot.knowledge.wiki.codex import assets, installer
```

#### Key Attributes & Constants
- `wikitoolkit = "parrot.knowledge.wiki.cli:main"` → console script in `packages/ai-parrot/pyproject.toml:200` (**core** distribution).
- `mcp>=1.28.1,<2` appears only in optional extras (`pyproject.toml:408, 462, 497`), never as a base dep — the design must not rely on it at runtime.
- `.parrot/wiki.json` (this repo): `backend: "sqlite"`, `arango_database: "wiki_ai-parrot"`, `arango_credentials_env: "ARANGODB"`, `arango_text_analyzer: "text_en"`, `structural_backend: true`.
- MCP tools currently exposed by `wikitoolkit mcp` (14): `wiki_query`, `wiki_page`, `wiki_related`, `wiki_remember`, `wiki_note`, `wiki_status`, `wiki_symbol_lookup`, `wiki_code_outline`, `wiki_blast_radius`, `ledger_open`, `ledger_ready`, `ledger_claim`, `ledger_close`, `ledger_context` (+ Obsidian tools when a vault is configured).
- Claude approval names are `mcp__wikitoolkit__<tool>` (`claude_code/assets.py` ~L52-63) — tied to the server key `wikitoolkit`.
- In-flight/related features: FEAT-403 (stdio MCP), FEAT-450 (namespaces), FEAT-461 (env overlays + sync), FEAT-485/556 (installers), FEAT-498 (structural tools), FEAT-557 (SQLite policy), FEAT-566 (work ledger) — all **completed** on `dev` as of 2026-09-17.

### Does NOT Exist (Anti-Hallucination)
- ~~`wikitoolkit serve`~~ — no HTTP serving command exists; `wikitoolkit mcp` is stdio-only (`cli.py:1349`).
- ~~`WikiProjectConfig.remote`~~, ~~`WikiRemoteConfig`~~, ~~`WIKITOOLKIT_REMOTE_URL`~~, ~~`WIKITOOLKIT_TOKEN`~~ — none defined anywhere.
- ~~`backend: "remote"`~~ / ~~`RemoteWikiStore`~~ — `backend` is `Literal["sqlite", "memory", "arangodb"]` (`project.py:415`).
- ~~`WikiNamespaceConfig.url`~~ — namespace kinds are `path` / `store` / `database` / `vault` only.
- ~~Streamable-HTTP **client** in core~~ — `MCPClient._detect_transport()` knows `stdio|http|sse|unix|websocket|quic`; the only client session that parses SSE-in-POST (`HttpMCPSession`) lives in **ai-parrot-server** (`transports/http.py:203`). Core has no such client today.
- ~~`StreamableHttpMCPServer` in core~~ — it is in **ai-parrot-server**; core only has `StdioMCPServer`.
- ~~Static-token bearer auth in `MCPServerConfig`~~ — `AuthMethod.BEARER` means navigator-auth **session** auth; `AuthMethod.API_KEY` expects an `api_key_store` object (referred to as `APIKeyStore` in a comment; its module was not located in this brainstorm — verify in spec).
- ~~`X-Wiki-Actor` header / actor ContextVar~~ — identity today comes from `default_local_identity()` (`sync.py:86`) and `_authoring_identity()` (`cli.py:3027`) on the **local** host.
- ~~MCP tools `wiki_link`, `wiki_memories`, `wiki_audit`, `wiki_ground`, `wiki_export`, `wiki_communities`, `wiki_ingest_batch`, `wiki_page_hashes`, `wiki_sync_push`, `wiki_sync_pull`~~ — `link`, `memories`, `audit`, `ground`, `export`, `communities`, `sync`, `build`, `upsert`, `ingest` are CLI-only today.
- ~~MCP tools `ledger_acknowledge`, `ledger_blockers`, `ledger_export`, `ledger_audit`, `ledger_sync`, `ledger_rebuild`, `ledger_compact`, `ledger_ingest_sdd`~~ — CLI-only; only the five ledger tools listed above are exposed.
- ~~`LedgerStore` on ArangoDB~~ — `LedgerStore(SQLiteWikiStore)` is SQLite-only (`ledger/store.py:24`).
- ~~`LedgerService(ledger_dir=...)`~~ — only `from_root(root)` (git-backed shared root) and the collaborator-injecting `__init__` exist (`service.py:99-141`).
- ~~`wikitoolkit claude install` writing `.mcp.json`~~ — that command (`coding_agents.install`) writes hooks/skill/instruction blocks only; `.mcp.json` and `.codex/config.toml` are written by **`parrot claude install`** / **`parrot codex install`** (`claude_code/installer.py`, `codex/installer.py`).
- ~~`--remote` flag on any installer~~ — installers always write the stdio `command`/`args` entry.
- ~~`wikitoolkit --version`~~ — not a valid option (only `-v/--verbose`).

---

## Parallelism Assessment

- **Internal parallelism**: four largely independent lanes — (1) **server**:
  tool-builder split + `wikitoolkit serve` + bearer/actor middleware +
  multi-wiki mounts + `LedgerService` explicit dir; (2) **client + CLI
  proxy**: `remote.py`, `WikiRemoteConfig`, command branching, stdio
  pass-through; (3) **bulk ingest tools** + delta push in
  `build`/`upsert`/`ingest`/`sync`; (4) **installers** (claude + codex
  `--remote`, status, uninstall). Lanes 1 and 2 share `mcp_server.py` and
  `project.py` (the `remote` model must land first); lanes 2 and 3 both
  touch `cli.py`, so their commits must be sequenced or split by command
  group.
- **Cross-feature independence**: no open wiki feature on `dev` as of
  2026-09-17 (FEAT-557 / FEAT-566 completed). `cli.py` (≈5 000 lines) is
  the hot file — any concurrent wiki feature would conflict there.
  `claude_code/installer.py` is shared with FEAT-556 follow-ups.
  `packages/ai-parrot-server/src/parrot/mcp/transports/*` should be
  consumed read-only.
- **Recommended isolation**: `mixed` — one feature worktree for lanes 1–3
  (sequential: config model → server → client/proxy → bulk tools), and the
  installer lane (4) may run in parallel in a second worktree once the
  `remote` config field and the HTTP entry shape are fixed in the spec.
- **Rationale**: the server/client/bulk work forms a dependency chain over
  the same two files; the installer work touches disjoint files and only
  needs the agreed entry shape, so it is safe to parallelise.

---

## Open Questions

- [x] Feature or hotfix; base branch? — *Owner: Jesus*: `type: feature`, `base_branch: dev`.
- [x] Where does the remote server run? — *Owner: Jesus*: standalone `wikitoolkit serve` (aiohttp); not mounted in the ai-parrot server app for v1.
- [x] Authentication? — *Owner: Jesus*: static bearer token from an env var; OAuth2 out of scope.
- [x] How do build results reach the server? — *Owner: Jesus*: build locally into SQLite, push the delta through MCP bulk tools; server never scans repos.
- [x] One wiki per server or many? — *Owner: Jesus*: multi-wiki by path, `/mcp/<wiki_name>`.
- [x] Write attribution with a shared token? — *Owner: Jesus*: client sends `X-Wiki-Actor: human:<local-user>`; trusted for the internal team.
- [x] Local vs remote selection and failure behaviour? — *Owner: Jesus*: `remote` block in `wiki.json` (env-overlayable) + `WIKITOOLKIT_REMOTE_URL` override; fail-closed, no silent local fallback.
- [x] **Ledger storage on the server** — *Owner: Jesus*: v1 keeps `LedgerStore` as SQLite on the server host (centralised, unexposed). Porting the ledger to ArangoDB is a **follow-up feature** with its own spec (`wikitoolkit-ledger-arangodb`, see "Follow-up features"); this feature must not block on it and must leave `LedgerService` construction backend-agnostic enough for that port.
- [x] **CLI-only commands in remote mode** — *Owner: Jesus*: out of scope here. `link`, `memories`, `audit`, `ground`, `export`, `communities` and the non-tool `ledger` subcommands return "not available in remote mode" in v1; exposing them as MCP tools belongs to a **separate spec** (exposing wikitoolkit CLI commands as MCP tools — not yet present under `sdd/specs/` on 2026-09-17; slug to be linked from the spec §8 when it lands). Once those tools exist, the remote proxy picks them up through the same command→tool mapping with no protocol change.
- [x] **Stdio pass-through as the intermediate install path** — *Owner: Jesus*: yes. `wikitoolkit mcp` forwards `tools/list`/`tools/call` to the remote server whenever `remote` is configured, so the existing stdio `.mcp.json` / `.codex/config.toml` entries work against the remote plane with **no installer change** and always carry `X-Wiki-Actor`. This is the recommended v1 path for Codex (its native HTTP client cannot send custom headers) and the zero-migration path for every repo already installed; the native `"type": "http"` registration is an optional optimisation for Claude Code.
- [ ] **Server packaging**: make `ai-parrot-server` an optional extra of core (`ai-parrot[wikitoolkit-server]`) or move a dependency-light Streamable HTTP server into core? (Affects who can `pip install` the server image.) — *Owner: Jesus / spec*
- [ ] **Token gate implementation**: aiohttp middleware in `wikitoolkit serve` vs. `AuthMethod.API_KEY` with a one-token `api_key_store` (locate the `APIKeyStore` class first) — *Owner: spec*
- [ ] **Bulk-ingest limits**: max payload per `wiki_ingest_batch` call, slices per call, and whether embeddings (`upsert_embedding`) are pushed or recomputed server-side — *Owner: spec*
- [ ] **Federation in remote mode**: should `ns list` show the server's namespaces (read-only) so users understand what a remote `--ns` targets? — *Owner: Jesus*
- [x] **Exact Claude Code / Codex remote-MCP config keys** — *Owner: spec*: checked against `claude mcp add --help` (Claude Code 2.1.274) and `codex mcp add --help` on 2026-09-17. Claude Code: `.mcp.json` entry `{"type": "http", "url": "<url>", "headers": {"Authorization": "Bearer ${WIKITOOLKIT_TOKEN}"}}`; CLI `claude mcp add --transport http wikitoolkit <url> --header "Authorization: Bearer ${WIKITOOLKIT_TOKEN}" --scope project`; `${VAR}` expansion is confirmed at config level (2.1.274 changelog) — the installer task must include a smoke test that the header value expands. Codex: `[mcp_servers.wikitoolkit] url = "<url>"` + `bearer_token_env_var = "WIKITOOLKIT_TOKEN"` (+ optional `startup_timeout_sec`, `tool_timeout_sec`); CLI `codex mcp add --url <url> wikitoolkit --bearer-token-env-var WIKITOOLKIT_TOKEN`; project-level `.codex/config.toml` is honoured (already used by `parrot codex install`). Codex documents **no arbitrary-header key**, so `X-Wiki-Actor` cannot be sent by Codex's native HTTP client — the server must default the actor (e.g. to a per-token or `unknown` identity) when the header is absent, or Codex keeps using the stdio pass-through. Both hosts still accept legacy SSE, but it is not needed.
- [ ] **Default actor when `X-Wiki-Actor` is absent** (only native-HTTP callers without header support, e.g. Codex registered directly, or curl): proposed default `agent:unknown` for writes, reads unaffected. Low priority now that the stdio pass-through is the recommended Codex path. — *Owner: spec*
- [ ] **TLS termination**: `wikitoolkit serve` speaks plain HTTP behind a reverse proxy, or supports `ssl_cert_path`/`ssl_key_path` from `MCPServerConfig` directly? — *Owner: ops*
