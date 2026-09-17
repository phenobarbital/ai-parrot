# TASK-3360: `serve.py` part A — server config models, static bearer key store, actor middleware (M4a)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3352
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (config + gate), AC2, AC4, design research S3/S4/S7. The HTTP
server needs three core-side building blocks before any transport is mounted:
the `server.yaml` model (`WikiServerConfig` / `WikiServerEntry`, with URL-safe
names and pairwise-distinct routes), a **static bearer** credential that plugs
into ai-parrot-server's existing `AuthMethod.API_KEY` path (a one-token
`APIKeyStore` whose `validate_key` strips `Bearer `), and the aiohttp
middleware that turns `X-Wiki-Actor` into the ContextVar from TASK-3352
(default `agent:unknown`, malformed → 400). The mounting itself is TASK-3361.

---

## Scope

- `WikiServerEntry`, `WikiServerConfig` (+ `from_yaml`, name/route validation, `allow_sqlite_for_tests: bool = False`).
- `ACTOR_RE = re.compile(r"^(human|agent|service):[\w.@-]{1,64}$")`; `actor_middleware` (aiohttp `@web.middleware`): read `X-Wiki-Actor` → validate → `request["wiki_actor"]` → run handler inside `actor_scope(actor)`; absent → `request.app["wiki_default_actor"]`; malformed → `web.json_response({...}, status=400)`.
- `_import_server_stack()` lazy importer returning `(StreamableHttpMCPServer, MCPServerConfig, AuthMethod, APIKeyStore, APIKeyRecord)` or raising `click.ClickException` with the install hint.
- `build_key_store(token) -> APIKeyStore`: defines and instantiates `StaticBearerKeyStore(APIKeyStore)` inside the function (so importing `serve.py` never imports ai-parrot-server): `validate_key(key)` accepts `"Bearer <t>"` or `"<t>"`, `hmac.compare_digest`, returns `APIKeyRecord(key=..., user_id=f"token:{sha256[:8]}", created_at=time.time())`; `log_session_start` no-op.
- Unit tests (`pytest.importorskip("parrot.mcp.transports.streamable_http")` for the key-store test only).

**NOT in scope**: `build_server_app` / `run_server` / `serve` command (TASK-3361), pyproject extra (TASK-3361).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/serve.py` | CREATE | config models, actor middleware, lazy imports, key store factory |
| `packages/ai-parrot/tests/knowledge/wiki/test_serve_auth.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click, hashlib, hmac, re, time, yaml                       # pyyaml is a core dependency (used by parrot/mcp/toolkit_config.py)
from aiohttp import web
from pydantic import BaseModel, Field, field_validator, model_validator
from parrot.knowledge.wiki.actor import actor_scope               # TASK-3352
from parrot.knowledge.wiki.project import validate_namespace_name   # project.py:147-178 (raises on invalid/reserved names)
# LAZY (inside _import_server_stack only) — ai-parrot-server:
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer   # streamable_http.py:250
from parrot.mcp.config import MCPServerConfig, AuthMethod                    # config.py:131, :9
from parrot.mcp.oauth_server import APIKeyStore, APIKeyRecord                 # oauth_server.py:86, :75
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/oauth_server.py
@dataclass class APIKeyRecord: key: str; user_id: str; created_at: float; expires_at: Optional[float] = None; scopes: list[str] = []; description: str = ""   # :75-84
class APIKeyStore:                                                       # :86
    def __init__(self): self._keys = {}; self._sessions = []
    def validate_key(self, key: str) -> Optional[APIKeyRecord]           # :156
    def log_session_start(self, key: str, user_id: str, timestamp: float) -> None   # :194
