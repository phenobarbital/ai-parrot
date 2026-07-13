"""A2UI baking pass (Module 6).

Static surfaces (email, PDF, Teams card, baked HTML) cannot hold live data-model
bindings. The bake pass resolves EVERY ``{"$bind": "/pointer"}`` expression against
the envelope's data model, yielding a self-contained tree with zero live bindings.

**Core dependency hygiene (spec G8)**: this module imports ``jsonpointer`` *lazily*
inside :func:`_load_jsonpointer` — importing ``parrot.outputs.a2ui.baking`` therefore
works on a core-only install (zero new core deps). Full pointer *resolution* runs
only where ``jsonpointer`` is available (i.e. in the ``ai-parrot-visualizations[a2ui]``
satellite); calling it without the extra raises an actionable :class:`ImportError`.
Core-only installs can still *syntax-validate* bindings via Module 1's regex.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from parrot.outputs.a2ui.models import BINDING_KEY, CreateSurface, is_binding_expression

__all__ = ["BakeError", "bake_envelope", "persist_envelope"]

logger = logging.getLogger(__name__)

_A2UI_EXTRA = "ai-parrot-visualizations[a2ui]"


class BakeError(Exception):
    """Raised when an envelope cannot be fully baked (e.g. unresolvable pointer)."""


def _import_jsonpointer():
    """Import ``jsonpointer`` (indirection point so tests can force failure)."""
    import jsonpointer  # noqa: PLC0415 — lazy by design (G8)

    return jsonpointer


def _load_jsonpointer():
    """Lazily load ``jsonpointer``, raising an actionable error if unavailable.

    Returns:
        The imported ``jsonpointer`` module.

    Raises:
        ImportError: If ``jsonpointer`` is not installed; message names the extra.
    """
    try:
        return _import_jsonpointer()
    except ImportError as exc:
        raise ImportError(
            "A2UI data-model binding resolution requires 'jsonpointer'. "
            f"Install the renderer backend with: pip install {_A2UI_EXTRA}"
        ) from exc


def _resolve_value(value: Any, data_model: dict[str, Any]) -> Any:
    """Recursively resolve any binding expressions found in ``value``.

    Args:
        value: A property value (possibly nested dict/list) to resolve.
        data_model: The envelope's data model (a nested JSON document).

    Returns:
        ``value`` with every binding replaced by its resolved data-model value.

    Raises:
        BakeError: If a binding points at a path absent from the data model.
    """
    jsonpointer = _load_jsonpointer()
    if is_binding_expression(value):
        pointer = value[BINDING_KEY]
        try:
            return jsonpointer.resolve_pointer(data_model, pointer)
        except jsonpointer.JsonPointerException as exc:
            raise BakeError(
                f"Unresolvable data-model binding {pointer!r}: {exc}"
            ) from exc
    if isinstance(value, dict):
        return {key: _resolve_value(item, data_model) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item, data_model) for item in value]
    return value


def _has_live_binding(value: Any) -> bool:
    """Return whether ``value`` still contains any live binding expression."""
    if is_binding_expression(value):
        return True
    if isinstance(value, dict):
        return any(_has_live_binding(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_live_binding(item) for item in value)
    return False


def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]:
    """Bake an envelope: resolve all bindings against its data model.

    Args:
        envelope: The ``createSurface`` envelope to bake.

    Returns:
        A list of resolved component dicts (``id``/``component``/``properties``/
        ``children``) with zero live bindings.

    Raises:
        BakeError: If any binding is unresolvable, or if a live binding survives
            (post-condition guard).
        ImportError: If ``jsonpointer`` is unavailable (names the extra).
    """
    data_model = envelope.data_model
    baked: list[dict[str, Any]] = []
    for comp in envelope.components:
        resolved_props = _resolve_value(comp.properties, data_model)
        if _has_live_binding(resolved_props):  # pragma: no cover - defensive
            raise BakeError(
                f"Component {comp.id!r} still contains a live binding after baking."
            )
        baked.append(
            {
                "id": comp.id,
                "component": comp.component,
                "properties": resolved_props,
                "children": list(comp.children),
            }
        )
    return baked


async def persist_envelope(
    envelope: CreateSurface,
    store: Any,
    *,
    user_id: str,
    agent_id: str,
    session_id: str,
    artifact_id: str | None = None,
    title: str = "A2UI envelope",
) -> str:
    """Persist the source envelope via ``ArtifactStore`` and return its reference.

    The >200 KB S3 overflow is handled transparently by ``ArtifactStore`` (the
    ``definition_ref`` convention) — this function does not reimplement thresholds.

    Args:
        envelope: The source envelope to persist.
        store: An ``ArtifactStore`` instance (``save_artifact`` coroutine).
        user_id: Owning user id.
        agent_id: Owning agent id.
        session_id: Owning session id.
        artifact_id: Optional explicit id; a UUID4 is generated when omitted.
        title: Artifact title.

    Returns:
        The artifact id used as ``RenderedArtifact.source_envelope_ref``.
    """
    from parrot.storage.models import Artifact, ArtifactType  # local: avoid core cycle

    artifact_id = artifact_id or f"a2ui-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    artifact = Artifact(
        artifact_id=artifact_id,
        artifact_type=ArtifactType.INTERACTIVE,
        title=title,
        created_at=now,
        updated_at=now,
        definition=envelope.model_dump(by_alias=True, mode="json"),
    )
    await store.save_artifact(
        user_id=user_id,
        agent_id=agent_id,
        session_id=session_id,
        artifact=artifact,
    )
    logger.debug("Persisted A2UI envelope as artifact %s", artifact_id)
    return artifact_id
