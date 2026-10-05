"""Minimal MCP Streamable HTTP client for one remote wiki mount (FEAT-569)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiohttp

from parrot.knowledge.wiki.project import WikiRemoteConfig

PROTOCOL_VERSION = "2025-03-26"
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "wiki_query",
        "wiki_page",
        "wiki_related",
        "wiki_status",
        "wiki_symbol_lookup",
        "wiki_code_outline",
        "wiki_blast_radius",
        "wiki_page_hashes",
        "ledger_ready",
        "ledger_context",
        "wiki_sync_pull",
    }
)
logger = logging.getLogger(__name__)


class RemoteWikiError(Exception):
    """Typed failure raised while communicating with a remote wiki."""

    exit_code = 2

    def __init__(self, code: str, message: str, *, url: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.url = url
        self.status = status

    def __str__(self) -> str:
        return f"[remote:{self.code}] {self.message} ({self.url})"


def _decode_body(content_type: str, body: bytes, url: str = "") -> dict[str, Any]:
    """Decode a JSON or SSE JSON-RPC response body.

    Args:
        content_type: Response ``Content-Type`` header.
        body: Raw response body.
        url: URL used for a protocol error, when available.

    Returns:
        The first JSON object found in the response, or the decoded JSON body.

    Raises:
        RemoteWikiError: If the body is not valid JSON or SSE JSON.
    """
    try:
        if "text/event-stream" in content_type:
            for line in body.decode("utf-8", errors="replace").splitlines():
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    decoded = json.loads(payload)
                    if not isinstance(decoded, dict):
                        raise ValueError("JSON-RPC response must be an object")
                    return decoded
            raise ValueError("SSE body without data: line")
        decoded = json.loads(body)
        if not isinstance(decoded, dict):
            raise ValueError("JSON-RPC response must be an object")
        return decoded
    except (ValueError, UnicodeDecodeError) as exc:
        raise RemoteWikiError("protocol", f"unparsable response: {exc}", url=url) from exc


class RemoteWikiClient:
    """JSON-RPC over MCP Streamable HTTP: initialize, list, and call tools."""

    def __init__(
        self,
        remote: WikiRemoteConfig,
        *,
        actor: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        token = os.environ.get(remote.token_env, "").strip()
        if not token:
            raise RemoteWikiError(
                "token_missing",
                f"{remote.token_env} is not set (remote mode)",
                url=remote.url,
            )
        self._remote = remote
        self._token = token
        self._actor = actor
        self._session = session
        self._owns_session = session is None
        self._session_id: str | None = None
        self._next_id = 0

    async def __aenter__(self) -> "RemoteWikiClient":
        try:
            await self.initialize()
        except Exception:
            await self.close()
            raise
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    def _headers(self) -> dict[str, str]:
        """Build the headers required by the remote MCP endpoint."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Wiki-Actor": self._actor,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        return headers

    async def _post(
        self,
        method: str,
        params: dict[str, Any],
        *,
        notification: bool = False,
    ) -> dict[str, Any] | None:
        """Send one JSON-RPC request and map transport and protocol failures."""
        if self._session is None:
            connector = aiohttp.TCPConnector(ssl=False) if not self._remote.verify_tls else None
            self._session = aiohttp.ClientSession(connector=connector)

        self._next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            payload["id"] = self._next_id

        try:
            timeout = aiohttp.ClientTimeout(total=self._remote.timeout)
            async with self._session.post(
                self._remote.url,
                json=payload,
                headers=self._headers(),
                timeout=timeout,
            ) as response:
                response_session_id = response.headers.get("Mcp-Session-Id")
                if method == "initialize" and response_session_id:
                    self._session_id = response_session_id

                if response.status in (401, 403):
                    raise RemoteWikiError(
                        "unauthorized",
                        f"remote wiki rejected credentials (HTTP {response.status})",
                        url=self._remote.url,
                        status=response.status,
                    )
                if response.status == 404:
                    code = "session_expired" if self._session_id else "wiki_not_found"
                    message = "remote wiki session expired" if code == "session_expired" else "remote wiki not found"
                    raise RemoteWikiError(code, message, url=self._remote.url, status=response.status)
                if response.status in (202, 204):
                    return None

                body = await response.read()
                data = _decode_body(response.headers.get("Content-Type", ""), body, self._remote.url)
                if "error" in data:
                    error = data["error"]
                    message = error.get("message", "remote JSON-RPC error") if isinstance(error, dict) else str(error)
                    raise RemoteWikiError("tool_error", message, url=self._remote.url, status=response.status)
                if response.status >= 400:
                    raise RemoteWikiError(
                        "protocol",
                        f"remote wiki returned HTTP {response.status}",
                        url=self._remote.url,
                        status=response.status,
                    )
                return data.get("result")
        except (aiohttp.ClientConnectorError, aiohttp.ClientOSError) as exc:
            raise RemoteWikiError("unreachable", str(exc), url=self._remote.url) from exc
        except asyncio.TimeoutError as exc:
            raise RemoteWikiError("timeout", "remote wiki request timed out", url=self._remote.url) from exc

    async def initialize(self) -> dict[str, Any]:
        """Initialize the MCP session and acknowledge the initialized notification."""
        self._session_id = None
        result = await self._post(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "wikitoolkit", "version": "1.0.0"},
            },
        )
        await self._post("notifications/initialized", {}, notification=True)
        return result or {}

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return the tools advertised by the remote wiki."""
        return (await self._post("tools/list", {}) or {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool, retrying once after session expiry only for read-only tools."""
        try:
            return await self._post("tools/call", {"name": name, "arguments": arguments}) or {}
        except RemoteWikiError as exc:
            if exc.code != "session_expired" or name not in READ_ONLY_TOOLS:
                raise
            logger.info("remote session expired; re-initialising for read-only tool %s", name)
            await self.initialize()
            return await self._post("tools/call", {"name": name, "arguments": arguments}) or {}

    async def call_tool_text(self, name: str, arguments: dict[str, Any]) -> str:
        """Call a tool and join the text values in its MCP content envelope."""
        result = await self.call_tool(name, arguments)
        return "\n".join(content.get("text", "") for content in result.get("content", []) if isinstance(content, dict))

    async def close(self) -> None:
        """Close the client-owned HTTP session."""
        if self._owns_session and self._session is not None:
            await self._session.close()
