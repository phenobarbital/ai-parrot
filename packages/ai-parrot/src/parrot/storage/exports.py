"""Tenant-partitioned file exports (PA-12): what a Studio export tool writes, and who may download it.

Keys are ``{tenant}/{agent}/{export_id}/{filename}``, built from the SERVER-bound tool scope — never from anything the
LLM or the client chose — and every segment is validated (no separators, no ``..``, no control characters), so a key
can never address another partition. A file is readable only through :meth:`ArtifactStore.get_export` with the
caller's own tenant (anything else is ``None``: the download route answers 404, never 403), only until its TTL
(``STUDIO_ARTIFACT_TTL_SECONDS``, default 7 days) and is refused at write time above ``STUDIO_ARTIFACT_MAX_BYTES``
(default 50 MB).
"""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from typing import Any

from navconfig import config

EXPORT_PREFIX = "exports"
NO_TENANT = "-"  # the partition of a host with no tenants (a caller with no tenant reads only this one)
DEFAULT_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
STUDIO_EXPORTS_URL_BASE_KEY = "studio_exports_url_base"
DEFAULT_URL_BASE = "/api/v1/astudio/exports"

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")
_FILENAME_BAD = re.compile(r"[^\w.\- ()@+]")


class ExportError(Exception):
    """Base of the export store refusals."""


class InvalidExportKey(ExportError):
    """A key segment that could address another partition or path (``..``, separators, control characters…)."""


class ExportTooLarge(ExportError):
    """The file is above ``STUDIO_ARTIFACT_MAX_BYTES``."""


@dataclass(frozen=True)
class ExportRef:
    """What a tool returns to the LLM about a stored export."""

    key: str
    url: str
    filename: str
    bytes: int
    content_type: str
    expires_at: float

    def public(self) -> dict[str, Any]:
        """``{url, filename, bytes}``: all the LLM (and the user) need."""
        return {"url": self.url, "filename": self.filename, "bytes": self.bytes}


def partition_segment(value: str | None, *, what: str, from_key: bool = False) -> str:
    """A validated key segment; :class:`InvalidExportKey` otherwise.

    An empty tenant is :data:`NO_TENANT`; a caller-supplied tenant that IS the marker is refused (it would read the
    untenanted partition), while the marker inside an already-built key (``from_key``) is the partition itself.
    """
    text = (value or "").strip()
    if what == "tenant":
        if not text:
            return NO_TENANT
        if text == NO_TENANT:
            if from_key:
                return text
            raise InvalidExportKey("invalid tenant segment")
    if not _SEGMENT.match(text) or text in {".", ".."} or ".." in text:
        raise InvalidExportKey(f"invalid {what} segment")
    return text


def safe_filename(name: str) -> str:
    """The base name of ``name`` with every path part and unsafe character removed (never empty, never hidden)."""
    base = re.split(r"[\\/]", (name or "").strip())[-1]
    base = _FILENAME_BAD.sub("_", base).strip(" .")
    base = base.lstrip(".")[:120]
    return base or "export"


def build_export_key(tenant: str | None, agent: str | None, export_id: str, filename: str) -> str:
    """``{tenant}/{agent}/{export_id}/{filename}`` from validated parts."""
    return "/".join(
        (
            partition_segment(tenant, what="tenant"),
            partition_segment(agent or "agent", what="agent"),
            partition_segment(export_id, what="export id"),
            safe_filename(filename),
        )
    )


def parse_export_key(key: str) -> tuple[str, str, str, str]:
    """``(tenant, agent, export_id, filename)`` of a key; :class:`InvalidExportKey` for anything crafted."""
    parts = key.split("/")
    if len(parts) != 4:
        raise InvalidExportKey("an export key has exactly four segments")
    tenant, agent, export_id, filename = parts
    partition_segment(tenant, what="tenant", from_key=True)
    partition_segment(agent, what="agent")
    partition_segment(export_id, what="export id")
    if filename != safe_filename(filename) or filename in {".", ".."}:
        raise InvalidExportKey("invalid filename segment")
    return tenant, agent, export_id, filename


def guess_content_type(filename: str) -> str:
    """Content type by extension (``application/octet-stream`` when unknown)."""
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def ttl_seconds() -> int:
    """``STUDIO_ARTIFACT_TTL_SECONDS`` (a positive integer; the default when unset or malformed)."""
    return _positive_int(config.get("STUDIO_ARTIFACT_TTL_SECONDS"), DEFAULT_TTL_SECONDS)


def max_bytes() -> int:
    """``STUDIO_ARTIFACT_MAX_BYTES`` (a positive integer; the default when unset or malformed)."""
    return _positive_int(config.get("STUDIO_ARTIFACT_MAX_BYTES"), DEFAULT_MAX_BYTES)


def _positive_int(raw: Any, default: int) -> int:
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default
