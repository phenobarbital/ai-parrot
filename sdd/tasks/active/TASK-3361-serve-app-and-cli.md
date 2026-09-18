# TASK-3361: `serve.py` part B — `build_server_app` / `run_server`, `wikitoolkit serve` command, `wikitoolkit-server` extra (M4b)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3358, TASK-3360, TASK-3363
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (mount + run), AC1–AC3, AC15, design research S2/S6/S7. With
the builder (TASK-3358), the config/auth/actor pieces (TASK-3360) and the bulk
tools in place, this task mounts one `StreamableHttpMCPServer` per wiki on a
single aiohttp application, owns every store's lifecycle in `on_startup` /
`on_cleanup`, runs a **single-process** `TCPSite`, exposes the `wikitoolkit
serve` command, and declares the optional extra that pulls ai-parrot-server.
Depends on TASK-3363 only because both edit `cli.py` (serialisation). This task
is **exclusive** (`parallel: false`) because it edits `packages/ai-parrot/pyproject.toml`.

---

## Scope

- `async def build_server_app(config: WikiServerConfig) -> web.Application`: validate every entry's effective config (`backend == "arangodb"` unless `allow_sqlite_for_tests`); `app["wiki_default_actor"] = config.default_actor`; middleware `actor_middleware`; per wiki an `on_startup` hook that awaits `abuild_wiki_tools(entry.root, cfg, ledger_dir=..., read_repair=False, include_bulk_tools=True)`, builds `StreamableHttpMCPServer(MCPServerConfig(name=f"wikitoolkit-{name}", transport="streamable-http", auth_method=AuthMethod.API_KEY, api_key_header="Authorization", api_key_store=build_key_store(token), base_path=f"{base}/{name}", allowed_origins=..., session_ttl=...), parent_app=app)`, registers `bundle.tools + bundle.vault_tools`, awaits `server.start()`; matching `on_cleanup` awaits `server.stop()` then `close_bundle(bundle)`. Token from `os.environ[config.token_env]`, missing → `click.ClickException` before binding.
- `async def run_server(config, *, host=None, port=None) -> None`: `AppRunner` + one `TCPSite` (ssl context from `ssl_cert_path`/`ssl_key_path`), SIGTERM/SIGINT → graceful stop. No worker option.
- `wikitoolkit serve --config PATH [--host] [--port] [--ssl-cert] [--ssl-key]` in `cli.py` (inserted before the `mcp` command).
- `pyproject.toml` extra `wikitoolkit-server = ["ai-parrot-server"]`.
- Tests with `allow_sqlite_for_tests=True` (importorskip the server transport).

