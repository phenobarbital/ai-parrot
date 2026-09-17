---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: wikitoolkit as a remote (Streamable HTTP) MCP — server, CLI proxy, coding-agent install

**Feature ID**: FEAT-569
**Date**: 2026-09-17
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: next minor after 0.29.x (core `ai-parrot` + new optional extra; nothing ships in ai-parrot-server)
**Brainstorm**: `sdd/proposals/wikitoolkit-http-mcp.brainstorm.md` (accepted 2026-09-17, Option A)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Today `wikitoolkit` is consumed **locally**: the CLI opens a plane on disk
(SQLite under `.parrot/wiki/`) or connects **directly** to ArangoDB when
`backend: arangodb` is resolved (base `wiki.json` or a per-env overlay,
FEAT-461), and `wikitoolkit mcp` exposes the same plane to Claude Code /
Codex as a **stdio** MCP server (FEAT-403). Every team member — and every
coding agent — that wants the shared plane therefore needs network reach
to ArangoDB plus its credentials (`ARANGODB_*` via navconfig). Sharing the
graph means **exposing the database** (VPN, per-user DB credentials,
driver/analyzer version drift on every laptop).

We want a **remote wikitoolkit MCP server** that owns the ArangoDB
connection (and the SDD work ledger, FEAT-566) and that clients reach over
HTTPS with a bearer token. Three concrete actions are in scope:

1. **Expose wikitoolkit as an HTTP MCP** — `wikitoolkit serve`, speaking
   MCP Streamable HTTP, serving one or more wikis, ArangoDB behind it.
2. **`wikitoolkit` CLI and the stdio `wikitoolkit mcp` act as a proxy** to
   that server when the repo is configured for it — same commands, no local
   DB credentials.
3. **Install wikitoolkit as a remote HTTP MCP** in Claude Code and Codex via
   the existing installers.

Affected users: developers running Claude Code / Codex against shared wikis
(parrot, fieldsync, issues), ops (one deployable instead of N DB clients),
and the SDD dev-loop agents that write to the ledger.

### Goals

- G1. A standalone `wikitoolkit serve` process publishes the existing wiki
  tool set over MCP Streamable HTTP, one mount per wiki at
  `/mcp/<wiki_name>`, gated by a static bearer token.
- G2. Writes are attributed to the caller via `X-Wiki-Actor`; the hardcoded
  `agent:mcp` identity in the MCP tools is replaced by a request-scoped
  actor.
- G3. With a `remote` block in `.parrot/wiki.json` (env-overlayable) or
  `WIKITOOLKIT_REMOTE_URL`, the CLI proxies the tool-backed commands to the
  server, **fail-closed** (no silent fallback to the local plane).
- G4. `build` / `upsert` / `ingest` keep scanning locally and push changed
  source slices (pages + edges + symbols) to the server through bulk MCP
  tools; `sync push|pull` move authored knowledge through the same server.
- G5. `wikitoolkit mcp` (stdio) becomes a pass-through to the remote when
  `remote` is configured — the **v1 intermediate install path**: existing
  `.mcp.json` / `.codex/config.toml` entries work with no reinstall.
- G6. `parrot claude install --remote` / `parrot codex install --remote`
  write native HTTP entries under the same server key `wikitoolkit`, so
  `mcp__wikitoolkit__*` approvals stay valid.
- G7. Without `remote`, every local path is byte-identical to today; MCP
  tool names do not change.

### Non-Goals (explicitly out of scope)

- Porting `LedgerStore` to ArangoDB — follow-up feature
  `wikitoolkit-ledger-arangodb`; v1 keeps the ledger as SQLite on the
  server host (decided in brainstorm).
- Exposing the CLI-only commands (`link`, `memories`, `audit`, `ground`,
  `export`, `communities`, `ledger acknowledge|blockers|export|audit|sync|
  rebuild|ingest-sdd|compact`) as MCP tools — separate spec (not yet in
  `sdd/specs/`); in remote mode they are refused with a clear message.
- OAuth2 / per-user tokens; mounting the wiki MCP inside the ai-parrot
  server app; server-side `build` from git (brainstorm Option C, rejected);
  a store-level RPC backend (brainstorm Option B, rejected).
- Vector search over the remote (`search_vector` / embeddings are neither
  pushed nor proxied in v1).
- Federation configured from the client in remote mode (`ns add|remove`);
  namespaces are the server's configuration.

---

## 2. Architectural Design

### Overview

The remote server publishes exactly the tool set `wikitoolkit mcp` already
assembles — the six wiki tools, the three structural tools and the five
ledger tools — plus four **bulk tools** (`wiki_page_hashes`,
`wiki_ingest_batch`, `wiki_sync_push`, `wiki_sync_pull`) that exist only to
let clients move data without a database connection. The assembly currently
inlined in `create_wiki_mcp_server()` is extracted into a transport-agnostic
`build_wiki_tools()` used by three transports: the existing stdio server, a
new **pass-through stdio server** (forwards to the remote), and the new
**HTTP server**, which wraps ai-parrot-server's `StreamableHttpMCPServer`
one instance per wiki on a single aiohttp application.

Auth is `AuthMethod.API_KEY` with `api_key_header="Authorization"` and a
`StaticBearerKeyStore` whose `validate_key()` strips the `Bearer ` prefix
and compares against `WIKITOOLKIT_SERVER_TOKEN` in constant time — reusing
`RemoteMCPServerBase._authenticate_api_key()` unchanged. A tiny aiohttp
middleware reads `X-Wiki-Actor` (default `agent:unknown`) into a
`ContextVar` that the write tools consult in place of the literal
`"agent:mcp"` they hardcode today.

The client side is core-only: `RemoteWikiClient` is an aiohttp JSON-RPC
client for Streamable HTTP (initialize → `Mcp-Session-Id` → `tools/call`,
`Accept: application/json, text/event-stream`, decodes plain JSON or the
first SSE `message` event). The CLI branches once per proxied command:
remote → call the matching tool and print its text result; else today's
path. The mode switch is `WikiProjectConfig.remote` (overlayable, env
override `WIKITOOLKIT_REMOTE_URL`); any remote failure is a typed
`RemoteWikiError` with exit code 2, never a fallback.

Two server-side realities drive small changes in existing modules: the
server has **no source tree** and **no git checkout**. `StructuralService`
therefore gains a `read_repair=False` mode (no disk hashing, no
`_ensure_fresh`, `include_source` excerpts unavailable), and `LedgerService`
gains `from_dir()` so the ledger lives at an explicit `ledger_dir` instead of
`find_shared_root()`.

Decisions carried from the brainstorm and applied here: standalone process
(not mounted in the app), static bearer token, local build + MCP push,
multi-wiki by path, `X-Wiki-Actor`, fail-closed `remote` config, ledger on
server-side SQLite, CLI-only commands refused, pass-through as the v1
install path, Claude/Codex config keys as verified.

### Component Diagram

```
 laptop / CI                                                  server host (no repo, no git)
 ─────────────────────────────────────────────────            ────────────────────────────────────────────
 Claude Code ─"type":"http"─────────────────────┐             wikitoolkit serve  (aiohttp app, :8765)
 Codex ──stdio──▶ wikitoolkit mcp (pass-through)┼──HTTPS────▶ ┌ actor middleware (X-Wiki-Actor → ContextVar)
 wikitoolkit CLI ─▶ RemoteWikiClient ───────────┘  Bearer     │ /mcp/parrot    StreamableHttpMCPServer ─┐
      │  query/page/…  → tools/call                          │ /mcp/fieldsync StreamableHttpMCPServer ─┤ build_wiki_tools()
      │  build/upsert  → local scan → wiki_page_hashes        │ /mcp/<wiki>/info                        │   ├ 6 wiki tools
      │                 → wiki_ingest_batch (chunked)         │ StaticBearerKeyStore (API_KEY auth)     │   ├ 3 structural (read_repair=False)
      │  sync push/pull → wiki_sync_push / wiki_sync_pull     └─────────────────────────────────────────┘   ├ 5 ledger (LedgerService.from_dir)
      └  .parrot/wiki.json {remote:{url,token_env}}                       │                                └ 4 bulk tools
                                                             ArangoDBWikiStore ──▶ ArangoDB        LedgerStore (SQLite, server disk)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/mcp_server.py` `create_wiki_mcp_server()` | refactors | body becomes `build_wiki_tools()`; stdio wrapper kept; `main()` picks pass-through when `remote` resolves |
| `parrot/knowledge/wiki/tools.py` | extends | actor ContextVar replaces `"agent:mcp"` literals (L352, L654); four bulk tools added |
| `parrot/knowledge/wiki/structural/service.py` `StructuralService` | extends | `read_repair: bool = True` ctor flag; `create_structural_tools(..., read_repair=True)` |
| `parrot/knowledge/wiki/ledger/service.py` `LedgerService` | extends | `from_dir(ledger_dir, *, sqlite_policy)` classmethod |
| `parrot/knowledge/wiki/project.py` `WikiProjectConfig` / `WikiEnvOverlay` | extends | `remote: WikiRemoteConfig | None`; `resolve_remote()` |
| `parrot/knowledge/wiki/sync.py` `_sync_records` | uses | server-side body of `wiki_sync_push/pull`; client path via MCP replaces `_open_remote()` for `sync` when `remote` is set |
| `parrot/knowledge/wiki/cli.py` | extends | `serve` command; remote branch in proxied commands; refusals; push after build |
| `parrot/mcp/transports/streamable_http.py` (ai-parrot-server) `StreamableHttpMCPServer` | uses (read-only) | one instance per wiki with `base_path=/mcp/<wiki>`, `parent_app` shared |
| `parrot/mcp/transports/base.py` `RemoteMCPServerBase._authenticate_api_key` | uses | validates via `config.api_key_store.validate_key()`; sets `request["mcp_user"]` |
| `parrot/mcp/oauth_server.py` `APIKeyStore` / `APIKeyRecord` | subclasses | `StaticBearerKeyStore(APIKeyStore)` |
| `parrot/mcp/config.py` `MCPServerConfig` | uses | `transport="streamable-http"`, `auth_method=API_KEY`, `api_key_header="Authorization"`, `base_path`, ssl fields |
| `claude_code/{assets,installer,cli}.py` | extends | `mcp_json_entry_remote()`, `--remote`, managed-entry detection, status `transport` |
| `codex/{assets,installer}.py` | extends | `mcp_block(..., remote=...)` writing `url` + `bearer_token_env_var` |
| `packages/ai-parrot/pyproject.toml` | extends | optional extra `wikitoolkit-server = ["ai-parrot-server"]` |

### Data Models

