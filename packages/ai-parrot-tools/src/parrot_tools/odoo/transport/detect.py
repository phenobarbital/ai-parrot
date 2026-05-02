"""Auto-detect the best Odoo external API transport for a given server.

Strategy: use the unauthenticated ``/web/version`` endpoint first because it is
the Odoo 19+ replacement for the legacy ``common.version`` service. If it
reports Odoo 19 or newer, prefer JSON-2. Older versions use XML-RPC. When
``/web/version`` is unavailable, fall back to the legacy JSON-RPC version probe
only for compatibility detection.

* ``19.0`` and newer → JSON-2
* anything older or any error → XML-RPC
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

import aiohttp

from parrot.interfaces.odoointerface import OdooConfig

from .base import AbstractOdooTransport
from .json2 import Json2Transport
from .jsonrpc import JsonRpcTransport
from .xmlrpc import XmlRpcTransport

logger = logging.getLogger("parrot_tools.odoo.detect")

Protocol = Literal["auto", "json2", "jsonrpc", "xmlrpc"]


def _serie_is_json2(serie: str | None) -> bool:
    """Return True when ``serie`` looks like Odoo 19.0 or newer."""
    if not serie:
        return False
    try:
        major = int(serie.split(".")[0])
    except (ValueError, IndexError):
        return False
    return major >= 19


async def _probe_web_version(
    config: OdooConfig,
    timeout_seconds: float = 5.0,
) -> dict | None:
    """Fetch version data from Odoo's modern ``/web/version`` endpoint."""
    url = f"{config.url.rstrip('/')}/web/version"
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    connector = aiohttp.TCPConnector(ssl=config.verify_ssl)
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            async with session.get(url) as resp:
                if resp.status >= 400:
                    return None
                data = await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.debug("Web version probe failed for %s: %s", url, exc)
        return None

    if not data.get("version") and not data.get("version_info"):
        return None
    version = str(data.get("version", ""))
    version_info = list(data.get("version_info") or [])
    server_serie = ".".join(str(part) for part in version_info[:2]) if version_info else version
    return {
        "server_version": version,
        "server_serie": server_serie,
        "server_version_info": version_info,
    }


async def _probe_legacy_jsonrpc_version(
    config: OdooConfig,
    timeout_seconds: float = 5.0,
) -> dict | None:
    """Fetch ``common.version`` over legacy JSON-RPC.

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
        logger.debug("Legacy JSON-RPC version probe failed for %s: %s", url, exc)
        return None
    if data.get("error"):
        return None
    result = data.get("result")
    return result if isinstance(result, dict) else None


async def auto_detect_transport(config: OdooConfig) -> AbstractOdooTransport:
    """Return the best transport for the given server.

    Probe order:

    1. ``/web/version`` — succeeds → inspect ``server_serie``.
       Use JSON-2 when serie ≥ 19.0.
    2. Legacy JSON-RPC ``common.version`` — compatibility-only probe.
    3. Default to XML-RPC.
    """
    info = await _probe_web_version(config)
    if info is None:
        info = await _probe_legacy_jsonrpc_version(config)
    if info is not None:
        if _serie_is_json2(info.get("server_serie")):
            logger.info(
                "Auto-detect: using JSON-2 (server_serie=%r)",
                info.get("server_serie"),
            )
            return Json2Transport.from_config(config)
        logger.info(
            "Auto-detect: server_serie=%r → XML-RPC",
            info.get("server_serie"),
        )
    else:
        logger.info("Auto-detect: version probes failed → XML-RPC fallback")
    return XmlRpcTransport(config)


def build_transport(protocol: Protocol, config: OdooConfig) -> AbstractOdooTransport | None:
    """Build a transport for an explicit protocol choice.

    Returns ``None`` for ``"auto"`` — callers must invoke
    :func:`auto_detect_transport` instead, which is async.
    """
    if protocol == "json2":
        return Json2Transport.from_config(config)
    if protocol == "jsonrpc":
        return JsonRpcTransport.from_config(config)
    if protocol == "xmlrpc":
        return XmlRpcTransport.from_config(config)
    if protocol == "auto":
        return None
    raise ValueError(f"Unknown protocol: {protocol!r}")