**NOT in scope**: the client, the CLI proxy, docs (TASK-3367), Redis sessions (§8 Q3 follow-up).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/serve.py` | MODIFY | `build_server_app`, `run_server` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `serve` command |
| `packages/ai-parrot/pyproject.toml` | MODIFY | optional extra |
| `packages/ai-parrot/tests/knowledge/wiki/test_serve_app.py` | CREATE | App-level tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.serve import WikiServerConfig, WikiServerEntry, actor_middleware, build_key_store, _import_server_stack, INSTALL_HINT   # TASK-3360
from parrot.knowledge.wiki.mcp_server import abuild_wiki_tools, close_bundle, WikiToolBundle           # TASK-3358
from parrot.knowledge.wiki.project import load_effective_config, sqlite_policy_from_config, WikiConfigError   # project.py:897, :682, :732
import asyncio, os, signal, ssl
from aiohttp import web
import click   # cli.py already imports click (:40)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py
class StreamableHttpMCPServer(HttpMCPServer):
    def __init__(self, config: MCPServerConfig, parent_app: web.Application | None = None, session_store: SessionStore | None = None)   # :259
    async def start(self)   # :291 — with parent_app: registers POST/GET/DELETE at config.base_path + GET base_path/info on parent_app.router (http.py:38-92, _register_routes :284-289); no socket of its own
    async def stop(self)    # :297
    self._session_store = InMemorySessionStore(...) by default   # :277-279 — per process (S6)
# packages/ai-parrot-server/src/parrot/mcp/transports/http.py
HttpMCPServer.start()   # :38-92 — parent_app branch: `target_router = self.parent_app.router`; standalone branch creates AppRunner/TCPSite itself (we do NOT use it; we pass parent_app)
# packages/ai-parrot-server/src/parrot/mcp/transports/base.py
_authenticate_request → API_KEY → _authenticate_api_key(request)   # :174-199 — header = config.api_key_header ("Authorization" here) → api_key_store.validate_key(...)
# packages/ai-parrot-server/src/parrot/mcp/config.py  @dataclass MCPServerConfig(name, version, description, transport, host, port, auth_method, api_key_header, api_key_store, base_path, allowed_origins, allow_any_origin, session_ttl, ...)   # :131-226
# packages/ai-parrot-server/src/parrot/mcp/parrot_server.py  ParrotMCPServer._check_base_path_conflicts :121-147 — precedent: distinct base paths per HTTP-like transport on one app
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
@wiki.command()                 # :1349
def mcp() -> None:              # :1350 (unique two-line anchor `@wiki.command()` + `def mcp() -> None:`)
# packages/ai-parrot/pyproject.toml  [project.optional-dependencies] :206 … `server = [\n    "ai-parrot-server[all]",\n]` :357-359 (`^server = \[` 1 occurrence)
```

### Does NOT Exist
- ~~`build_server_app` / `run_server` / `wikitoolkit serve`~~ / ~~`wikitoolkit-server` extra~~ — created here.
- ~~`StreamableHttpMCPServer(...).start()` opening its own port when `parent_app` is given~~ — it only registers routes; our `TCPSite` serves (http.py:38-92).
- ~~`MCPServerConfig(bearer_token=...)`~~ / ~~`AuthMethod.STATIC_BEARER`~~ — use `API_KEY` + `api_key_header="Authorization"` + `build_key_store`.
- ~~`--workers` option~~ — deliberately absent (§8 Q3: single process).
- ~~`app.cleanup_ctx` requirement~~ — use `app.on_startup.append` / `app.on_cleanup.append` (simpler; either is acceptable, but do not mix).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/serve.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_serve_app.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py#StreamableHttpMCPServer",
    "sym:packages/ai-parrot-server/src/parrot/mcp/transports/http.py#HttpMCPServer.start",
    "sym:packages/ai-parrot-server/src/parrot/mcp/config.py#MCPServerConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#mcp",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Validate **everything** (token present, backends, names/routes) before `runner.setup()` — fail-fast (AC1).
- Startup hooks must run on the serving loop (they do, via `on_startup`); never call `build_wiki_tools` (sync) here (S2).
- `/info` sits behind the same auth (AC2) — `StreamableHttpMCPServer._handle_info` is registered on the same router; verify `_authenticate_request` guards it; if it does not, wrap `/info` in a small auth-checking handler (record the finding in the Completion Note).
- `run_server` is single-process; document in the command help ("run one process; put a reverse proxy in front for TLS/HA").

---

## Implementation Blueprint

### Steps (in order)
1. `build_server_app` — *why*: the app is testable without binding a port.
2. `run_server` — *why*: separates process concerns (signals, TLS) from app construction.
3. `serve` click command — *why*: user entry point; inserted before `mcp` so the two transport commands sit together.
4. pyproject extra — *why*: AC15.
5. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/serve.py` (MODIFY — append at end of file)
```python
# AFTER — append below `build_key_store` (end of file as written by TASK-3360)
async def build_server_app(config: WikiServerConfig) -> web.Application:
    """Validate the config, then mount one Streamable HTTP MCP server per wiki on a single aiohttp app."""
    StreamableHttpMCPServer, MCPServerConfig, AuthMethod, _, _ = _import_server_stack()
    token = os.environ.get(config.token_env, "").strip()
    if not token:
        raise click.ClickException(f"{config.token_env} is not set — refusing to start without a bearer token")
    entries: dict[str, tuple[WikiServerEntry, Any]] = {}
    for name, entry in config.wikis.items():
        cfg = load_effective_config(entry.root, env=entry.env).config
        if cfg.backend != "arangodb" and not config.allow_sqlite_for_tests:
            raise click.ClickException(f"wiki {name!r}: backend must be arangodb (got {cfg.backend})")
        entries[name] = (entry, cfg)
    app = web.Application(middlewares=[actor_middleware])
    app["wiki_default_actor"] = config.default_actor
    app["wiki_servers"] = {}
    base = config.base_path.rstrip("/")

    for name, (entry, cfg) in entries.items():
        async def _start(app: web.Application, name: str = name, entry: WikiServerEntry = entry, cfg: Any = cfg) -> None:
            from parrot.knowledge.wiki.mcp_server import abuild_wiki_tools
            ledger_dir = entry.ledger_dir or cfg.ledger_path(entry.root)
            bundle = await abuild_wiki_tools(entry.root, cfg, ledger_dir=ledger_dir, read_repair=False, include_bulk_tools=True)
            server = StreamableHttpMCPServer(
                MCPServerConfig(name=f"wikitoolkit-{name}", version="1.0.0", description=bundle.description,
                                transport="streamable-http", auth_method=AuthMethod.API_KEY, api_key_header="Authorization",
                                api_key_store=build_key_store(token), base_path=f"{base}/{name}",
                                allowed_origins=config.allowed_origins, session_ttl=config.session_ttl),
                parent_app=app)
            server.register_tools(bundle.tools + bundle.vault_tools)
            await server.start()
            app["wiki_servers"][name] = (server, bundle)
            logger.info("mounted wiki %s at %s/%s (%d tools)", name, base, name, len(server.tools))

        async def _stop(app: web.Application, name: str = name) -> None:
            from parrot.knowledge.wiki.mcp_server import close_bundle
            server, bundle = app["wiki_servers"].pop(name, (None, None))
            if server is not None:
                await server.stop()
            if bundle is not None:
                await close_bundle(bundle)

        app.on_startup.append(_start)
        app.on_cleanup.append(_stop)
    return app


async def run_server(config: WikiServerConfig, *, host: str | None = None, port: int | None = None) -> None:
    """Serve the app in ONE process until SIGTERM/SIGINT (sessions are in-memory per process — §8 Q3)."""
    app = await build_server_app(config)
    ssl_ctx = None
    if config.ssl_cert_path and config.ssl_key_path:
        ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_ctx.load_cert_chain(certfile=str(config.ssl_cert_path), keyfile=str(config.ssl_key_path))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host or config.host, port or config.port, ssl_context=ssl_ctx)
    await site.start()
    stop = asyncio.Event()
    # FILL IN: loop.add_signal_handler(SIGTERM/SIGINT, stop.set) (guard NotImplementedError on non-POSIX); await stop.wait(); finally await runner.cleanup() — bounded by AC1
