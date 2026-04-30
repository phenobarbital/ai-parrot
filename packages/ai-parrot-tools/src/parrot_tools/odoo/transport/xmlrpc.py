"""XML-RPC transport for Odoo (v14-18 and any version with /xmlrpc/2/ enabled).

Uses ``xmlrpc.client`` (synchronous) and offloads RPC calls to a worker thread
via ``asyncio.to_thread`` so the event loop stays unblocked. This mirrors the
classic Odoo XML-RPC pattern used by Flowtask's OdooInjector and odoo-mcp-pro
for older Odoo releases.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import xmlrpc.client
from typing import Any
from xml.parsers.expat import ExpatError

from parrot.interfaces.odoointerface import (
    OdooAuthenticationError,
    OdooConfig,
    OdooConnectionError,
    OdooRPCError,
    _validate_model_name,
)

from .base import AbstractOdooTransport


def _build_proxy(url: str, verify_ssl: bool) -> xmlrpc.client.ServerProxy:
    """Create a ServerProxy with consistent SSL handling.

    Args:
        url: Full XML-RPC endpoint URL.
        verify_ssl: When False, build an unverified SSL context.

    Returns:
        A configured ``xmlrpc.client.ServerProxy`` instance.
    """
    if not verify_ssl and url.lower().startswith("https://"):
        import ssl

        ctx = ssl._create_unverified_context()  # noqa: SLF001 - intentional
        return xmlrpc.client.ServerProxy(url, allow_none=True, context=ctx)
    return xmlrpc.client.ServerProxy(url, allow_none=True)


class XmlRpcTransport(AbstractOdooTransport):
    """Synchronous XML-RPC client wrapped in an async surface."""

    name: str = "xmlrpc"

    def __init__(self, config: OdooConfig) -> None:
        """Initialise the XML-RPC transport.

        Args:
            config: Odoo connection configuration.
        """
        self.config = config
        self.uid: int | None = None
        self.logger = logging.getLogger("parrot_tools.odoo.XmlRpcTransport")
        base = self.config.url.rstrip("/")
        self._common = _build_proxy(f"{base}/xmlrpc/2/common", config.verify_ssl)
        self._object = _build_proxy(f"{base}/xmlrpc/2/object", config.verify_ssl)

    @classmethod
    def from_config(cls, config: OdooConfig) -> "XmlRpcTransport":
        """Build an XML-RPC transport from an :class:`OdooConfig`."""
        return cls(config)

    # ── Auth ────────────────────────────────────────────────────────────────

    def _authenticate_sync(self) -> int:
        try:
            uid = self._common.authenticate(
                self.config.database,
                self.config.username,
                self.config.password,
                {},
            )
        except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError) as exc:
            raise OdooRPCError(f"Odoo XML-RPC error during login: {exc}") from exc
        except (OSError, socket.error, ExpatError) as exc:
            raise OdooConnectionError(
                f"Network error contacting Odoo at {self.config.url}: {exc}"
            ) from exc
        if not uid:
            raise OdooAuthenticationError(
                f"Authentication failed for user {self.config.username!r} "
                f"on database {self.config.database!r}."
            )
        return int(uid)

    async def authenticate(self) -> int:
        self.logger.info(
            "Authenticating to Odoo db=%r as user=%r (xmlrpc)",
            self.config.database,
            self.config.username,
        )
        uid = await asyncio.to_thread(self._authenticate_sync)
        self.uid = uid
        self.logger.info("Authenticated successfully, uid=%d", uid)
        return uid

    # ── execute_kw ──────────────────────────────────────────────────────────

    def _execute_kw_sync(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any],
    ) -> Any:
        if self.uid is None:
            raise OdooAuthenticationError("Not authenticated. Call authenticate() first.")
        try:
            return self._object.execute_kw(
                self.config.database,
                self.uid,
                self.config.password,
                model,
                method,
                args,
                kwargs,
            )
        except xmlrpc.client.Fault as exc:
            raise OdooRPCError(
                f"Odoo RPC error: {exc.faultString}",
                error_data={"faultCode": exc.faultCode, "faultString": exc.faultString},
            ) from exc
        except xmlrpc.client.ProtocolError as exc:
            raise OdooRPCError(
                f"Odoo protocol error [{exc.errcode}]: {exc.errmsg}",
                error_data={"url": exc.url, "headers": dict(exc.headers or {})},
            ) from exc
        except (OSError, socket.error, ExpatError) as exc:
            raise OdooConnectionError(
                f"Network error contacting Odoo at {self.config.url}: {exc}"
            ) from exc

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        _validate_model_name(model)
        if self.uid is None:
            await self.authenticate()
        self.logger.debug("execute_kw model=%r method=%r (xmlrpc)", model, method)
        return await asyncio.to_thread(
            self._execute_kw_sync, model, method, args or [], kwargs or {}
        )

    # ── Version ─────────────────────────────────────────────────────────────

    def _version_sync(self) -> dict[str, Any]:
        try:
            return dict(self._common.version() or {})
        except (xmlrpc.client.Fault, xmlrpc.client.ProtocolError) as exc:
            raise OdooRPCError(f"Odoo XML-RPC error during version: {exc}") from exc
        except (OSError, socket.error, ExpatError) as exc:
            raise OdooConnectionError(
                f"Network error contacting Odoo at {self.config.url}: {exc}"
            ) from exc

    async def version(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._version_sync)

    async def close(self) -> None:
        # xmlrpc.client.ServerProxy holds no persistent socket; nothing to do.
        return None
