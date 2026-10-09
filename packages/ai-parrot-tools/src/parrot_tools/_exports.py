"""Shared plumbing of the export tools (PA-11): write ONLY through the tenant-partitioned artifact store.

An export tool never lets the LLM choose where it writes: the path, file name, overwrite and template-path arguments
are not in its schema. When the tool has an ``artifact_store`` (a server-managed constructor parameter, filled from
``app["artifact_store"]``) the produced file goes to the store under the partition of the SERVER-bound tool scope and
the tool returns ``{url, filename, bytes}``. Without a store the tool keeps its legacy behaviour (a file under its own
constructor-configured ``output_dir``) — except inside a Studio tool scope, where a missing store is a refusal: a Studio
call never writes a local file.
"""

from __future__ import annotations

import logging
from typing import Any

from parrot.storage.exports import ExportError, export_url_base
from parrot.tools.scope import current_tool_scope
from parrot.tools.server_params import ServerParam

logger = logging.getLogger(__name__)

STORE_PARAM = {"artifact_store": ServerParam(source="app", key="artifact_store")}
UNSAFE_NAME_CHARS = ("/", "\\", "\x00")


class ExportStoreUnavailable(RuntimeError):
    """A Studio-scoped export call with no artifact store configured."""


def safe_template_name(name: str | None) -> str | None:
    """``name`` when it is a plain file name; ``ValueError`` for anything that is a path (separators, absolute, ``..``)."""
    if name is None or name == "":
        return None
    if any(ch in name for ch in UNSAFE_NAME_CHARS) or name.startswith(".") or ".." in name:
        raise ValueError("template must be a file name from the server-configured templates directory, not a path")
    return name


class ExportsToStoreMixin:
    """Mixin of an :class:`~parrot.tools.abstract.AbstractTool`: ``artifact_store`` + :meth:`_publish_export`."""

    server_managed_params = STORE_PARAM  # a CONSTRUCTOR param: every concrete class lists ``artifact_store`` in __init__
    artifact_store: Any = None

    @property
    def exports_to_store(self) -> bool:
        """Whether this instance publishes to the artifact store (a store was supplied)."""
        return self.artifact_store is not None

    def _require_export_target(self) -> None:
        """Refuse a Studio-scoped call that has no store (never a local write on a Studio call)."""
        if self.artifact_store is None and current_tool_scope() is not None:
            raise ExportStoreUnavailable("Exports are unavailable: no artifact store is configured for this tool.")

    async def _publish_export(self, filename: str, data: bytes | str, *, content_type: str | None = None) -> dict[str, Any]:
        """Store ``data`` under the caller's tenant partition and return ``{url, filename, bytes}``."""
        body = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        scope = current_tool_scope()
        tenant = getattr(getattr(scope, "caller", None), "tenant", None) if scope is not None else None
        agent = getattr(scope, "agent", None) if scope is not None else None
        agent_key = (str(agent.agent_id) if getattr(agent, "agent_id", None) else getattr(agent, "name", None)) or "agent"
        try:
            ref = await self.artifact_store.save_export(
                tenant, agent_key, filename, body, content_type=content_type, url_base=export_url_base()
            )
        except ExportError as exc:
            raise ValueError(f"export refused: {exc}") from exc
        return ref.public()