```
**Why this shape**: startup hooks give every ArangoDB connection the serving loop (S2); `parent_app` mounting reuses `HttpMCPServer.start`'s router branch and nothing else; `api_key_header="Authorization"` makes `_authenticate_api_key` consume the bearer header verbatim.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -B1 '^def mcp() -> None:' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py → the preceding line is `@wiki.command()` at cli.py:1349)
# BEFORE — insert above the `@wiki.command()` that decorates `def mcp() -> None:` (cli.py:1349-1350)
@wiki.command()
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path), help="server.yaml")
@click.option("--host", default=None, help="Bind address (default: server.yaml host).")
@click.option("--port", default=None, type=int, help="Bind port (default: server.yaml port).")
@click.option("--ssl-cert", "ssl_cert", default=None, type=click.Path(path_type=Path), help="TLS certificate (or terminate TLS at a reverse proxy).")
@click.option("--ssl-key", "ssl_key", default=None, type=click.Path(path_type=Path), help="TLS private key.")
def serve(config_path: Path, host: str | None, port: int | None, ssl_cert: Path | None, ssl_key: Path | None) -> None:
    """Serve one or more wikis as MCP Streamable HTTP at <base_path>/<wiki> (FEAT-569).

    Runs ONE process; sessions are in-memory. Put a reverse proxy in front for
    TLS and high availability. Requires `pip install 'ai-parrot[wikitoolkit-server]'`.
    """
    from parrot.knowledge.wiki.serve import WikiServerConfig, run_server

    config = WikiServerConfig.from_yaml(config_path)
    if ssl_cert or ssl_key:
        config = config.model_copy(update={"ssl_cert_path": ssl_cert, "ssl_key_path": ssl_key})
    _run(run_server(config, host=host, port=port))


```
**Why**: mirrors `mcp()`'s lazy-import style (cli.py:1349-1362); `_run` (cli.py:494) is the module's coroutine runner.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '^server = \[' packages/ai-parrot/pyproject.toml)
# BEFORE — insert above `server = [` (verified: pyproject.toml:357)
# FEAT-569: `wikitoolkit serve` needs the Streamable HTTP MCP transport from the server satellite.
wikitoolkit-server = ["ai-parrot-server"]
```
**Why**: precedent `server = ["ai-parrot-server[all]"]` (:357-359); clients keep zero new deps (AC15). This edit makes the task **exclusive** (`parallel: false`).

### FILL IN checklist
- [ ] `run_server` signal handling + cleanup — bounded by AC1.
- [ ] Confirm `/info` is auth-guarded (AC2); if not, wrap it and record the finding.
- [ ] `serve` command placement before `mcp` and `Path` import present in cli.py (`from pathlib import Path, PurePosixPath` at cli.py:37 — yes).

---

## Acceptance Criteria

- [ ] `build_server_app` with two SQLite test wikis (`allow_sqlite_for_tests=True`) + token set: after `runner.setup()`, `GET /mcp/a/info` with the bearer → 200 JSON with `tools_count ≥ 13`; without bearer → 401; `GET /mcp/zzz/info` → 404.
- [ ] `POST /mcp/a` initialize + `tools/list` (bearer) lists today's tool names + the 4 bulk tools (AC3); `tools/call wiki_remember` with `X-Wiki-Actor: human:alice` writes `asserted_by == "human:alice"`; without header → `agent:unknown` (AC4).
- [ ] Missing token env → `click.ClickException` before any bind; a wiki with `backend: sqlite` and `allow_sqlite_for_tests=False` → `ClickException`.
- [ ] `on_cleanup` closes stores (spy on `close_bundle`).
- [ ] `wikitoolkit serve --help` shows the four options and no `--workers`; `pip install -e 'packages/ai-parrot[wikitoolkit-server]'` resolves (or `uv pip compile` dry-run) — document evidence in the Completion Note.
- [ ] `ruff check` clean on `serve.py` and `cli.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_serve_app.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_serve_app.py
import asyncio, pytest, aiohttp
from aiohttp import web
pytest.importorskip("parrot.mcp.transports.streamable_http")
from parrot.knowledge.wiki.project import WikiProjectConfig, save_project_config
from parrot.knowledge.wiki.serve import WikiServerConfig, build_server_app
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store