```python
# parrot/knowledge/wiki/project.py  (new, next to WikiNamespaceConfig)
class WikiRemoteConfig(BaseModel):
    """Remote wikitoolkit MCP server this repository proxies to."""
    url: str                                   # absolute http(s) URL of the wiki mount, e.g. https://wiki.example.com/mcp/parrot
    token_env: str = "WIKITOOLKIT_TOKEN"       # env var holding the bearer token
    timeout: float = Field(default=30.0, ge=1.0, le=600.0)   # per-call seconds
    actor: str | None = None                   # override X-Wiki-Actor; default = _authoring_identity(None)
    verify_tls: bool = True

# parrot/knowledge/wiki/serve.py  (new)
class WikiServerEntry(BaseModel):
    """One wiki served by `wikitoolkit serve`."""
    root: Path                                 # directory holding .parrot/wiki.json (backend MUST be arangodb)
    env: str | None = None                     # WIKI_ENV overlay to merge (load_effective_config(root, env=...))
    ledger_dir: Path | None = None             # default: WikiProjectConfig.ledger_path(root)
    description: str = ""

class WikiServerConfig(BaseModel):
    """`wikitoolkit serve --config server.yaml`."""
    host: str = "127.0.0.1"
    port: int = 8765
    base_path: str = "/mcp"                    # mounts at f"{base_path}/{wiki_name}"
    token_env: str = "WIKITOOLKIT_SERVER_TOKEN"
    default_actor: str = "agent:unknown"       # when X-Wiki-Actor is absent
    allowed_origins: list[str] | None = None
    ssl_cert_path: Path | None = None
    ssl_key_path: Path | None = None
    session_ttl: int = 3600
    wikis: dict[str, WikiServerEntry]          # key = wiki_name (validated by validate_namespace_name)

# parrot/knowledge/wiki/tools.py  (new payload models for the bulk tools)
class SourceSlicePayload(BaseModel):
    """One `replace_source_slice` unit crossing the wire."""
    source_id: str
    pages: list[WikiPageRecord]
    edges: list[tuple[str, str, str]] = []
    symbols: list[SymbolRecord] = []

class IngestBatchInput(BaseModel):
    slices: list[SourceSlicePayload] = Field(default_factory=list, max_length=200)
    deleted_source_ids: list[str] = Field(default_factory=list, max_length=200)   # files removed since the last push (S8)
    batch_id: str | None = None                # client UUID, logged per applied slice; re-applying the same batch is idempotent

class IngestBatchReport(BaseModel):
    slices_applied: int; slices_deleted: int; pages_written: int; edges_written: int; symbols_written: int
    symbols_dropped: int = 0                   # backend has no native symbol table (§8 Q5)
    rejected: list[str] = []                   # source_ids refused (oversize / invalid)

class PageHashesInput(BaseModel):
    concept_ids: list[str] = Field(..., max_length=2000)

class SyncPagesInput(BaseModel):
    """Client → server authored knowledge (push) or server → client (pull)."""
    pages: list[WikiPageRecord] = []
    edges: list[tuple[str, str, str, str]] = []    # (src, dst, rel, "asserted")
    since: str | None = None                    # pull: ISO-8601 lower bound on updated_at
    skip_asserted_by: str | None = None         # pull: exclude own writes

# parrot/knowledge/wiki/remote.py  (new)
class RemoteWikiError(Exception):
    """Typed remote failure. `code` ∈ {token_missing, unauthorized, wiki_not_found,
    unreachable, timeout, protocol, tool_error}; `status` is the HTTP status or None."""
    def __init__(self, code: str, message: str, *, url: str, status: int | None = None) -> None: ...
```

Wire limits (decided here, brainstorm §8): one `wiki_ingest_batch` call carries
at most **200 slices** and **1 MiB** of JSON (client-enforced chunking, server
rejects oversize with `tool_error`); `wiki_page_hashes` accepts at most
**2000** ids per call.

### New Public Interfaces

```python
# parrot/knowledge/wiki/mcp_server.py
def build_wiki_tools(root: Path, config: WikiProjectConfig, *, ledger_dir: Path | None = None,
                     read_repair: bool = True, include_bulk_tools: bool = False) -> WikiToolBundle: ...
def create_wiki_mcp_server(root: Path) -> StdioMCPServer: ...          # unchanged signature, now a thin wrapper
def create_proxy_mcp_server(remote: WikiRemoteConfig) -> StdioMCPServer: ...

# parrot/knowledge/wiki/actor.py
def current_actor(default: str = "agent:mcp") -> str: ...
def actor_scope(actor: str | None) -> AbstractContextManager[None]: ...

# parrot/knowledge/wiki/remote.py
class RemoteWikiClient:
    async def list_tools(self) -> list[dict[str, Any]]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    async def call_tool_text(self, name: str, arguments: dict[str, Any]) -> str: ...
    async def close(self) -> None: ...

# parrot/knowledge/wiki/project.py
def resolve_remote(config: WikiProjectConfig) -> WikiRemoteConfig | None: ...   # env override applied

# parrot/knowledge/wiki/serve.py
class StaticBearerKeyStore(APIKeyStore): ...
async def build_server_app(config: WikiServerConfig) -> web.Application: ...
async def run_server(config: WikiServerConfig) -> None: ...

# CLI
wikitoolkit serve --config server.yaml [--host] [--port] [--ssl-cert] [--ssl-key]
parrot claude install --remote [--remote-url URL] [--token-env NAME]
parrot codex  install --remote [--remote-url URL] [--token-env NAME]
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Remote config model | yes | `WikiRemoteConfig` fields fixed above; `remote` on `WikiProjectConfig` + `WikiEnvOverlay`; `resolve_remote()` precedence `WIKITOOLKIT_REMOTE_URL` > overlay > base; `WikiConfigError` for invalid URL | — |
| M2: Tool builder + actor context + server-mode hooks | yes | `build_wiki_tools()` = current `create_wiki_mcp_server()` body; `WikiToolBundle`; `actor.py` ContextVar; `StructuralService(read_repair=)`; `LedgerService.from_dir()`; literals at tools.py:352/654 replaced by `current_actor()` | — |
| M3: Core Streamable HTTP client | yes | `RemoteWikiClient` contract + error codes fixed; SSE parsing mirrors `HttpMCPSession._read_sse_response` (transports/http.py:473-530); one re-initialize on unknown session | — |
| M4: `wikitoolkit serve` | yes | `WikiServerConfig`; `StaticBearerKeyStore`; `MCPServerConfig(transport="streamable-http", auth_method=API_KEY, api_key_header="Authorization", base_path=f"{base}/{wiki}")`; one `StreamableHttpMCPServer(parent_app=app)` per wiki; actor middleware; lazy import with typed error | — |
| M5: Bulk tools | yes | four tools, payload models and limits fixed above; server body = `replace_source_slice` + `upsert_symbols` under `wiki_write_lock`; sync body = `_sync_records` with an in-memory `InMemoryWikiStore` holding the payload | — |
| M6: CLI remote proxy + pass-through + push | yes | command→tool table fixed in §3 M6; refusal list fixed; `build/upsert/ingest --no-push`; `sync` via tools; `ProxyStdioMCPServer` | — |
| M7: Installers `--remote` | yes | entry shapes fixed (`type: http`, `url`, `headers.Authorization = "Bearer ${TOKEN_ENV}"`; Codex `url` + `bearer_token_env_var`); managed detection extended | — |
| M8: Docs + end-to-end evidence | yes | `docs/guides/llm-wiki-remote.md`; in-process e2e test (serve on 127.0.0.1 ephemeral port → CLI proxy) | — |

### Module 1: Remote config model
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
- **Responsibility**: declare the `remote` block, overlay it per env, and resolve the effective remote (env override, token presence check deferred to the client).
- **Depends on**: existing `WikiProjectConfig` / `WikiEnvOverlay` / `load_effective_config`.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/project.py
  class WikiRemoteConfig(BaseModel):                       # new, before WikiProjectConfig (verified: project.py:379)
      """Remote wikitoolkit MCP server this repository proxies to (FEAT-569)."""
      url: str
      token_env: str = "WIKITOOLKIT_TOKEN"
      timeout: float = Field(default=30.0, ge=1.0, le=600.0)
      actor: str | None = None
      verify_tls: bool = True
      @field_validator("url")
      @classmethod
      def _absolute_http_url(cls, value: str) -> str:
          """Reject anything that is not an absolute http(s) URL; strip a trailing slash."""

  class WikiProjectConfig(BaseModel):                      # verified: project.py:379-543
      remote: WikiRemoteConfig | None = Field(default=None, description="Proxy every tool-backed command to this remote MCP (FEAT-569)")

  class WikiEnvOverlay(BaseModel):                         # verified: project.py:780-839
      remote: WikiRemoteConfig | None = None               # merged like every other overlay field

  REMOTE_URL_ENV = "WIKITOOLKIT_REMOTE_URL"

  def resolve_remote(config: WikiProjectConfig) -> WikiRemoteConfig | None:
      """Effective remote: `WIKITOOLKIT_REMOTE_URL` (keeps token_env/timeout from config or defaults) > config.remote > None."""
  ```

### Module 2: Tool builder, actor context, server-mode hooks
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py`, new `packages/ai-parrot/src/parrot/knowledge/wiki/actor.py`, `tools.py`, `structural/service.py`, `structural/tools.py`, `ledger/service.py`
- **Responsibility**: one assembly for every transport; request-scoped actor; make the assembly runnable on a host with no source tree and no git root.
- **Depends on**: none (M4/M5/M6 depend on it).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/actor.py  (new)
  _ACTOR: ContextVar[str | None] = ContextVar("wiki_actor", default=None)
  def current_actor(default: str = "agent:mcp") -> str:
      """Identity asserting the current write; `default` keeps today's stdio behaviour when nothing is set."""
  @contextmanager
  def actor_scope(actor: str | None) -> Iterator[None]:
      """Set the actor for the enclosed block (used by the HTTP middleware and tests)."""

  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
  @dataclass
  class WikiToolBundle:
      """Everything a transport needs to register."""
      tools: list[AbstractTool]          # wiki + structural (+ ledger, + bulk) tools
      vault_tools: list[AbstractTool]
      description: str
      store: BaseWikiStore               # writable local plane
      read_store: BaseWikiStore          # federated read view
      ledger_service: "LedgerService | None"

  def build_wiki_tools(root: Path, config: WikiProjectConfig, *, ledger_dir: Path | None = None,
                       read_repair: bool = True, include_bulk_tools: bool = False) -> WikiToolBundle:
      """Extracted body of create_wiki_mcp_server() (verified: mcp_server.py:94-~270).
      ledger_dir=None keeps `LedgerService.from_root(root)` gated by find_shared_root; a Path uses `from_dir`.
      read_repair=False is passed to create_structural_tools. include_bulk_tools registers M5's tools."""

  async def abuild_wiki_tools(root: Path, config: WikiProjectConfig, *, ledger_dir: Path | None = None,
                              read_repair: bool = True, include_bulk_tools: bool = False) -> WikiToolBundle:
      """Async twin used by the long-lived HTTP server (design research S2): awaits resolve_namespaces() and
      store.initialize() on the SERVING loop — never through _run_sync (verified: mcp_server.py:70-92) — so
      ArangoDB connections are owned by the process, not re-opened lazily after a probe (federation.py:306-357).
      build_wiki_tools() is the sync wrapper for the stdio path and keeps today's behaviour byte-identical."""
  async def close_bundle(bundle: WikiToolBundle) -> None:
      """Close bundle.store, every namespace handle and bundle.ledger_service.store (called from aiohttp on_cleanup)."""

  def create_wiki_mcp_server(root: Path) -> StdioMCPServer:   # verified: mcp_server.py:94 — signature unchanged
      """Thin wrapper: build_wiki_tools(root, load_effective_config(root).config) → StdioMCPServer(LocalServerConfig(name="wikitoolkit"))."""

  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
  #   L352  asserted_by="agent:mcp"   →  asserted_by=current_actor()          (WikiRememberTool._execute, verified tools.py:318-398)
  #   L654  actor="agent:mcp"         →  actor=current_actor()                (LedgerOpenTool._execute, verified tools.py:637-658)
  #   WikiNoteTool / LedgerClaimTool / LedgerCloseTool: same substitution wherever "agent:mcp" is asserted.

  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py
  class StructuralService:                                                  # verified: service.py:127
      def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig, *, read_repair: bool = True) -> None:
          """read_repair=False: `_ensure_fresh` returns [] without touching disk (verified: service.py:425),
          `_read_source_excerpt` returns (None, False) (verified: service.py:258-285), `_open_sources` still opened for symbol lookups."""
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py
  def create_structural_tools(store: BaseWikiStore, root: Path, config: WikiProjectConfig, *, read_repair: bool = True) -> list[AbstractTool]: ...  # verified: tools.py:225-263

  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
  class LedgerService:                                                      # verified: service.py:96-384
      @classmethod
      def from_dir(cls, ledger_dir: Path, *, sqlite_policy: SQLitePragmaPolicy | None = None) -> "LedgerService":
          """Open <ledger_dir>/ledger.db + events.jsonl exactly like from_root (verified: service.py:114-141) but with
          shared_root=ledger_dir.parent.parent and no find_shared_root(); merge_blockers()' per-spec index lookup
          (verified: service.py:311-323) then yields [] — documented server limitation."""
  ```

