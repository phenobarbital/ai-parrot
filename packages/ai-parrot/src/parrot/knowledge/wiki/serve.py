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
        base = self.base_path.rstrip("/")
        routes: set[str] = set()
        for name in self.wikis:
            validate_namespace_name(name)
            if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
                raise ValueError(f"wiki name {name!r} must be URL-safe ([A-Za-z0-9._-]+)")
            routes.add(f"{base}/{name}".rstrip("/"))
        if len(routes) != len(self.wikis):
            raise ValueError("duplicate route among served wikis")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> "WikiServerConfig":
        """Load and validate a ``server.yaml`` file."""
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


@web.middleware
async def actor_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """Bind `X-Wiki-Actor` (or the configured default) to the request context; malformed -> 400."""
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
