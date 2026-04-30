"""Auto-detect the best Odoo RPC transport for a given server.

Strategy: hit the unauthenticated ``common.version`` endpoint over JSON-RPC
once. If we get a usable ``server_serie`` back, decide based on Odoo's serie:

* ``19.0`` and newer → JSON-RPC (Odoo's modern JSON/2 API)
* anything older or any error → XML-RPC

This matches odoo-mcp-pro's behaviour while keeping the probe cheap (one
network round-trip with a short timeout) and falling back gracefully when
JSON-RPC is disabled on the server.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

import aiohttp

from parrot.interfaces.odoointerface import OdooConfig, OdooInterface

from .base import AbstractOdooTransport
from .jsonrpc import JsonRpcTransport
from .xmlrpc import XmlRpcTransport

logger = logging.getLogger("parrot_tools.odoo.detect")

Protocol = Literal["auto", "jsonrpc", "xmlrpc"]


def _serie_is_jsonrpc(serie: str | None) -> bool:
    """Return True when ``serie`` looks like Odoo 19.0 or newer."""
    if not serie:
        return False
    try:
        major = int(serie.split(".")[0])
    except (ValueError, IndexError):
        return False
    return major >= 19


async def _probe_version(config: OdooConfig, timeout_seconds: float = 5.0) -> dict | None:
    """Fetch ``common.version`` over JSON-RPC.

    Returns the parsed dict on success, ``None`` on any failure (network,
    protocol, JSON parse, or non-2xx response). Errors are logged but never
    raised — callers should treat absence as a signal to fall back.
    """
    url = f"{config.url.rstrip('/')}/jsonrpc"
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "id": 1,
        "params": {"service": "common", "method": "version", "args": []},
    }
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    connector = aiohttp.TCPConnector(ssl=config.verify_ssl)
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.post(url, json=payload) as resp:
                if resp.status >= 400:
                    return None
                data = await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.debug("Version probe failed for %s: %s", url, exc)
        return None
    if data.get("error"):
        return None
    result = data.get("result")
    return result if isinstance(result, dict) else None


async def auto_detect_transport(config: OdooConfig) -> AbstractOdooTransport:
    """Return the best transport for the given server.

    Probe order:

    1. JSON-RPC ``common.version`` — succeeds → inspect ``server_serie``.
       Use JSON-RPC when serie ≥ 19.0, otherwise fall through.
    2. Default to XML-RPC.
    """
    info = await _probe_version(config)
    if info is not None:
        if _serie_is_jsonrpc(info.get("server_serie")):
            logger.info(
                "Auto-detect: using JSON-RPC (server_serie=%r)",
                info.get("server_serie"),
            )
            return JsonRpcTransport(
                OdooInterface(
                    url=config.url,
                    database=config.database,
                    username=config.username,
                    password=config.password,
                    timeout=config.timeout,
                    verify_ssl=config.verify_ssl,
                )
            )
        logger.info(
            "Auto-detect: server_serie=%r → XML-RPC",
            info.get("server_serie"),
        )
    else:
        logger.info("Auto-detect: JSON-RPC probe failed → XML-RPC fallback")
    return XmlRpcTransport(config)


def build_transport(protocol: Protocol, config: OdooConfig) -> AbstractOdooTransport | None:
    """Build a transport for an explicit protocol choice.

    Returns ``None`` for ``"auto"`` — callers must invoke
    :func:`auto_detect_transport` instead, which is async.
    """
    if protocol == "jsonrpc":
        return JsonRpcTransport.from_config(config)
    if protocol == "xmlrpc":
        return XmlRpcTransport.from_config(config)
    if protocol == "auto":
        return None
    raise ValueError(f"Unknown protocol: {protocol!r}")