### Module 3: Core Streamable HTTP client
- **Path**: new `packages/ai-parrot/src/parrot/knowledge/wiki/remote.py`
- **Responsibility**: talk MCP Streamable HTTP to one wiki mount with aiohttp only; typed errors; actor header; one transparent re-initialize when the server forgets the session.
- **Depends on**: M1 (`WikiRemoteConfig`).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/remote.py  (new; core dep aiohttp only)
  class RemoteWikiError(Exception):
      """See §2 Data Models. `exit_code` is always 2 for the CLI."""
      code: str; url: str; status: int | None

  class RemoteWikiClient:
      """Minimal Streamable HTTP JSON-RPC client (protocol "2025-03-26", verified supported: server_base.py:17)."""
      def __init__(self, remote: WikiRemoteConfig, *, actor: str, session: aiohttp.ClientSession | None = None) -> None:
          """Raises RemoteWikiError(code="token_missing") when os.environ[remote.token_env] is unset/empty."""
      async def __aenter__(self) -> "RemoteWikiClient": ...
      async def __aexit__(self, *exc) -> None: ...
      async def initialize(self) -> dict[str, Any]:
          """POST initialize (+ notifications/initialized); stores Mcp-Session-Id. 401/403→unauthorized, 404→wiki_not_found,
          ClientConnectorError→unreachable, asyncio.TimeoutError→timeout."""
      async def list_tools(self) -> list[dict[str, Any]]: ...
      async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
          """Returns the JSON-RPC `result` (MCP content envelope). A JSON-RPC error → RemoteWikiError(code="tool_error").
          On HTTP 404 with a known session id (expired session): re-initialize once and retry ONLY when `name` is in
          READ_ONLY_TOOLS; otherwise raise RemoteWikiError(code="session_expired") — never replay a write (design research S5)."""

  READ_ONLY_TOOLS: frozenset[str] = frozenset({"wiki_query", "wiki_page", "wiki_related", "wiki_status", "wiki_symbol_lookup",
      "wiki_code_outline", "wiki_blast_radius", "wiki_page_hashes", "ledger_ready", "ledger_context", "wiki_sync_pull"})
      async def call_tool_text(self, name: str, arguments: dict[str, Any]) -> str:
          """Concatenated `content[*].text` of call_tool()."""
      async def close(self) -> None: ...

  def _decode_body(content_type: str, body: bytes) -> dict[str, Any]:
      """application/json → json; text/event-stream → first `data:` JSON message (mirrors transports/http.py:473-530)."""
  ```

### Module 4: `wikitoolkit serve`
- **Path**: new `packages/ai-parrot/src/parrot/knowledge/wiki/serve.py`; `cli.py` (`serve` command); `packages/ai-parrot/pyproject.toml` (extra)
- **Responsibility**: load `WikiServerConfig`, open each wiki's plane (ArangoDB) and ledger, mount one Streamable HTTP MCP server per wiki, gate with the static token, propagate the actor.
- **Depends on**: M2 (`build_wiki_tools`), M5 (bulk tools registered via `include_bulk_tools=True`); ai-parrot-server at runtime (lazy import).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/serve.py  (new)
  class WikiServerEntry(BaseModel): ...      # §2 Data Models
  class WikiServerConfig(BaseModel):
      @classmethod
      def from_yaml(cls, path: Path) -> "WikiServerConfig": ...
      @field_validator("wikis")
      @classmethod
      def _names(cls, value): """validate_namespace_name(name) for every key (verified: project.py:147-178)."""

  class StaticBearerKeyStore(APIKeyStore):   # APIKeyStore verified: ai-parrot-server parrot/mcp/oauth_server.py:86; APIKeyRecord :75
      """Single static token. `validate_key()` (verified :156) accepts "Bearer <token>" or "<token>", compares with
      hmac.compare_digest, returns APIKeyRecord(user_id="token:<sha256[:8]>"). `log_session_start()` (verified :194) is a no-op."""
      def __init__(self, token: str) -> None: ...

  @web.middleware
  async def actor_middleware(request: web.Request, handler) -> web.StreamResponse:
      """Read X-Wiki-Actor (fallback: app["wiki_default_actor"]); validate against ^(human|agent|service):[\\w.@-]{1,64}$;
      set request["wiki_actor"] and run the handler inside actor_scope(actor). Runs BEFORE auth so 401s are attributed too."""

  def _import_server_stack():
      """Lazy: from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer; from parrot.mcp.config import MCPServerConfig, AuthMethod.
      ImportError → click.ClickException("wikitoolkit serve needs the ai-parrot-server package: pip install 'ai-parrot[wikitoolkit-server]'")."""

  async def build_server_app(config: WikiServerConfig) -> web.Application:
      """Validate first (fail-fast, before binding): every wiki name passes validate_namespace_name AND is URL-safe; the normalised
      routes f"{base_path}/{name}" are pairwise distinct (design research S7); each entry's effective config
      (load_effective_config(entry.root, env=entry.env).config) has backend == "arangodb" unless allow_sqlite_for_tests.
      Then register an on_startup hook per wiki that awaits abuild_wiki_tools(entry.root, cfg, ledger_dir=entry.ledger_dir or
      cfg.ledger_path(entry.root), read_repair=False, include_bulk_tools=True) ON THE SERVING LOOP, builds
      StreamableHttpMCPServer(MCPServerConfig(name=f"wikitoolkit-{name}", transport="streamable-http", auth_method=AuthMethod.API_KEY,
      api_key_header="Authorization", api_key_store=StaticBearerKeyStore(token), base_path=f"{config.base_path}/{name}",
      allowed_origins=config.allowed_origins, session_ttl=config.session_ttl), parent_app=app), registers bundle.tools + bundle.vault_tools
      and awaits server.start(); the matching on_cleanup awaits server.stop() then close_bundle(bundle) (design research S2).
      The process owns every store connection for its lifetime. Distinct base paths per wiki (precedent: parrot_server.py:121-147).
      `/info` is behind the same auth as the MCP endpoint (AC2)."""

  async def run_server(config: WikiServerConfig) -> None:
      """Single-process serving: web.AppRunner + one TCPSite(host, port, ssl_context from ssl_cert_path/ssl_key_path); SIGTERM → graceful stop.
      Sessions live in the default InMemorySessionStore (verified: streamable_http.py:277-279), so v1 MUST NOT be run behind a
      multi-worker launcher (gunicorn --workers > 1) without sticky routing — documented in AC16; Redis-backed sessions are §8 Q3."""

  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/cli.py  (new command in the `wiki` group, verified: cli.py:1328)
  @wiki.command()
  @click.option("--config", "config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
  @click.option("--host"), @click.option("--port", type=int), @click.option("--ssl-cert"), @click.option("--ssl-key")
  def serve(config_path: Path, host: str | None, port: int | None, ssl_cert: Path | None, ssl_key: Path | None) -> None:
      """Serve one or more wikis as MCP Streamable HTTP (FEAT-569). Token from $<token_env>; missing → exit 1."""

  # modifies packages/ai-parrot/pyproject.toml  [project.optional-dependencies]  (precedent `server = ["ai-parrot-server[all]"]`, verified :357-359)
  wikitoolkit-server = ["ai-parrot-server"]
  ```

