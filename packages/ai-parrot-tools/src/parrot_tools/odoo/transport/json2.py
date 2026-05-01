"""External JSON-2 transport for Odoo 19+.

Odoo 19 introduced the External JSON-2 API as the replacement for the legacy
XML-RPC and JSON-RPC object services. The endpoint shape is:

    POST /json/2/<model>/<method>

Unlike ``execute_kw``, JSON-2 accepts only named arguments. This transport keeps
the toolkit-facing ``execute_kw`` contract but translates the ORM calls used by
``OdooToolkit`` into JSON-2 request bodies.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from parrot.interfaces.odoointerface import (
    OdooAuthenticationError,
    OdooConfig,
    OdooConnectionError,
    OdooRPCError,
    _validate_model_name,
)

from .base import AbstractOdooTransport


def _looks_like_ids(value: Any) -> bool:
    """Return True for an Odoo record id or list of record ids."""
    if isinstance(value, int):
        return True
    return isinstance(value, list) and all(isinstance(item, int) for item in value)


class Json2Transport(AbstractOdooTransport):
    """Async transport for Odoo's External JSON-2 API."""

    name: str = "json2"

    def __init__(self, config: OdooConfig) -> None:
        self.config = config
        self.uid: int | None = None
        self._session: aiohttp.ClientSession | None = None

    @classmethod
    def from_config(cls, config: OdooConfig) -> "Json2Transport":
        """Build a JSON-2 transport from an :class:`OdooConfig`."""
        return cls(config)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            connector = aiohttp.TCPConnector(ssl=self.config.verify_ssl)
            self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self._session

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"bearer {self.config.password}",
            "X-Odoo-Database": self.config.database,
            "Content-Type": "application/json",
        }

    async def _request_json2(
        self,
        model: str,
        method: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        _validate_model_name(model)
        url = f"{self.config.url.rstrip('/')}/json/2/{model}/{method}"
        session = await self._get_session()
        try:
            async with session.post(url, headers=self._headers(), json=body or {}) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    message = (
                        data.get("message", f"HTTP {resp.status}") if isinstance(data, dict) else f"HTTP {resp.status}"
                    )
                    error = OdooAuthenticationError if resp.status in (401, 403) else OdooRPCError
                    raise error(f"Odoo JSON-2 error [{resp.status}] calling {model}.{method}: {message}")
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise OdooConnectionError(f"Network error contacting Odoo JSON-2 at {url}: {exc}") from exc

    @staticmethod
    def _build_body(
        method: str,
        args: list[Any] | None,
        kwargs: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Translate legacy ``execute_kw`` args into JSON-2 named arguments."""
        args = args or []
        body = dict(kwargs or {})

        if method in {"search", "search_read", "search_count"}:
            if len(args) > 1:
                raise OdooRPCError(f"JSON-2 transport cannot map positional args for method {method!r}.")
            body.setdefault("domain", args[0] if args else [])
            return body

        if method == "read":
            if not args or not _looks_like_ids(args[0]):
                raise OdooRPCError("JSON-2 read requires record ids as the first argument.")
            body.setdefault("ids", args[0])
            if len(args) > 1:
                body.setdefault("fields", args[1])
            if len(args) > 2:
                body.setdefault("load", args[2])
            return body

        if method == "create":
            if len(args) != 1:
                raise OdooRPCError("JSON-2 create requires exactly one values argument.")
            body.setdefault("vals_list", args[0])
            return body

        if method == "write":
            if len(args) != 2 or not _looks_like_ids(args[0]) or not isinstance(args[1], dict):
                raise OdooRPCError("JSON-2 write requires ids and a values dict.")
            body.setdefault("ids", args[0])
            body.setdefault("vals", args[1])
            return body

        if method == "unlink":
            if len(args) != 1 or not _looks_like_ids(args[0]):
                raise OdooRPCError("JSON-2 unlink requires record ids.")
            body.setdefault("ids", args[0])
            return body

        if method == "fields_get":
            if args:
                raise OdooRPCError("JSON-2 fields_get does not support positional args.")
            return body

        if method == "check_access_rights":
            if len(args) != 1:
                raise OdooRPCError("JSON-2 check_access_rights requires one operation argument.")
            body.setdefault("operation", args[0])
            return body

        if method == "load":
            if len(args) != 2:
                raise OdooRPCError("JSON-2 load requires fields and data arguments.")
            body.setdefault("fields", args[0])
            body.setdefault("data", args[1])
            return body

        if len(args) == 1 and _looks_like_ids(args[0]):
            body.setdefault("ids", args[0])
            return body

        if not args:
            return body

        raise OdooRPCError(
            f"JSON-2 transport cannot map positional args for method {method!r}. "
            "Add an explicit JSON-2 argument mapping or use the legacy jsonrpc protocol."
        )

    async def authenticate(self) -> int:
        """Validate the bearer API key and cache the current user id when available."""
        result = await self._request_json2("res.users", "context_get", {})
        uid = result.get("uid") if isinstance(result, dict) else None
        self.uid = int(uid) if isinstance(uid, int) else 0
        return self.uid

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        body = self._build_body(method, args, kwargs)
        return await self._request_json2(model, method, body)

    async def version(self) -> dict[str, Any]:
        url = f"{self.config.url.rstrip('/')}/web/version"
        session = await self._get_session()
        try:
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise OdooRPCError(f"Odoo version endpoint failed [{resp.status}] at {url}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise OdooConnectionError(f"Network error contacting Odoo version endpoint at {url}: {exc}") from exc

        version = str(data.get("version", ""))
        version_info = list(data.get("version_info") or [])
        server_serie = ".".join(str(part) for part in version_info[:2]) if version_info else version
        return {
            "server_version": version,
            "server_serie": server_serie,
            "server_version_info": version_info,
        }

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
