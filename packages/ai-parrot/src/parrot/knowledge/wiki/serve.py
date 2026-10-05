"""`wikitoolkit serve` — configuration, static bearer gate and actor propagation (FEAT-569).

Server-stack imports (ai-parrot-server) are LAZY: importing this module must work
on a client that only has core installed.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import signal
import ssl
import time
from pathlib import Path
from typing import Any

import click
import yaml
from aiohttp import web
from pydantic import BaseModel, Field, field_validator, model_validator

from parrot.knowledge.wiki.actor import actor_scope
from parrot.knowledge.wiki.project import load_effective_config, validate_namespace_name

logger = logging.getLogger(__name__)
# aiohttp rejects bigger bodies with 413; sized above the 1 MiB ingest payload plus envelope.
_MAX_REQUEST_BYTES = 4 * 1024 * 1024
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
        if not ACTOR_RE.fullmatch(value):
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
    if not ACTOR_RE.fullmatch(actor):
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


async def build_server_app(config: WikiServerConfig) -> web.Application:
    """Validate config and mount one Streamable HTTP MCP server per wiki."""
    StreamableHttpMCPServer, MCPServerConfig, AuthMethod, _, _ = _import_server_stack()
    token = os.environ.get(config.token_env, "").strip()
    if not token:
        raise click.ClickException(f"{config.token_env} is not set — refusing to start without a bearer token")

    entries: dict[str, tuple[WikiServerEntry, Any]] = {}
    for name, entry in config.wikis.items():
        effective_config = load_effective_config(entry.root, env=entry.env).config
        if effective_config.backend != "arangodb" and not config.allow_sqlite_for_tests:
            raise click.ClickException(f"wiki {name!r}: backend must be arangodb (got {effective_config.backend})")
        entries[name] = (entry, effective_config)

    app = web.Application(middlewares=[actor_middleware], client_max_size=_MAX_REQUEST_BYTES)
    app["wiki_default_actor"] = config.default_actor
    app["wiki_servers"] = {}
    base_path = config.base_path.rstrip("/")

    for name, (entry, effective_config) in entries.items():

        async def _start(
            app: web.Application,
            name: str = name,
            entry: WikiServerEntry = entry,
            effective_config: Any = effective_config,
        ) -> None:
            from parrot.knowledge.wiki.mcp_server import abuild_wiki_tools

            ledger_dir = entry.ledger_dir or effective_config.ledger_path(entry.root)
            bundle = await abuild_wiki_tools(
                entry.root,
                effective_config,
                ledger_dir=ledger_dir,
                read_repair=False,
                include_bulk_tools=True,
            )
            server = StreamableHttpMCPServer(
                MCPServerConfig(
                    name=f"wikitoolkit-{name}",
                    version="1.0.0",
                    description=bundle.description,
                    transport="streamable-http",
                    auth_method=AuthMethod.API_KEY,
                    api_key_header="Authorization",
                    api_key_store=build_key_store(token),
                    base_path=f"{base_path}/{name}",
                    allowed_origins=config.allowed_origins,
                    session_ttl=config.session_ttl,
                ),
                parent_app=app,
            )
            original_info = server._handle_info

            async def _authenticated_info(request: web.Request) -> web.Response:
                auth_response = await server._authenticate_request(request)
                if auth_response is not None:
                    return auth_response
                return await original_info(request)

            server._handle_info = _authenticated_info
            server.register_tools(bundle.tools + bundle.vault_tools)
            await server.start()
            app["wiki_servers"][name] = (server, bundle)
            logger.info("mounted wiki %s at %s/%s (%d tools)", name, base_path, name, len(server.tools))

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
    """Serve one process until SIGTERM or SIGINT, then clean up gracefully."""
    app = await build_server_app(config)
    ssl_context = None
    if config.ssl_cert_path and config.ssl_key_path:
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(certfile=str(config.ssl_cert_path), keyfile=str(config.ssl_key_path))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host or config.host, port or config.port, ssl_context=ssl_context)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    try:
        await site.start()
        await stop.wait()
    finally:
        await runner.cleanup()