# packages/ai-parrot-server/src/parrot/mcp/transports/base.py
async def RemoteMCPServerBase._authenticate_api_key(self, request)      # :~199 — api_key = request.headers.get(self.config.api_key_header); record = self.api_key_store.validate_key(api_key); … request["mcp_user"] = {"user_id": record.user_id, "scopes": record.scopes}
# packages/ai-parrot-server/src/parrot/mcp/config.py
class AuthMethod(str, Enum): NONE, API_KEY, OAUTH2_INTERNAL, OAUTH2_EXTERNAL, BEARER   # :9-16 (BEARER = navigator-auth sessions — NOT usable here)
@dataclass class MCPServerConfig: auth_method, api_key_header="X-API-Key", api_key_store: Optional[Any], base_path="/mcp", allowed_origins, session_ttl, ssl_cert_path, ssl_key_path   # :131-226
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def validate_namespace_name(name: str) -> ...                            # :147-178
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.serve`~~ — created here.
- ~~`AuthMethod.STATIC_BEARER`~~ — no such member; reuse `API_KEY` with `api_key_header="Authorization"` (TASK-3361 wires it).
- ~~`MCPServerConfig.bearer_token`~~ — no such field.
- ~~`APIKeyStore(token=...)`~~ — constructor takes no args; subclass and override `validate_key`.
- ~~`parrot.mcp.server_base` in ai-parrot-server~~ — the core module is `parrot/mcp/server_base.py`; do not cite the server path (design research S3/S4 got this wrong).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/serve.py", "action": "CREATE" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_serve_auth.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#validate_namespace_name",
    "sym:packages/ai-parrot-server/src/parrot/mcp/oauth_server.py#APIKeyStore",
    "sym:packages/ai-parrot-server/src/parrot/mcp/oauth_server.py#APIKeyRecord",
    "sym:packages/ai-parrot-server/src/parrot/mcp/config.py#MCPServerConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Module import of `serve.py` must succeed **without** ai-parrot-server installed (all server imports inside `_import_server_stack`).
- Name validation: `validate_namespace_name(name)` **and** `re.fullmatch(r"[A-Za-z0-9._-]+", name)`; routes `f"{base_path}/{name}".rstrip("/")` must be pairwise distinct (S7).
- Middleware order: it runs **before** auth (registered on the parent app), so even a 401 is attributed; it must never read the body.
- `default_actor` must itself match `ACTOR_RE` (validator).

---

## Implementation Blueprint

### Steps (in order)
1. Models + validators — *why*: TASK-3361 loads them first (fail-fast).
2. `ACTOR_RE` + `actor_middleware` — *why*: pure aiohttp/core; testable without ai-parrot-server.
3. `_import_server_stack` + `build_key_store` — *why*: isolates the optional dependency.
4. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/serve.py` (CREATE)
```python
"""`wikitoolkit serve` — configuration, static bearer gate and actor propagation (FEAT-569).

Server-stack imports (ai-parrot-server) are LAZY: importing this module must work
on a client that only has core installed.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from pathlib import Path
from typing import Any

import click
import yaml
from aiohttp import web
from pydantic import BaseModel, Field, field_validator, model_validator

from parrot.knowledge.wiki.actor import actor_scope
from parrot.knowledge.wiki.project import validate_namespace_name

logger = logging.getLogger(__name__)
ACTOR_RE = re.compile(r"^(human|agent|service):[\w.@-]{1,64}$")
INSTALL_HINT = "wikitoolkit serve needs the ai-parrot-server package: pip install 'ai-parrot[wikitoolkit-server]'"


class WikiServerEntry(BaseModel):
    """One wiki served by `wikitoolkit serve`."""
    root: Path
    env: str | None = None
    ledger_dir: Path | None = None
    description: str = ""


class WikiServerConfig(BaseModel):
    """`server.yaml` for `wikitoolkit serve`."""
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    base_path: str = "/mcp"
    token_env: str = "WIKITOOLKIT_SERVER_TOKEN"
    default_actor: str = "agent:unknown"
    allowed_origins: list[str] | None = None
    ssl_cert_path: Path | None = None
    ssl_key_path: Path | None = None
    session_ttl: int = Field(default=3600, ge=60)
    allow_sqlite_for_tests: bool = False
    wikis: dict[str, WikiServerEntry]

    @field_validator("default_actor")
    @classmethod
    def _actor_shape(cls, value: str) -> str:
        if not ACTOR_RE.match(value):
            raise ValueError(f"default_actor must match {ACTOR_RE.pattern}")
        return value

    @model_validator(mode="after")
    def _names_and_routes(self) -> "WikiServerConfig":
        # FILL IN: for each name: validate_namespace_name(name); re.fullmatch(r"[A-Za-z0-9._-]+", name) else ValueError;
        #          routes = {f"{self.base_path.rstrip('/')}/{name}" for name}; len(routes) == len(self.wikis) else ValueError("duplicate route") — bounded by S7 / AC1
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> "WikiServerConfig":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


@web.middleware
async def actor_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """Bind `X-Wiki-Actor` (or the configured default) to the request context; malformed → 400."""
    raw = request.headers.get("X-Wiki-Actor")
    actor = raw if raw else request.app["wiki_default_actor"]
    if not ACTOR_RE.match(actor):
        return web.json_response({"error": "invalid X-Wiki-Actor"}, status=400)
    request["wiki_actor"] = actor
    with actor_scope(actor):
        return await handler(request)


def _import_server_stack() -> tuple[Any, Any, Any, Any, Any]:
    """Lazily import the ai-parrot-server pieces; a missing package is a clear CLI error."""
    try:
        from parrot.mcp.config import AuthMethod, MCPServerConfig
        from parrot.mcp.oauth_server import APIKeyRecord, APIKeyStore
        from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer
    except ImportError as exc:
        raise click.ClickException(f"{INSTALL_HINT} ({exc})") from exc
    return StreamableHttpMCPServer, MCPServerConfig, AuthMethod, APIKeyStore, APIKeyRecord


def build_key_store(token: str) -> Any:
    """Return an `APIKeyStore` that accepts exactly one static token (`Bearer <t>` or `<t>`), constant-time."""
    _, _, _, APIKeyStore, APIKeyRecord = _import_server_stack()
    user_id = f"token:{hashlib.sha256(token.encode()).hexdigest()[:8]}"

    class StaticBearerKeyStore(APIKeyStore):  # type: ignore[misc,valid-type]
        """Single static bearer token; `log_session_start` is a no-op."""

        def validate_key(self, key: str):
            candidate = key[7:] if key.lower().startswith("bearer ") else key
            if hmac.compare_digest(candidate.encode(), token.encode()):
                return APIKeyRecord(key=candidate, user_id=user_id, created_at=time.time())
            return None

        def log_session_start(self, key: str, user_id: str, timestamp: float) -> None:
            return None

    return StaticBearerKeyStore()
```
**Why this shape**: the spec's `StaticBearerKeyStore` lives inside a factory so `serve.py` stays importable core-only (spec §7 "lazy imports"); `validate_key` is exactly what `_authenticate_api_key` calls (base.py:~199) once TASK-3361 sets `api_key_header="Authorization"`.