### Module 5: Bulk tools (ingest, hashes, sync)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
- **Responsibility**: the only server surface a client needs to move data: delta detection, slice replacement with symbols, authored-knowledge sync in both directions. Registered by `build_wiki_tools(include_bulk_tools=True)` only (never in the local stdio server).
- **Depends on**: M2 (`current_actor`, registration hook).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
  class WikiPageHashesTool(AbstractTool):
      name = "wiki_page_hashes"
      """Return {concept_id: content_hash|null} for up to 2000 ids — the delta oracle for build pushes."""
      async def _execute(self, concept_ids: list[str]) -> ToolResult:   # → store.page_hashes (verified: store.py:803)

  class WikiIngestBatchTool(AbstractTool):
      name = "wiki_ingest_batch"
      """Apply ≤200 SourceSlicePayload: per slice `replace_source_slice(source_id, pages, edges)` (verified: store.py:550-555;
      atomic PER SLICE, backend-defined — SQLite impl store.py:1557-1562 deletes the old slice then inserts) then
      `upsert_symbols(symbols, source_id=source_id)` (verified: store.py:687-705 — DEFAULT IS A NO-OP on backends without a native
      symbol table; ArangoDBWikiStore has none, see §8 Q5), all under wiki_write_lock (verified: project.py:71-131).
      `deleted_source_ids` are removed via replace_source_slice(source_id, pages=[], edges=[]) (design research S8 — page_hashes
      cannot express deletions). `batch_id` (client UUID) is logged with every applied slice for idempotent re-runs/audit.
      Oversize (>1 MiB serialized) → ToolResult(success=False, error="payload too large"). Returns IngestBatchReport
      (+ `symbols_dropped: int` when the backend cannot persist symbols)."""
      async def _execute(self, slices: list[SourceSlicePayload], deleted_source_ids: list[str] = [], batch_id: str | None = None) -> ToolResult: ...

  class WikiSyncPushTool(AbstractTool):
      name = "wiki_sync_push"
      """Client authored knowledge → this plane. Body: InMemoryWikiStore seeded with `pages`/`edges`, then
      _sync_records(source=mem, destination=self._store, direction="push", env=<wiki>, dry_run=False, skip_asserted_by=None)
      (verified: sync.py:221-269). Returns SyncReport fields."""
      async def _execute(self, pages: list[WikiPageRecord], edges: list[tuple[str, str, str, str]] = ...) -> ToolResult: ...

  class WikiSyncPullTool(AbstractTool):
      name = "wiki_sync_pull"
      """This plane's memory-origin pages (+ asserted edges) newer than `since`, excluding `skip_asserted_by`, ordered by
      (updated_at, concept_id), at most `limit` (default 500, max 2000) per call; `next_cursor` is an opaque
      "<updated_at>|<concept_id>" the client passes back as `cursor` (design research S9). No tombstones — deletions are not
      exchanged, matching the existing engine (sync.py header: "deletes are never propagated"). Returns SyncPagesInput shape + next_cursor."""
      async def _execute(self, since: str | None = None, skip_asserted_by: str | None = None, limit: int = 500, cursor: str | None = None) -> ToolResult: ...

  def create_bulk_tools(store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> list[AbstractTool]: ...
  ```

### Module 6: CLI remote proxy, stdio pass-through, build push
- **Path**: new `packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py`; `cli.py`; `mcp_server.py`
- **Responsibility**: the user-visible proxy. One helper decides remote vs local; each proxied command branches at its top; unsupported commands refuse; `build/upsert/ingest` push deltas; `sync` uses the bulk tools; `wikitoolkit mcp` forwards when remote is configured.
- **Depends on**: M1, M3, M5 (payload models); M2 for `create_proxy_mcp_server`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py  (new)
  def remote_or_none(path_: str | None) -> tuple[Path, WikiEffectiveConfig, WikiRemoteConfig | None]:
      """_resolve_project_effective(path_) (verified: cli.py:375-389) + resolve_remote(); never opens a store."""
  def remote_client(remote: WikiRemoteConfig, *, by: str | None = None) -> RemoteWikiClient:
      """actor = remote.actor or _authoring_identity(by) (verified: cli.py:3027-3049)."""
  def call_remote_text(remote: WikiRemoteConfig, tool: str, arguments: dict[str, Any], *, by: str | None = None) -> str:
      """Sync wrapper (uses cli._run, verified: cli.py:494): opens client, initialize, call_tool_text, close.
      RemoteWikiError → click.ClickException(f"[remote:{e.code}] {e}") with exit code 2."""
  def refuse_remote(command: str, hint: str = "") -> NoReturn:
      """raise click.UsageError(f"`wikitoolkit {command}` is not available in remote mode ({hint})")."""
  def remote_aware(*, proxied: bool, tool: str | None = None) -> Callable:
      """Decorator applied to every command BEFORE its body runs (design research S10): resolves the remote via remote_or_none()
      and stores it in ctx.obj["remote"]; when a remote is configured it (a) rejects --store/--backend with a UsageError,
      (b) refuses non-proxied commands, (c) guarantees no _open_store()/_require_built()/is_built() call happens for proxied
      read commands. Local mode is untouched (byte-identical behaviour, AC14)."""
  async def push_slices(client: RemoteWikiClient, store: BaseWikiStore, rel_paths: list[str]) -> IngestBatchReport:
      """For the changed files: collect slice (pages via store.list_pages/source_id, edges via neighbors, symbols via symbols_for),
      ask wiki_page_hashes, drop unchanged, chunk ≤200 slices / ≤1 MiB, call wiki_ingest_batch per chunk; one retry per chunk."""

  # Command → tool mapping (remote branch at the top of each command; else unchanged local path)
  #   query          → wiki_query {question, budget_tokens, namespace, include_symbols}   prints tool text (packed result)
  #   page           → wiki_page {page_id, namespace}
  #   related        → wiki_related {page_id, namespace}
  #   status         → wiki_status {}  + prints "mode: remote (<url>)"
  #   remember       → wiki_remember {fact, category, title, link_page_id, rel}
  #   note           → wiki_note {page_id, text}
  #   symbols lookup → wiki_symbol_lookup · symbols outline → wiki_code_outline · symbols blast → wiki_blast_radius
  #   ledger open    → ledger_open · ledger ready → ledger_ready · ledger claim → ledger_claim · ledger close → ledger_close · ledger context → ledger_context
  #   build/upsert/ingest → local run unchanged, then push_slices(changed) unless --no-push; prints IngestBatchReport
  #   sync push      → local memory pages → wiki_sync_push ;  sync pull → wiki_sync_pull → local upsert (LWW via _sync_records with mem source)
  # Refused in remote mode: --store/--backend on any command, ns add|list|remove, communities, export, link, memories, audit, ground,
  #   sync obsidian, ledger acknowledge|blockers|export|sync|rebuild|ingest-sdd|compact|audit, ingest-jira, claude-hook is unaffected.

  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
  class ProxyStdioMCPServer(StdioMCPServer):                  # StdioMCPServer verified: parrot/mcp/local_server.py:36
      """tools/list and tools/call forwarded to RemoteWikiClient; initialize answered locally with the remote's serverInfo."""
      async def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]: ...    # verified base: server_base.py:~95
      async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]: ...    # verified base: server_base.py:~105
  def create_proxy_mcp_server(remote: WikiRemoteConfig) -> StdioMCPServer: ...
  def main() -> None:
      """Unchanged root discovery; if resolve_remote(config) → create_proxy_mcp_server (no is_built() requirement); else today's path (verified: mcp_server.py main())."""
  ```

### Module 7: Installers `--remote`
- **Path**: `claude_code/assets.py`, `claude_code/installer.py`, `claude_code/cli.py`, `codex/assets.py`, `codex/installer.py`
- **Responsibility**: write the native HTTP registration under the unchanged server key `wikitoolkit`; keep uninstall/status honest about both shapes.
- **Depends on**: M1 (reads `remote` from the effective config when `--remote-url` is not given).
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
  def mcp_json_entry_remote(url: str, token_env: str) -> dict:                     # next to mcp_json_entry (verified: assets.py:108-116)
      """{"type": "http", "url": url, "headers": {"Authorization": f"Bearer ${{{token_env}}}"}} — Claude Code expands ${VAR} in .mcp.json (verified in brainstorm §8, Claude Code 2.1.274)."""
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
  def _install_mcp_json(root: Path, *, remote: WikiRemoteConfig | None = None) -> str:   # verified: installer.py:462-551
      """entry = mcp_json_entry_remote(...) if remote else assets.mcp_json_entry(root); reconciliation of "wikitoolkit" key unchanged."""
  def _is_wikitoolkit_entry(entry: Any) -> bool:
      """True for both managed shapes (stdio: command endswith wikitoolkit & args==["mcp"]; http: type=="http" and headers.Authorization startswith "Bearer ${")."""
  def install_claude_integration(root, config=None, git_hook=True, gitignore=True, bookstore=True, toolkits=(), approve_mcp=True,
                                 remote: WikiRemoteConfig | None = None) -> list[str]: ...          # verified: installer.py:770-778
  def integration_status(root: Path) -> dict[str, Any]: ...  # adds "mcp_transport": "stdio" | "http" | None   (verified: installer.py:985)
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py  (install command, verified: cli.py:107-118)
  #   --remote (flag) · --remote-url URL · --token-env NAME  → remote = WikiRemoteConfig(url=..., token_env=...) or config.remote; error if neither.
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
  def mcp_block(root: Path, toolkit_block: str = "", *, remote: WikiRemoteConfig | None = None) -> str:   # verified: assets.py:93-116
      """remote → lines: [mcp_servers.wikitoolkit] / url = "<url>" / bearer_token_env_var = "<token_env>" / default_tools_approval_mode = "approve".
      Codex has no header key: the actor header is NOT sent on this path (documented; pass-through recommended)."""
  # modifies packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
  def _install_mcp(root: Path, *, remote: WikiRemoteConfig | None = None) -> str: ...   # verified: installer.py:110-168
  def install_codex_integration(root, config=None, gitignore=True, bookstore=True, toolkits=(), remote: WikiRemoteConfig | None = None) -> list[str]: ...  # verified: installer.py:202-208
  ```

### Module 8: Docs and end-to-end evidence
- **Path**: new `docs/guides/llm-wiki-remote.md`; `docs/guides/llm-wiki-guide.md` (link); tests under `packages/ai-parrot/tests/knowledge/wiki/`
- **Responsibility**: operator guide (server.yaml, token, container, TLS-behind-proxy), client guide (`remote` block, env override, pass-through vs native), and the in-process e2e test that boots `build_server_app()` on an ephemeral port against a SQLite plane (test double for ArangoDB via a config flag `allow_sqlite_for_tests`) and drives the CLI proxy.
- **Depends on**: M1–M7.
- **Interface Skeleton**: documentation + tests only (see §4).

---

## 4. Test Specification

All new tests live in `packages/ai-parrot/tests/knowledge/wiki/` (the directory FEAT-557/FEAT-566 used; existing `test_mcp_server*.py`, `test_installer_mcp.py`, `test_codex_installer_conventions.py` are the siblings). Tests that import the ai-parrot-server transport use `pytest.importorskip("parrot.mcp.transports.streamable_http")`.

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_remote_config_roundtrip` | M1 | `remote` parses from `wiki.json`, overlay `wiki.dev.json` overrides `url`, invalid URL → `WikiConfigError` |
| `test_resolve_remote_env_override` | M1 | `WIKITOOLKIT_REMOTE_URL` wins over config; unset + no config → `None` |
| `test_build_wiki_tools_matches_legacy` | M2 | tool names from `build_wiki_tools()` equal today's `create_wiki_mcp_server(root).tools` keys (14 without vault/bulk) |
| `test_build_wiki_tools_bulk_only_when_requested` | M2 | `include_bulk_tools=False` never exposes `wiki_ingest_batch` |
| `test_actor_scope_replaces_agent_mcp` | M2 | `wiki_remember` inside `actor_scope("human:jl")` writes `asserted_by="human:jl"`; outside → `"agent:mcp"` |
| `test_structural_no_read_repair` | M2 | `read_repair=False`: outline works from stored symbols with the file absent; `include_source` → `source=None` |
| `test_ledger_from_dir` | M2 | `LedgerService.from_dir(tmp)` opens without a git root; `open_issue`/`claim` work; `merge_blockers` → `[]` |
| `test_client_decodes_json_and_sse` | M3 | `_decode_body` handles both content types (fixture bodies) |
| `test_client_error_mapping` | M3 | 401→`unauthorized`, 404→`wiki_not_found`, connection refused→`unreachable`, timeout→`timeout`, JSON-RPC error→`tool_error` |
| `test_client_token_missing` | M3 | constructor raises `token_missing` before any I/O |
| `test_client_reinitializes_once` | M3 | fake server forgets session → one re-init, second failure propagates |
| `test_static_bearer_store` | M4 | accepts `Bearer <tok>` and `<tok>`, rejects others, constant-time compare, `user_id` stable |
| `test_server_config_validation` | M4 | duplicate/invalid wiki names, `backend != arangodb` fail fast, missing token env → exit 1 |
| `test_actor_middleware_default_and_validation` | M4 | absent header → `default_actor`; malformed → 400 |
| `test_ingest_batch_limits` | M5 | 201 slices rejected; >1 MiB rejected; valid batch writes pages/edges/symbols atomically |
| `test_page_hashes_tool` | M5 | returns `None` for unknown ids, hash for known |
| `test_sync_push_pull_lww` | M5 | push older record does not overwrite newer; pull excludes `skip_asserted_by` |
| `test_cli_remote_query_prints_tool_text` | M6 | with fake remote, `wikitoolkit query` prints the packed text and never opens `wiki.db` |
| `test_cli_remote_refusals` | M6 | each refused command exits with `UsageError` naming remote mode |
| `test_cli_remote_fail_closed` | M6 | remote down → exit 2 with `[remote:unreachable]`, local plane untouched |
| `test_cli_build_pushes_delta` | M6 | second `build` pushes only changed slices (hash oracle) ; `--no-push` pushes nothing |
| `test_proxy_stdio_forwards` | M6 | `ProxyStdioMCPServer` forwards `tools/list`/`tools/call` and adds `X-Wiki-Actor` |
| `test_mcp_json_remote_entry` | M7 | `--remote` writes `type/url/headers`; re-run idempotent; uninstall removes; status reports `http` |
| `test_codex_remote_block` | M7 | `[mcp_servers.wikitoolkit]` has `url` + `bearer_token_env_var`, no `command`; managed block regenerates cleanly |
| `test_stdio_entry_unchanged_without_remote` | M7 | byte-identical `.mcp.json` / `config.toml` when `remote` is not configured |
| `test_tool_surface_golden` | M2/M4 | golden list of tool names for (stdio local, stdio pass-through, server) — fails on any drift (design research S11) |
| `test_client_no_replay_of_writes` | M3 | expired session + `wiki_remember` → `session_expired`, tool not re-sent; `wiki_query` → re-init + one retry |
| `test_server_owns_store_lifecycle` | M4 | stores initialised in `on_startup` on the serving loop, closed in `on_cleanup`; no `asyncio.run` inside the app |
| `test_server_duplicate_route_rejected` | M4 | two wiki names normalising to the same route fail validation before bind |
| `test_ingest_batch_deletions_and_batch_id` | M5 | `deleted_source_ids` removes slices; same `batch_id` re-applied is idempotent |
| `test_sync_pull_pagination` | M5 | 1200 memory pages → 3 pages of 500/500/200 with stable cursors |
| `test_ingest_symbols_dropped_on_backend_without_symbol_table` | M5 | `symbols_dropped` reported when `upsert_symbols` is the base no-op |
| `test_remote_aware_precedes_store_open` | M6 | with remote configured and no local `wiki.db`, every proxied read command succeeds; `--store` → UsageError before any file access |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_serve_and_proxy` | boot `build_server_app()` on 127.0.0.1:0 with two wikis (SQLite test planes, `allow_sqlite_for_tests=True`), token set; `RemoteWikiClient` initialize → `wiki_query` on both mounts; wrong token → 401; unknown wiki → 404 |
| `test_e2e_actor_attribution` | `wiki_remember` through the server with `X-Wiki-Actor: human:alice` → page `asserted_by == "human:alice"`; without header → `agent:unknown` |
| `test_e2e_build_push_roundtrip` | local `build` of a fixture repo → `push_slices` → remote `wiki_query`/`wiki_code_outline` return the pushed content |
| `test_streamable_http_interop_wiki` | official `mcp` SDK client (precedent `packages/ai-parrot-server/tests/mcp/test_streamable_http_interop.py`) lists tools on `/mcp/<wiki>` — skipped when `mcp` is not installed |

### Test Data / Fixtures
```python
@pytest.fixture
def remote_config(monkeypatch) -> WikiRemoteConfig:
    monkeypatch.setenv("WIKITOOLKIT_TOKEN", "t0k3n")
    return WikiRemoteConfig(url="http://127.0.0.1:1/mcp/parrot")

@pytest.fixture
async def fake_remote(aiohttp_server):
    """aiohttp test server answering initialize / tools/list / tools/call from a scripted table; records headers."""

@pytest.fixture
async def wiki_server(tmp_path, monkeypatch):
    """Two SQLite planes + WikiServerConfig(allow_sqlite_for_tests=True) → build_server_app() on an ephemeral port."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1. `wikitoolkit serve --config server.yaml` starts one aiohttp app and answers `GET <base>/<wiki>/info` for every configured wiki; a wiki whose effective backend is not `arangodb` aborts startup with a clear error.
- [ ] AC2. Requests without `Authorization: Bearer <WIKITOOLKIT_SERVER_TOKEN>` get 401 on POST, GET, DELETE **and** `/info`; wrong wiki name gets 404; the comparison is constant-time; the server refuses to start when the token env is unset.
- [ ] AC3. `tools/list` on `/mcp/<wiki>` returns exactly today's 14 tool names plus `wiki_page_hashes`, `wiki_ingest_batch`, `wiki_sync_push`, `wiki_sync_pull` (plus Obsidian tools only when a vault is configured); the local stdio server never lists the four bulk tools.
- [ ] AC4. Writes through the server record `X-Wiki-Actor` as `asserted_by` / ledger `actor`; absent header → `default_actor` (`agent:unknown`); malformed header → 400. The literal `"agent:mcp"` no longer appears in `tools.py` except as `current_actor()`'s default.
- [ ] AC5. Structural tools work on the server with no source tree (`read_repair=False`): outline from stored symbols, `include_source` yields no excerpt, no disk access attempted.
- [ ] AC6. The ledger on the server opens from `ledger_dir` without a git root (`LedgerService.from_dir`); `ledger_open|ready|claim|close|context` succeed remotely.
- [ ] AC7. With `remote` configured (base, overlay or `WIKITOOLKIT_REMOTE_URL`), `query|page|related|status|remember|note|symbols *|ledger open|ready|claim|close|context` run against the server and print the tool's text result (the same text an agent receives — not the local table renderer); remote resolution happens before any store open, so no local `wiki.db` is opened or required.
- [ ] AC8. Fail-closed: server unreachable / 401 / timeout → exit code 2 with `[remote:<code>]`; the local plane is never consulted. Missing token env → error before any request. An expired session is re-initialised once for read-only tools only; a write on an expired session fails with `session_expired` and is never replayed.
- [ ] AC9. Refused commands in remote mode (`--store/--backend`, `ns *`, `communities`, `export`, `link`, `memories`, `audit`, `ground`, `sync obsidian`, `ingest-jira`, non-tool `ledger` subcommands) exit with a usage error naming remote mode.
- [ ] AC10. `build`/`upsert`/`ingest` in remote mode scan locally as today, then push only slices whose hash differs (`wiki_page_hashes`), chunked ≤200 slices / ≤1 MiB per call; `--no-push` skips the push; a failed chunk is retried once and reported.
- [ ] AC11. `sync push|pull` in remote mode move memory-origin pages and asserted edges through `wiki_sync_push|pull` with last-write-wins; `ARANGODB_*` is not needed on the client.
- [ ] AC12. `wikitoolkit mcp` with `remote` configured forwards `tools/list`/`tools/call` to the server, adds `X-Wiki-Actor`, does not require `is_built()`, and returns JSON-RPC errors (never exits) on remote failure.
- [ ] AC13. `parrot claude install --remote` writes `{"type":"http","url":…,"headers":{"Authorization":"Bearer ${TOKEN_ENV}"}}` under key `wikitoolkit`; `parrot codex install --remote` writes `url` + `bearer_token_env_var`; both are idempotent, uninstall removes them, status reports `mcp_transport`.
- [ ] AC14. Without `remote`, `.mcp.json`, `.codex/config.toml`, the stdio server's tool list and every CLI command are byte-identical to `dev` before this feature (regression tests in §4).
- [ ] AC15. `pip install 'ai-parrot[wikitoolkit-server]'` pulls ai-parrot-server; `wikitoolkit serve` without it fails with the install hint; clients need no new dependency.
- [ ] AC16. `docs/guides/llm-wiki-remote.md` documents server.yaml, token handling, TLS-behind-proxy, **single-process deployment** (no multi-worker without sticky routing), the `remote` block, env override, pass-through vs native install, and the v1 limitations (ledger SQLite, refused commands, no Codex actor header, per-slice atomicity, structural tools per §8 Q5).
- [ ] AC17. All tests in §4 pass: `pytest packages/ai-parrot/tests/knowledge/wiki -k "remote or serve or bulk or actor or proxy" -v` (worktree: `PYTHONPATH=packages/ai-parrot/src`).
- [ ] AC18. `ruff check` clean on every touched file; no `requests`/`httpx`/`mcp` SDK import in runtime code.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.
> All anchors re-verified on 2026-09-17 against `dev` @ `ba578f928`.

### Verified Imports
```python
# core — packages/ai-parrot/src/parrot/
from parrot.knowledge.wiki.project import (                       # project.py
    WikiConfigError, WikiProjectConfig, WikiEnvOverlay, WikiEffectiveConfig, WikiNamespaceConfig,
    find_project_root, find_shared_root, load_effective_config, resolve_arango_params, resolve_vault_dir,
    sqlite_policy_from_config, validate_namespace_name, wiki_write_lock)
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, InMemoryWikiStore, WikiPageRecord, WikiStoreBusy, SQLitePragmaPolicy, create_wiki_store, register_wiki_backend
from parrot.knowledge.wiki.symbols import SymbolRecord, SymbolKind
from parrot.knowledge.wiki.tools import create_wiki_tools, VaultIngestTool, _scoped_store, _unknown_namespace_error
from parrot.knowledge.wiki.structural import create_structural_tools          # re-export of structural/tools.py:225
from parrot.knowledge.wiki.structural.service import StructuralService
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle, resolve_namespaces
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.sync import SyncError, SyncReport, default_local_identity, sync_push, sync_pull, _sync_records
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server, main
from parrot.knowledge.wiki.claude_code import assets as claude_assets, installer as claude_installer
from parrot.knowledge.wiki.codex import assets as codex_assets, installer as codex_installer
from parrot.mcp.server_base import MCPServerBase, LocalServerConfig, SUPPORTED_PROTOCOL_VERSIONS, negotiate_protocol_version   # parrot/mcp/__init__.py eager exports
from parrot.mcp.local_server import LocalMCPServerBase, StdioMCPServer
from parrot.mcp.adapter import MCPToolAdapter
from parrot.tools.abstract import AbstractTool, ToolResult
# ai-parrot-server — packages/ai-parrot-server/src/parrot/ (PEP 420 merge; import lazily, only in serve.py)
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer
from parrot.mcp.transports.base import RemoteMCPServerBase
from parrot.mcp.config import MCPServerConfig, AuthMethod, TransportConfig
from parrot.mcp.oauth_server import APIKeyStore, APIKeyRecord
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
_INVOCATION_CWD = os.getcwd()                                              # L44
def _ensure_stderr_logging() -> None                                        # L47
def _run_sync(coro: Any) -> Any                                             # L70
def create_wiki_mcp_server(root: Path) -> StdioMCPServer                    # L94  (store → resolve_namespaces → LedgerService.from_root if find_shared_root → ledger NamespaceHandle(read_only=True) → FederatedWikiStore → create_wiki_tools → create_structural_tools → vault → StdioMCPServer(LocalServerConfig(name="wikitoolkit", version="1.0.0")))
def main() -> None                                                          # ~L300 (requires config.is_built(root))

# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
class WikiQueryTool(AbstractTool)      # L191  name "wiki_query";  _execute(question, budget_tokens=DEFAULT_BUDGET_TOKENS, namespace=None, include_symbols=False) -> str  (L211-230, returns pack_results(...).text)
class WikiPageTool(AbstractTool)       # L233  "wiki_page";     _execute(page_id, namespace=None) -> ToolResult (L249)
class WikiRelatedTool(AbstractTool)    # L270  "wiki_related";  _execute(page_id, namespace=None) -> ToolResult (L286)
class WikiRememberTool(AbstractTool)   # L302  "wiki_remember"; __init__(store, storage_dir=None) L313; _execute L318-398; writes WikiPageRecord(origin="memory", asserted_by="agent:mcp") L340-352; WikiBookkeeper().log_operation(storage_dir,…) L383
class WikiNoteTool(AbstractTool)       # L401  "wiki_note";     __init__(store, storage_dir=None) L408
class WikiStatusTool(AbstractTool)     # L466  "wiki_status";   _execute() -> ToolResult(result=await store.stats()) L477-479
class VaultIngestTool(AbstractTool)    # L482
class LedgerOpenTool(AbstractTool)     # L626  "ledger_open";   _execute(title, body, kind="bug", severity="minor", discovered_from="", about=None) -> ToolResult; calls open_issue(..., actor="agent:mcp") L637-658
class LedgerReadyTool / LedgerClaimTool / LedgerCloseTool ("ledger_close") / LedgerContextTool ("ledger_context")   # L661-~740
def create_wiki_tools(store: BaseWikiStore, root: Path | None = None, config: WikiProjectConfig | None = None,
                      ledger_service: Union["LedgerService", None] = None) -> list[AbstractTool]              # L741-785

# packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py
class StructuralService:                                                    # L~110
    def __init__(self, store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> None   # L127 (self._sources = _open_sources(root, config, store=store) L131)
    async def lookup(self, query: str, *, kind: SymbolKind | None = None, ...)              # L136
    async def outline(self, target: str, ..., include_source: bool = ...)                    # L218 (calls _ensure_fresh([rel_path]) then store.symbols_for(rel_path))
    def _read_source_excerpt(self, sym_id: str, records: list[SymbolRecord]) -> tuple[str | None, bool]   # L258-285 (reads (root/rel_path).read_bytes(); OSError → (None, False))
    async def blast_radius(self, symbol: str, *, ...)                                        # L287
    def _disk_hash(self, rel_path: str) -> str | None                                        # L417
    async def _ensure_fresh(self, rel_paths: list[str]) -> list[str]                         # L425 (compares _disk_hash with store hashes; read-repair)
# packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py
def create_structural_tools(store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> list[AbstractTool]   # L225-263 (tool names: wiki_symbol_lookup L110, wiki_code_outline L150, wiki_blast_radius L185)

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class WikiPageRecord(BaseModel)       # L409-455: concept_id, node_id, title, category="concept", summary, body, source_id, token_count, origin="ingest", asserted_by, updated_at, content_hash
class BaseWikiStore(ABC)              # L525-818
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int                                     # L544
    async def add_edges(self, edges: list[tuple]) -> int                                                  # L547
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]   # L550-555
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]     # L565
    async def list_pages(...)                                                                             # L568
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]   # L576
    async def neighbors(...)                                                                              # L582
    async def stats(self) -> dict[str, Any]                                                               # L596
    async def upsert_symbols(self, symbols: list[SymbolRecord], source_id: Optional[str] = None, ...)    # L687-705
    async def symbols_for(self, rel_path: str) -> list[SymbolRecord]                                      # L707
    async def find_symbols(...)                                                                           # L734
    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]                      # L803
class SQLiteWikiStore(BaseWikiStore)  # L821 (__init__ L869)
def create_wiki_store(storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs: Any) -> BaseWikiStore   # L2247-2326
def register_wiki_backend(...)        # L511-522
class WikiStoreBusy(...)              # L264-286
# packages/ai-parrot/src/parrot/knowledge/wiki/symbols.py
class SymbolRecord(BaseModel)         # L56: rel_path, language, kind, name, qualname, parent, signature, doc, exported, is_async, start_line, end_line, start_byte, end_byte, node_kind, decorators, content_hash, depth
# packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py
class ArangoDBWikiStore(BaseWikiStore)  # L135; __init__(arango_params, database, wiki_name, text_analyzer, read_only) L170

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def wiki_write_lock(...)                                                    # L71-131 (exclusive writer lock)
def validate_namespace_name(name: str) -> ...                               # L147-178
class WikiNamespaceConfig(BaseModel)                                        # L181-277 (path | store(+backend) | database(+credentials_env) | vault; description, weight, overlay_prefixes)
class WikiProjectConfig(BaseModel)                                          # L379-543: wiki_name, storage_dir, backend: Literal["sqlite","memory","arangodb"], arango_database, arango_credentials_env, arango_text_analyzer, namespaces, sqlite_busy_timeout, sqlite_performance_pragmas; ledger_path(root) L507; storage_path(root) L519; is_built(root) L528
def resolve_arango_params(config) -> dict[str, Any]                         # L605-635
def sqlite_policy_from_config(config) -> SQLitePragmaPolicy                 # L682-701
def find_project_root(start: Path) -> Path | None                           # L709-729
class WikiConfigError(Exception)                                            # L732
class WikiEnvOverlay(BaseModel)                                             # L780-839
class WikiEffectiveConfig(BaseModel): config; env; overlay_path             # ~L842-859
def resolve_wiki_env(env: str | None = None) -> str                         # ~L861 (explicit > WIKI_ENV > ENV > "local")
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig   # L897-951
def find_shared_root(start: Path | None = None) -> Path | None              # L1184

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
class LedgerService:                                                        # L96-384
    def __init__(self, index: LedgerIndex, store: LedgerStore, log: LedgerLog, shared_root: Path) -> None   # L99
    @classmethod def from_root(cls, root: Path | None = None) -> "LedgerService"   # L114-141 (LedgerStore(ledger_dir/"ledger.db", wiki_name="ledger", sqlite_policy=...), LedgerLog(str(ledger_dir/"events.jsonl")), LedgerIndex(store, log))
    async def open_issue(...) L166 · ready_work(kind=None) L199 · claim(issue_id, actor) -> bool L209 · acknowledge(issue_id, reason, actor) L213 · close_issue(issue_id, reason, actor) -> bool L235 · get_context(file_paths, max_tokens=3000) -> str L247 · merge_blockers(feature_id) L280 · _feature_task_ids L311 · export_snapshot L325 · compact L353 · audit L357
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py
class LedgerStore(SQLiteWikiStore)   # L24-123; __init__(db_path, wiki_name="", *, read_only=False, sqlite_policy=None, persistent_writer=False)

# packages/ai-parrot/src/parrot/knowledge/wiki/sync.py
class SyncError(Exception) L50 · class SyncReport L59-83 · def default_local_identity() -> str L86
def _open_plane(root, config) -> BaseWikiStore L91 · async def _open_remote(root, target_env) -> tuple[BaseWikiStore, WikiProjectConfig] L117-134
async def _sync_records(*, source: BaseWikiStore, destination: BaseWikiStore, direction: Literal["push","pull"], env: str, dry_run: bool, skip_asserted_by: str | None) -> tuple[SyncReport, set[str]]   # L221-269
async def sync_push(root: Path, *, target_env: str = "dev", dry_run: bool = False, local_identity: str | None = None) -> SyncReport   # L293-333
async def sync_pull(...)                                                    # L336-380

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py   (click group `wiki` L1328; main() L4952)
def _resolve_project(path) -> tuple[Path, WikiProjectConfig] L350 · def _resolve_project_effective(path) -> tuple[Path, WikiEffectiveConfig] L375-389 · def _require_built(root, config) L391 · def _open_store(root, config) -> BaseWikiStore L398-433
def _open_sources(root, config, store=None) -> SourceCollectionManager L455-481 · def _run(coro) L494 · def _resolve_read_store(path_, store_opt, backend_opt, ns_opt) L517 · def _store_options(func) L588 · def _render_results_table(rows, question, show_body) L607
mcp() L1349-1362 · build L1401 · upsert L1670 · query L1824 (store.search_fts → _render_results_table) · page L1895 · related L1943 · status L2017 · symbols group L2195 (lookup L2208, outline L2230, blast L2266) · ns group L2397
ledger group L2638 (open L2650, ready L2679, claim L2696, acknowledge L2715, close L2730, context L2747, blockers L2759, export L2775, sync L2787, rebuild L2802, ingest-sdd L2828, compact L2848, audit L2860)
communities L2893 · export L2994 · def _authoring_identity(by: str | None) -> str L3027-3049 (--by > CLAUDE_AGENT_ID/PARROT_AGENT_ID → "agent:<id>" > "human:<getuser>") · _resolve_write_store L3060
remember L3320 · note L3460 · link L3531 · memories L3588 · audit L3618 · ground L3671 · sync group L3740 (push L3762, pull L3805, obsidian L3869) · ingest L4292 · ingest-jira L4744 · claude-hook L4938 · _register_agent_command L4966

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
PERMISSION_RULES (mcp__wikitoolkit__wiki_symbol_lookup / wiki_code_outline / wiki_blast_radius) L52-63 · MCP_JSON_ENTRY = {"command": "wikitoolkit", "args": ["mcp"], "env": {}} L71-75 · def resolve_wikitoolkit_bin(root) -> str L83 · def hook_command(root) L104 · def mcp_json_entry(root) -> dict L108-116 · def resolve_parrot_bin(root) L118
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
_managed_server_names(root) L304 · _install_mcp_approval(root) L340 · _is_managed_toolkit_entry(entry, root, name) L420-461 · _install_mcp_json(root) -> str L462-551 · _uninstall_mcp_json(root) L552 · install_claude_integration(root, config=None, git_hook=True, gitignore=True, bookstore=True, toolkits=(), approve_mcp=True) -> list[str] L770 · uninstall_claude_integration(root) L855 · integration_status(root) -> dict L985
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py   `parrot claude` group L50; install(path_, git_hook, gitignore, build_now, bookstore, tool_guards, toolkits_, all_toolkits, approve_mcp) L107; uninstall L184; status L205
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py   MCP_TABLE = "mcp_servers.wikitoolkit" L19 · def resolve_binary(root, name) -> str L52 · def mcp_block(root, toolkit_block="") -> str L93-116 (lines: [mcp_servers.wikitoolkit] / command = … / args = ["mcp"] / default_tools_approval_mode = "approve")
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py   _install_mcp(root) -> str L110-168 · install_codex_integration(root, config=None, gitignore=True, bookstore=True, toolkits=()) L202
# packages/ai-parrot/src/parrot/knowledge/wiki/coding_agents.py   install(agent, root=Path.cwd()) -> list[str] L123 (hooks/skill/instruction blocks ONLY — not .mcp.json)

# packages/ai-parrot/src/parrot/mcp/server_base.py (core)
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18") L17 · def negotiate_protocol_version(requested) L28 · @dataclass LocalServerConfig(name, version, description, log_level) L48
class MCPServerBase(ABC) L57: register_tool / register_tools / handle_initialize(params) / handle_tools_list(params) / handle_tools_call(params); abstract start/stop
# packages/ai-parrot/src/parrot/mcp/local_server.py (core)   class LocalMCPServerBase L18 · class StdioMCPServer L36 (start(): stdin lines; _handle_request: initialize / tools/list / tools/call / notifications/initialized)
# packages/ai-parrot/src/parrot/mcp/adapter.py (core)         class MCPToolAdapter L8-148: to_mcp_tool_definition() L27; async execute(arguments) -> dict L59
# packages/ai-parrot/src/parrot/mcp/__init__.py (core)        eager: MCPToolAdapter, MCPResource, MCPServerBase, LocalServerConfig, LocalMCPServerBase, StdioMCPServer; lazy __getattr__ for MCPClient/MCPServerConfig/… (navconfig side effects — do NOT import at module level in wikitoolkit code)

# packages/ai-parrot-server/src/parrot/mcp/config.py
class AuthMethod(str, Enum): NONE, API_KEY, OAUTH2_INTERNAL, OAUTH2_EXTERNAL, BEARER (navigator-auth session)   # L9-16
@dataclass class MCPServerConfig L131-226: name, version, description, transport="stdio" ("streamable-http" accepted), host="localhost", port=8080, allowed_tools, blocked_tools, log_level, auth_method=AuthMethod.NONE, api_key_header="X-API-Key", api_key_store: Optional[Any], base_path="/mcp", allowed_origins, allow_any_origin=False, session_ttl=3600, event_buffer_size=1000, max_sessions=1000, max_streams_per_session=64, ssl_cert_path, ssl_key_path, http_use_tls
# packages/ai-parrot-server/src/parrot/mcp/transports/base.py
class RemoteMCPServerBase(_CoreMCPServerBase) L19: __init__(config: MCPServerConfig) L27 (self.api_key_store = config.api_key_store or APIKeyStore() when API_KEY, L134); async _authenticate_request(request) -> web.Response | None L174; async _authenticate_api_key(request) L~199 (header = config.api_key_header; record = api_key_store.validate_key(api_key); api_key_store.log_session_start(api_key, record.user_id, time.time()); request["mcp_user"] = {"user_id": record.user_id, "scopes": record.scopes}); _extract_bearer_token L274; _unauthorized_response L304
# packages/ai-parrot-server/src/parrot/mcp/transports/http.py
class HttpMCPServer(RemoteMCPServerBase): __init__(config, parent_app: Optional[web.Application] = None) L25-36; start() L38-92 (parent_app → routes on parent router at base_path; standalone → own AppRunner/TCPSite with ssl from ssl_cert_path/ssl_key_path); _register_routes(router, base_route) L94; _handle_http_request L112 (calls _authenticate_request)
class HttpMCPSession L203-610 (client): _read_sse_response L473-530
# packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py
class StreamableHttpMCPServer(HttpMCPServer) L250-1125: __init__(config, parent_app=None, session_store=None) L259; _register_routes → POST/GET/DELETE base_route + GET base_route/info L284-289; start() L291 (super().start() + prune loop); stop() L297; _handle_info L309; _principal(request) L325-349 (request["mcp_user"] ids, else credential digest); _handle_streamable_post L629 (Accept negotiation; initialize must not be batched; _authenticate_request at L~581 helper; session via Mcp-Session-Id)
# packages/ai-parrot-server/src/parrot/mcp/oauth_server.py
@dataclass class APIKeyRecord(key, user_id, created_at, expires_at=None, scopes=[], description="") L75 · class APIKeyStore L86: issue_key(...) ; validate_key(key) -> Optional[APIKeyRecord] L156 ; log_session_start(key, user_id, timestamp) -> None L194
# packages/ai-parrot-server/src/parrot/mcp/parrot_server.py   class ParrotMCPServer L41; _check_base_path_conflicts() L121-147 (distinct base paths per HTTP-like transport on one app)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `build_wiki_tools()` | `create_wiki_tools()`, `create_structural_tools()`, `resolve_namespaces()`, `LedgerService.from_root/from_dir` | extracted body of `create_wiki_mcp_server` | `mcp_server.py:94-~270` |
| `current_actor()` | `WikiRememberTool._execute`, `LedgerOpenTool._execute` (+ note/claim/close) | replaces `"agent:mcp"` literals | `tools.py:352`, `tools.py:654` |
| `StaticBearerKeyStore` | `RemoteMCPServerBase._authenticate_api_key` | `config.api_key_store.validate_key()` | `transports/base.py:~199-215` |
| `WikiHttp mount` | `StreamableHttpMCPServer(config, parent_app=app)` | one per wiki, `base_path=f"/mcp/{name}"` | `streamable_http.py:259`, `http.py:38-92` |
| `actor_middleware` | `StreamableHttpMCPServer._principal` (via `request["mcp_user"]` set by auth) and tools via ContextVar | aiohttp middleware on parent app | `streamable_http.py:325-349` |
| `RemoteWikiClient` | server `/mcp/<wiki>` | aiohttp POST JSON-RPC, `Mcp-Session-Id` | protocol constants `server_base.py:17` |
| `ProxyStdioMCPServer` | `StdioMCPServer.handle_tools_list/handle_tools_call` | override → `RemoteWikiClient` | `local_server.py:36`, `server_base.py:~95-110` |
| `push_slices()` | `wiki_page_hashes` / `wiki_ingest_batch` tools → `BaseWikiStore.replace_source_slice` + `upsert_symbols` | MCP `tools/call` | `store.py:550-555`, `store.py:687-705`, `store.py:803` |
| `wiki_sync_push/pull` | `_sync_records()` | in-memory source/destination store | `sync.py:221-269` |
| `mcp_json_entry_remote()` | `_install_mcp_json` reconciliation of key `wikitoolkit` | new entry shape | `installer.py:462-551` |
| `mcp_block(remote=)` | `_install_mcp` managed marker block | new TOML lines | `codex/installer.py:110-168`, `codex/assets.py:93-116` |
| `serve` command | `wiki` click group | `@wiki.command()` | `cli.py:1328` |
| `wikitoolkit-server` extra | `[project.optional-dependencies]` | precedent `server = ["ai-parrot-server[all]"]` | `packages/ai-parrot/pyproject.toml:357-359` |

### Does NOT Exist (Anti-Hallucination)
- ~~`wikitoolkit serve`~~, ~~`parrot/knowledge/wiki/serve.py`~~, ~~`remote.py`~~, ~~`remote_cli.py`~~, ~~`actor.py`~~ — all new in this feature.
- ~~`WikiProjectConfig.remote`~~ / ~~`WikiRemoteConfig`~~ / ~~`resolve_remote`~~ / ~~`WIKITOOLKIT_REMOTE_URL`~~ / ~~`WIKITOOLKIT_TOKEN`~~ / ~~`WIKITOOLKIT_SERVER_TOKEN`~~ — none defined today.
- ~~`backend: "remote"`~~ / ~~`RemoteWikiStore`~~ — `backend` is `Literal["sqlite", "memory", "arangodb"]` (`project.py:415`); this feature adds no backend.
- ~~`WikiNamespaceConfig.url`~~ — kinds are `path` / `store` / `database` / `vault` only.
- ~~A Streamable HTTP **client** in core~~ — `MCPClient._detect_transport()` (`parrot/mcp/integration.py:~333`) knows `stdio|http|sse|unix|websocket|quic`; `HttpMCPSession` lives in ai-parrot-server. M3 writes its own.
- ~~`StreamableHttpMCPServer` in core~~ — ai-parrot-server only; core has `StdioMCPServer`.
- ~~Static-token bearer auth in `MCPServerConfig`~~ — `AuthMethod.BEARER` is navigator-auth session auth; `API_KEY` needs an `api_key_store` (`APIKeyStore`, `oauth_server.py:86`). This feature subclasses it.
- ~~`X-Wiki-Actor` / actor ContextVar~~ — MCP tools hardcode `"agent:mcp"` (`tools.py:352`, `tools.py:654`); the CLI uses `_authoring_identity()` locally.
- ~~MCP tools `wiki_link`, `wiki_memories`, `wiki_audit`, `wiki_ground`, `wiki_export`, `wiki_communities`~~ and ~~`ledger_acknowledge`, `ledger_blockers`, `ledger_export`, `ledger_audit`, `ledger_sync`, `ledger_rebuild`, `ledger_compact`, `ledger_ingest_sdd`~~ — CLI-only; out of scope (separate spec).
- ~~`wiki_page_hashes`, `wiki_ingest_batch`, `wiki_sync_push`, `wiki_sync_pull`~~ — new in M5.
- ~~`LedgerStore` on ArangoDB~~ — SQLite-only (`ledger/store.py:24`); follow-up feature.
- ~~`LedgerService.from_dir`~~ — only `from_root()` and the collaborator `__init__` exist (`service.py:99-141`); M2 adds it.
- ~~`StructuralService(read_repair=...)`~~ / ~~`create_structural_tools(..., read_repair=...)`~~ — no such flag today (`service.py:127`, `structural/tools.py:225`); M2 adds it.
- ~~`build_wiki_tools` / `WikiToolBundle` / `create_proxy_mcp_server` / `ProxyStdioMCPServer`~~ — new in M2/M6.
- ~~`wikitoolkit claude install` writing `.mcp.json`~~ — `coding_agents.install` writes hooks/skill/instruction blocks only; `.mcp.json` and `.codex/config.toml` are written by `parrot claude install` / `parrot codex install`.
- ~~`--remote` on any installer~~, ~~`mcp_json_entry_remote`~~, ~~`integration_status()["mcp_transport"]`~~ — new in M7.
- ~~`wikitoolkit --version`~~ — not an option (`-v/--verbose` only).
- ~~`MCPServerConfig` in core~~ — `parrot.mcp.__init__` resolves it lazily from `.integration`; the server-side dataclass is `parrot/mcp/config.py` in ai-parrot-server (import lazily inside `serve.py`).
- ~~Codex `http_headers` config key~~ — not documented; Codex native HTTP cannot send `X-Wiki-Actor`.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **Lazy imports for anything server-side or navconfig-tainted.** `mcp_server.py` already defers `parrot.mcp.local_server` under `contextlib.redirect_stdout(sys.stderr)` (L~105) because `parrot.mcp` transitively pulls navconfig; `serve.py` must import `parrot.mcp.transports.streamable_http` / `parrot.mcp.config` / `parrot.mcp.oauth_server` inside functions and map `ImportError` to the install hint (AC15).
- **stdout is the JSON-RPC channel** in every stdio path: the pass-through server logs to stderr via the existing `_ensure_stderr_logging()`.
- **Env-overlay discipline**: read the `remote` block only through `load_effective_config()` (never `load_project_config`) — the repo-wide call-site guard `test_env_call_sites.py` enforces this.
- **Config resolution precedence** for remote mode: `WIKITOOLKIT_REMOTE_URL` > overlay `wiki.<env>.json` > base `wiki.json` > none; `--store`/`--backend` with a resolved remote is a usage error, never a silent override.
- **One tool call = one `AbstractTool`**: the four bulk tools are `AbstractTool`s registered through `MCPToolAdapter` like every other tool; no bespoke HTTP routes.
- **Writes under the writer lock**: `wiki_ingest_batch` wraps its slices in `wiki_write_lock` exactly as `build`/`upsert` do; `WikiStoreBusy` surfaces as a `ToolResult(success=False, error=...)` the client maps to `tool_error` and retries once.
- **Identity**: `current_actor()` defaults to `"agent:mcp"` so the local stdio server's attribution is unchanged (AC14); the HTTP middleware and the CLI proxy are the only setters.
- **Installer reconciliation** keeps touching only the `wikitoolkit` key and managed `parrot-<name>` keys; the remote shape is detected by `_is_wikitoolkit_entry()` so uninstall/upgrade never strips a foreign entry.
- **Server test double**: `WikiServerConfig.allow_sqlite_for_tests: bool = False` lets the e2e tests serve SQLite planes; production refuses non-ArangoDB backends (AC1).
- Tests for worktrees: `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/wiki/...` (shared venv is editable-installed against the main checkout).

### Known Risks / Gotchas
- **No source tree on the server** → `wiki_code_outline(include_source=True)` cannot return excerpts and read-repair must be off; documented, covered by AC5. Pages carry their `body` in the DB (`WikiPageRecord.body`, store.py:409), so `wiki_page` is unaffected.
- **No git root on the server** → `LedgerService.merge_blockers()` cannot read per-spec indexes and returns `[]`; `/sdd-done`'s merge gate keeps running locally against the shared checkout, not against the remote. Documented in AC16.
- **ContextVar propagation**: `StreamableHttpMCPServer` dispatches tool calls in tracked tasks (`_track`, streamable_http.py:519); `asyncio.create_task` copies the current context, so the actor set by the middleware reaches the tool. The e2e attribution test (AC4) guards this; if a future transport change breaks propagation, fall back to reading `request["wiki_actor"]` in a tools/call hook.
- **Shared static token** binds every client to the same credential digest in `_principal()`; sessions are still per `Mcp-Session-Id`, so this only weakens session-ownership enforcement, not isolation of data. Per-user tokens are a later feature.
- **Bulk payload size**: `WikiPageRecord.body` can be up to `body_max_chars` (32 000 in this repo); 200 slices could exceed 1 MiB — the client chunks by *both* limits and never sends a single slice larger than 1 MiB (such a slice is reported as `rejected`).
- **Session expiry**: idle sessions expire after `session_ttl`; the client re-initialises once on a 404-with-session, then fails closed.
- **Codex native HTTP** cannot send `X-Wiki-Actor`; the pass-through is the recommended Codex path and `default_actor` covers the rest.
- **Ledger `acknowledge` is human-only** (`service.py:213`) and stays CLI-only; a remote actor cannot acknowledge in v1.
- **`.mcp.json` `${VAR}` expansion in headers** is confirmed at config level for Claude Code 2.1.274; M7's smoke test must assert the expanded header reaches the fake server before shipping the native install path.
- **Dual identity of `MCPServerConfig`**: core's lazy `parrot.mcp.MCPServerConfig` (client-side, `integration.py`) and ai-parrot-server's `parrot.mcp.config.MCPServerConfig` (server-side dataclass) share a name; `serve.py` must import the latter by module path.
- **Origin validation** is mandatory for browser callers; CLI/agent callers send no `Origin`, so defaults are safe. `allowed_origins` stays configurable.
- **Structural plane on ArangoDB (design research S8)**: `ArangoDBWikiStore` implements `replace_source_slice` (arango_store.py:599) but none of `upsert_symbols` / `symbols_for` / `find_symbols` / `search_symbols_fts`, so the `BaseWikiStore` defaults apply (no-op / empty). On an ArangoDB-backed wiki the three structural tools return empty results and pushed symbols are dropped (`symbols_dropped` in the ingest report). Decision pending in §8 Q5; until then AC5 is asserted against the SQLite test double only.
- **Single-process sessions (S6)**: `InMemorySessionStore` is per process; a second worker would not know the first worker's `Mcp-Session-Id`. v1 runs one process; HA is §8 Q3.
- **Cross-slice atomicity (S8)**: a batch of N slices is N per-slice replacements; a crash mid-batch leaves earlier slices applied. The client's hash oracle makes re-running the push converge; staging-and-swap is §8 Q4.
- **Store lifecycle (S2)**: never call `build_wiki_tools()` (sync, `_run_sync`) from inside the aiohttp app — use `abuild_wiki_tools()` so ArangoDB sessions are created on the serving loop and closed in `on_cleanup`.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiohttp` | existing core pin | server app (via ai-parrot-server) and the core client |
| `pydantic` | `>=2` (existing) | config, payload models |
| `click` | existing | `serve`, installer flags |
| `pyyaml` | existing (core) | `server.yaml` |
| `ai-parrot-server` | workspace version | `StreamableHttpMCPServer`, `MCPServerConfig`, `APIKeyStore` — server host only, via new extra `ai-parrot[wikitoolkit-server]` |
| `mcp` | `>=1.28.1,<2` (optional, tests only) | interop test with the official client; skipped when absent |

### Worktree Strategy

- **Isolation**: one feature worktree for FEAT-569 (`.claude/worktrees/feat-FEAT-569-wikitoolkit-http-mcp`, from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edge = imports/needs):
  - M2 → (none). M1 → (none). They may run concurrently.
  - M3 → M1 (`WikiRemoteConfig`).
  - M5 → M2 (`current_actor`, `build_wiki_tools(include_bulk_tools=)` registration).
  - M4 → M2, M5 (registers the bulk tools; `read_repair=False`, `from_dir`).
  - M6 → M1, M3, M5 (payload models for `push_slices`), M2 (`create_proxy_mcp_server` lives in `mcp_server.py`).
  - M7 → M1 (reads `config.remote`); otherwise independent of M3–M6.
  - M8 → all.
  Expected concurrency: {M1, M2} → {M3, M5, M7} → {M4, M6} → M8.
- **Shared files** (tasks touching them are serialized): `parrot/knowledge/wiki/cli.py` (M4 `serve`, M6 proxies/refusals/push), `parrot/knowledge/wiki/mcp_server.py` (M2 builder, M6 pass-through), `parrot/knowledge/wiki/tools.py` (M2 actor substitution, M5 bulk tools), `parrot/knowledge/wiki/project.py` (M1 only — M2 does not edit it).
- **Exclusive resources**: `packages/ai-parrot/pyproject.toml` (M4 extra) — `parallel: false`; no extension rebuilds or migrations.
- **Cross-feature dependencies**: none open on `dev` (FEAT-557, FEAT-566 completed). The separate "CLI commands as MCP tools" spec and `wikitoolkit-ledger-arangodb` depend on *this* feature's `build_wiki_tools()` and `LedgerService.from_dir()` seams, not the reverse.

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] Feature or hotfix; base branch? — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Where does the remote server run? — *Resolved in brainstorm*: standalone `wikitoolkit serve` (aiohttp); not mounted in the ai-parrot server app for v1. → §2 Overview, M4.
- [x] Authentication? — *Resolved in brainstorm*: static bearer token from an env var; OAuth2 out of scope. → M4 `StaticBearerKeyStore`, AC2.
- [x] How do build results reach the server? — *Resolved in brainstorm*: build locally into SQLite, push the delta through MCP bulk tools; server never scans repos. → M5, M6 `push_slices`, AC10.
- [x] One wiki per server or many? — *Resolved in brainstorm*: multi-wiki by path, `/mcp/<wiki_name>`. → M4, AC1/AC3.
- [x] Write attribution with a shared token? — *Resolved in brainstorm*: client sends `X-Wiki-Actor: human:<local-user>`; trusted for the internal team. → M2 `actor.py`, M4 middleware, AC4.
- [x] Local vs remote selection and failure behaviour? — *Resolved in brainstorm*: `remote` block in `wiki.json` (env-overlayable) + `WIKITOOLKIT_REMOTE_URL` override; fail-closed, no silent local fallback. → M1, M6, AC7/AC8.
- [x] Ledger storage on the server — *Resolved in brainstorm*: v1 keeps `LedgerStore` as SQLite on the server host; ArangoDB port is the follow-up feature `wikitoolkit-ledger-arangodb`; this feature keeps `LedgerService` construction backend-agnostic (`from_dir`). → §1 Non-Goals, M2.
- [x] CLI-only commands in remote mode — *Resolved in brainstorm*: out of scope; refused in v1; exposing them as MCP tools belongs to a separate spec (not yet under `sdd/specs/`; link from here when it lands). → §1 Non-Goals, M6 refusal list, AC9.
- [x] Stdio pass-through as the intermediate install path — *Resolved in brainstorm*: yes; `wikitoolkit mcp` forwards to the remote whenever `remote` is configured, no installer change required; recommended for Codex. → M6 `ProxyStdioMCPServer`, AC12.
- [x] Exact Claude Code / Codex remote-MCP config keys — *Resolved in brainstorm*: Claude `.mcp.json` `{"type":"http","url":…,"headers":{"Authorization":"Bearer ${WIKITOOLKIT_TOKEN}"}}` (2.1.274, `${VAR}` at config level); Codex `[mcp_servers.wikitoolkit] url = … bearer_token_env_var = …`, no header key. → M7, AC13.
- [x] Server packaging — *Resolved in spec*: new optional extra `ai-parrot[wikitoolkit-server] = ["ai-parrot-server"]` following the `server = ["ai-parrot-server[all]"]` precedent; `serve` lazy-imports and fails with an install hint. → M4, AC15.
- [x] Token-gate implementation — *Resolved in spec*: `AuthMethod.API_KEY` + `api_key_header="Authorization"` + `StaticBearerKeyStore(APIKeyStore)`, reusing `_authenticate_api_key()`; actor via a separate aiohttp middleware. → M4.
- [x] Bulk-ingest limits — *Resolved in spec*: ≤200 slices and ≤1 MiB JSON per `wiki_ingest_batch`; ≤2000 ids per `wiki_page_hashes`; embeddings neither pushed nor recomputed (no vector search remotely in v1). → §2 Data Models, M5, AC10.
- [x] `ns list` in remote mode — *Resolved in spec*: refused like the other namespace commands; `wikitoolkit status` in remote mode prints `mode: remote (<url>)` plus the server's `wiki_status` stats, which is where server-side namespaces show up. → M6.
- [x] Default actor when `X-Wiki-Actor` is absent — *Resolved in spec*: `WikiServerConfig.default_actor = "agent:unknown"`; malformed header → 400; reads unaffected. → M4, AC4.
- [x] TLS termination — *Resolved in spec*: plain HTTP behind a reverse proxy by default; `--ssl-cert/--ssl-key` pass through to `MCPServerConfig.ssl_cert_path/ssl_key_path` (already honoured by `HttpMCPServer.start`). → M4, AC16.
- [ ] Target version — *Owner: release maintainer*: `next minor after 0.29.x`; pick the concrete release when scheduling. Does not block decomposition.
- [x] Should `wiki_sync_pull` be paginated? — *Resolved after design research (S9)*: yes — `since` + `limit` (default 500) + opaque `cursor` (`updated_at,concept_id`); tombstones stay out of scope like the existing sync engine. → M5.
- [ ] Q3. HA / multi-worker: should `WikiServerConfig` accept `session_store_url: redis://…` to use `RedisSessionStore` (session_store.py:282), or is single-process + reverse-proxy sticky routing enough for v1? — *Owner: ops* (raised by S6)
- [ ] Q4. Cross-slice atomicity for `wiki_ingest_batch` on ArangoDB: accept per-slice atomicity (today's `replace_source_slice` semantics) or add staging-and-swap? — *Owner: Jesus* (raised by S8)
- [ ] Q5. **Structural plane on ArangoDB**: `ArangoDBWikiStore` has no `upsert_symbols`/`symbols_for`/`find_symbols`, so `wiki_symbol_lookup|code_outline|blast_radius` return empty on ArangoDB-backed wikis and pushed symbols are dropped. Implement the symbol tables for ArangoDB inside this feature (new module, ~M5b), or ship v1 with structural tools documented as SQLite-only and open a follow-up? — *Owner: Jesus* (raised by S8; blocks AC5 for ArangoDB wikis)

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.154.0, reasoning high) ·
> Status: completed (attempt 2, 590 s; attempt 1 timed out at 470 s — both logs kept)
> · Transcript: `sdd/state/FEAT-569/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make structural reads snapshot-backed on the server — rootless mode, no read-repair, no source reads (architecture) | CONFIRM | Verified: `StructuralService._ensure_fresh`/`_read_source_excerpt` hash and read files under `root` (service.py:258-285, 417-471). Already the M2 `read_repair=False` design; the reviewer's "document the resulting tool behavior" is AC5/AC16. | M2, AC5, §7 Risks |
| S2 | Async server runtime with explicit store ownership — initialise/close stores inside the aiohttp lifecycle, not via transient loops (architecture) | CONFIRM | Verified: `create_wiki_mcp_server` resolves namespaces through `_run_sync` (mcp_server.py:70-92) and `_open_arango` closes the probe connection for lazy re-open (federation.py:306-357); a long-lived process must own `initialize()`/`close()`. Added `abuild_wiki_tools()` (async, no transient loops) and `on_startup`/`on_cleanup` store ownership in `build_server_app`. | M2, M4 |
| S3 | Define static bearer auth independently of API-key auth; protect every endpoint; fail closed on missing token (risk) | REJECT | path not found: `packages/ai-parrot-server/src/parrot/mcp/server_base.py` (the file is core `parrot/mcp/server_base.py`). Substance is already covered independently: `StaticBearerKeyStore` with `hmac.compare_digest`, `api_key_header="Authorization"`, `_authenticate_request` runs on POST/GET/DELETE (streamable_http.py:581), missing token → exit 1 (M4, AC2). `/info` protection added as AC2 wording. | — (see M4/AC2) |
| S4 | Separate authenticated principal from `X-Wiki-Actor`; treat header as advisory; set/reset ContextVar per dispatch (risk) | REJECT | path not found: `packages/ai-parrot-server/src/parrot/mcp/server_base.py`. The impersonation concern is nonetheless real and was a brainstorm decision ("trusted from the client, internal team"); the spec already records both identities (`mcp_user.user_id` = token digest via `_principal`, actor via ContextVar set per request by the middleware, reset on exit through `actor_scope`). Per-user tokens stay a later feature. | — (see M4, §7 Risks) |
| S5 | Extend `HttpMCPSession` instead of a second client; do not replay non-idempotent calls after session expiry (api) | CONFIRM (partial) | REJECT the "extend `HttpMCPSession`" half: it lives in ai-parrot-server (transports/http.py:203) and clients must stay core-only (brainstorm constraint). CONFIRM the replay half: M3 now re-initialises and retries **only read-only tools**; writes surface `RemoteWikiError(code="session_expired")`. | M3, AC8 |
| S6 | Make multi-worker session storage an explicit deployment contract (architecture) | CONFIRM + ESCALATE | Verified: `InMemorySessionStore` default; `RedisSessionStore` exists (session_store.py:217, 282). v1 `wikitoolkit serve` is a **single process** (own `TCPSite`, no gunicorn workers) — documented in M4/AC16 and guarded by refusing any `--workers`-style option. Whether to wire `RedisSessionStore` for HA is escalated. | M4, §7 Risks, §8 Q3 |
| S7 | Rootless per-wiki server config: explicit name → backend/db/ledger/namespaces; validate names and duplicate routes (api) | CONFIRM | Already the `WikiServerEntry`/`WikiServerConfig` + `LedgerService.from_dir` design; added normalised duplicate-route check and URL-safe name validation to `WikiServerConfig`. | M4 |
| S8 | Source-slice manifests + atomic bulk-ingest commit; deletions; idempotency; symbols no-op on some backends (architecture) | CONFIRM (partial) + ESCALATE | Verified: `ArangoDBWikiStore.replace_source_slice` exists (arango_store.py:599) but the store has **no** `upsert_symbols`/`symbols_for`/`find_symbols` override, so the `BaseWikiStore` default no-op applies (store.py:687-705) — structural tools are inert on ArangoDB-backed wikis. Added `deleted_source_ids` and `batch_id` to `wiki_ingest_batch`; per-slice atomicity relies on `replace_source_slice` (documented as backend-defined). Cross-slice staging-and-swap and the ArangoDB symbol plane are escalated. | M5, §7 Risks, §8 Q4/Q5 |
| S9 | Treat sync push/pull as a versioned exchange protocol (cursor, tombstones) or defer it (alternative) | CONFIRM (partial) | Verified: `sync.py` is LWW with no deletion exchange ("deletes are never propagated (v1 limitation, documented)", sync.py:~9). Added `limit`/`cursor` pagination to `wiki_sync_pull`; tombstones REJECTED as out of scope (matches the existing engine); deferral REJECTED — brainstorm requires `sync` without client-side ArangoDB. | M5, §8 Q2 |
| S10 | Resolve remote mode before every local store/build gate; reject local-only flags deterministically (api) | CONFIRM | Verified: commands call `_resolve_read_store`/`_require_built` early (cli.py:391, 517). M6 now mandates a `@remote_aware` decorator that resolves the remote and rejects `--store/--backend` **before** any store open or `is_built()` check. | M6, AC7/AC9 |
| S11 | Freeze command→tool schemas with golden/contract tests; versioned capability manifest (testing) | CONFIRM (partial) | Golden tool-surface tests per mode and interop test added to §4; a versioned capability manifest is REJECTED for v1 (`/info` + `tools/list` suffice; the brainstorm promises "same text as agents see", not byte-identical local rendering — AC7 wording fixed). | §4, AC7 |
| S12 | Keep the server dependency an optional lane; installers emit HTTP only when configured, never clobber foreign entries (architecture) | CONFIRM | Already landed: extra `wikitoolkit-server`, lazy import with install hint, `_is_wikitoolkit_entry` shape detection, Codex header limitation documented. | M4, M7, AC13/AC15 |

Summary: **9** confirmed (4 partial) · **2** rejected (unverifiable path) · **3** escalated (§8 Q3–Q5, raised from S6 and S8).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-17 | Jesus Lara (with Claude) | Initial draft from accepted brainstorm (Option A); FEAT-569 reserved (ledger drift past hand-assigned FEAT-566..568 repaired in the same reservation) |
| 0.2 | 2026-09-18 | Jesus Lara (with Claude) | Design research (codex gpt-5.6-luna) triaged: 9 confirmed / 2 rejected / 3 escalated; added async store lifecycle, read-only-only session retry, ingest deletions + batch_id, sync pagination, `remote_aware` decorator, ArangoDB symbol-plane gap (§8 Q5) |