H = {"Authorization": "Bearer t0k3n"}


@pytest.fixture
async def served(tmp_path, monkeypatch):
    monkeypatch.setenv("WIKITOOLKIT_SERVER_TOKEN", "t0k3n")
    wikis = {}
    for name in ("a", "b"):
        root = tmp_path / name; (root / ".parrot").mkdir(parents=True)
        cfg = WikiProjectConfig(wiki_name=name); save_project_config(root, cfg)
        store = create_wiki_store(cfg.storage_path(root), wiki_name=name, backend="sqlite")
        await store.upsert_pages([WikiPageRecord(concept_id="c", title="c", body="b")])
        wikis[name] = {"root": str(root)}
    app = await build_server_app(WikiServerConfig(wikis=wikis, allow_sqlite_for_tests=True))
    runner = web.AppRunner(app); await runner.setup(); site = web.TCPSite(runner, "127.0.0.1", 0); await site.start()
    yield f"http://127.0.0.1:{runner.addresses[0][1]}/mcp"; await runner.cleanup()


async def test_info_auth_and_404(served):
    async with aiohttp.ClientSession() as s:
        assert (await s.get(f"{served}/a/info")).status == 401
        r = await s.get(f"{served}/a/info", headers=H); assert r.status == 200 and (await r.json())["tools_count"] >= 13
        assert (await s.get(f"{served}/zzz/info", headers=H)).status == 404


async def test_tools_list_and_actor(served):
    from parrot.knowledge.wiki.project import WikiRemoteConfig
    from parrot.knowledge.wiki.remote import RemoteWikiClient
    import os; os.environ["WIKITOOLKIT_TOKEN"] = "t0k3n"
    async with RemoteWikiClient(WikiRemoteConfig(url=f"{served}/a"), actor="human:alice") as c:
        names = {t["name"] for t in await c.list_tools()}
        assert {"wiki_query", "wiki_ingest_batch", "wiki_sync_pull"} <= names
        await c.call_tool("wiki_remember", {"fact": "f", "category": "note", "title": "t"})   # FILL IN: real kwargs
    # FILL IN: open the wiki 'a' store and assert the memory page has asserted_by == "human:alice"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3358, TASK-3360, TASK-3363 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-read `HttpMCPServer.start` (http.py:38-92) and `_authenticate_request` (base.py:174) before wiring
4. **Update status** in `sdd/tasks/index/wikitoolkit-http-mcp.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** acceptance criteria; run the Validation Commands
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