### FILL IN checklist
- [ ] `_names_and_routes` validator — bounded by S7/AC1.
- [ ] Tests for middleware use a tiny aiohttp app with the middleware + a handler that returns `current_actor()`.

---

## Acceptance Criteria

- [ ] `WikiServerConfig.from_yaml` loads a two-wiki file; duplicate normalised routes, `"bad name"`, and `default_actor="nobody"` are rejected with `ValidationError`.
- [ ] `import parrot.knowledge.wiki.serve` succeeds with ai-parrot-server absent (simulate by `monkeypatch.setitem(sys.modules, "parrot.mcp.transports.streamable_http", None)` → `_import_server_stack()` raises `click.ClickException` containing `ai-parrot[wikitoolkit-server]`).
- [ ] Middleware: no header → handler sees `agent:unknown` (configured default); `X-Wiki-Actor: human:alice` → `human:alice`; `X-Wiki-Actor: bad` → 400; the ContextVar is reset after the request.
- [ ] `build_key_store("t0k3n").validate_key("Bearer t0k3n").user_id.startswith("token:")`; `validate_key("t0k3n")` also accepted; `validate_key("Bearer nope") is None` (importorskip server package).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_serve_auth.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_serve_auth.py
import pytest, yaml
from aiohttp import web
from pydantic import ValidationError
from parrot.knowledge.wiki.actor import current_actor
from parrot.knowledge.wiki.serve import WikiServerConfig, actor_middleware, build_key_store


def test_config_validation(tmp_path):
    p = tmp_path / "server.yaml"
    p.write_text(yaml.safe_dump({"wikis": {"parrot": {"root": "/srv/p"}, "issues": {"root": "/srv/i"}}}))
    assert set(WikiServerConfig.from_yaml(p).wikis) == {"parrot", "issues"}
    with pytest.raises(ValidationError): WikiServerConfig(wikis={"bad name": {"root": "/x"}})
    with pytest.raises(ValidationError): WikiServerConfig(default_actor="nobody", wikis={"w": {"root": "/x"}})


async def test_actor_middleware():
    async def echo(request): return web.json_response({"actor": current_actor()})
    app = web.Application(middlewares=[actor_middleware]); app["wiki_default_actor"] = "agent:unknown"; app.router.add_get("/", echo)
    runner = web.AppRunner(app); await runner.setup(); site = web.TCPSite(runner, "127.0.0.1", 0); await site.start()
    import aiohttp
    base = f"http://127.0.0.1:{runner.addresses[0][1]}/"
    async with aiohttp.ClientSession() as s:
        assert (await (await s.get(base)).json())["actor"] == "agent:unknown"
        assert (await (await s.get(base, headers={"X-Wiki-Actor": "human:alice"})).json())["actor"] == "human:alice"
        assert (await s.get(base, headers={"X-Wiki-Actor": "bad"})).status == 400
    assert current_actor() == "agent:mcp"
    await runner.cleanup()


def test_key_store():
    pytest.importorskip("parrot.mcp.transports.streamable_http")
    ks = build_key_store("t0k3n")
    assert ks.validate_key("Bearer t0k3n").user_id.startswith("token:") and ks.validate_key("t0k3n")
    assert ks.validate_key("Bearer nope") is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3352 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `APIKeyRecord` fields and `_authenticate_api_key` behaviour
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
