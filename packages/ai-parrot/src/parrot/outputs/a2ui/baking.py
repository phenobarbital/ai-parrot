"""A2UI v1.0 baking pass (Module 4/6).

Static surfaces (email, PDF, Teams card, baked HTML) cannot hold live
data-model bindings or function calls. The bake pass resolves EVERY
``{"path": "/pointer"}`` (absolute or relative) and evaluates every
``{"call": ..., "args": {...}}`` against the envelope's data model — via
:class:`~parrot.outputs.a2ui.catalog.basic.functions.FunctionEvaluator` for
function calls — yielding a self-contained tree with zero live bindings.
``children: ChildTemplate`` is expanded into one clone per data-model list
item, with ``@index`` resolved and ids suffixed ``-<i>``.

**Core dependency hygiene (spec G8)**: this module imports ``jsonpointer``
*lazily* inside :func:`_load_jsonpointer` for resolving top-level
``{"path": ...}`` bindings (unchanged from FEAT-273) — importing
``parrot.outputs.a2ui.baking`` therefore still works on a core-only install.
:class:`FunctionEvaluator` (core, ``catalog/basic/functions.py``) has its
OWN self-contained pointer resolver for arguments nested inside a
``{"call": ...}`` — it does not need ``jsonpointer`` at all.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from parrot.outputs.a2ui.catalog.basic.functions import FunctionEvaluator
from parrot.outputs.a2ui.models import (
    ChildTemplate,
    Component,
    CreateSurface,
    FunctionCall,
)

__all__ = ["BakeError", "bake_envelope", "persist_envelope"]

logger = logging.getLogger(__name__)

_A2UI_EXTRA = "ai-parrot-visualizations[a2ui]"

#: Shared, stateless evaluator for ``{"call": ...}`` expressions during bake.
_EVALUATOR = FunctionEvaluator()


class BakeError(Exception):
    """Raised when an envelope cannot be fully baked (e.g. unresolvable pointer)."""


#: Module-private sentinel for an omitted optional binding (``parrot_optional``).
#: Never leaves :func:`_resolve_value` — the dict/list branches filter it out
#: before returning, so it is never stored as a property value.
_ABSENT = object()


def _import_jsonpointer():
    """Import ``jsonpointer`` (indirection point so tests can force failure)."""
    import jsonpointer

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


def _is_path_expr(value: Any) -> bool:
    """Whether ``value`` is a v1.0 ``DataBinding``-shaped dict: ``{"path": ...}``."""
    return isinstance(value, dict) and set(value) == {"path"}


def _is_call_expr(value: Any) -> bool:
    """Whether ``value`` is a v1.0 ``FunctionCall``-shaped dict: has a ``call`` key."""
    return isinstance(value, dict) and "call" in value


def _resolve_scoped_pointer(pointer: str, scope_path: str) -> str:
    """Resolve a possibly-relative pointer against ``scope_path`` (template scope)."""
    return FunctionEvaluator._resolve_scoped_pointer(pointer, scope_path)


def _resolve_value(
    value: Any,
    *,
    data_model: dict[str, Any],
    scope_path: str,
    index: int | None,
    optional_paths: set[str],
) -> Any:
    """Recursively resolve every ``{"path"}``/``{"call"}`` expression in ``value``.

    A ``{"path": ...}`` whose (possibly scope-relative) pointer is listed in
    ``optional_paths`` (``metadata.extensions.parrot_optional``) is OMITTED
    when it fails to resolve, rather than raising — the enclosing dict/list
    drops the entry entirely. Any other unresolvable binding raises.

    Args:
        value: A property value (possibly nested dict/list) to resolve.
        data_model: The envelope's data model.
        scope_path: The JSON Pointer of the current template item (``""``
            outside template scope).
        index: The current 0-based template index, if any.
        optional_paths: Pointers (raw or scope-resolved) allowed to be absent.

    Returns:
        ``value`` with every binding/call replaced by its resolved value, or
        :data:`_ABSENT` if ``value`` itself is an optional binding that did
        not resolve (callers must filter this out).

    Raises:
        BakeError: If a required (non-optional) binding/call is unresolvable.
    """
    if _is_path_expr(value):
        pointer = value["path"]
        resolved_pointer = _resolve_scoped_pointer(pointer, scope_path)
        jsonpointer = _load_jsonpointer()
        try:
            return jsonpointer.resolve_pointer(data_model, resolved_pointer)
        except jsonpointer.JsonPointerException as exc:
            if pointer in optional_paths or resolved_pointer in optional_paths:
                logger.info(
                    "Optional data-model binding %r did not resolve; omitting.",
                    pointer,
                )
                return _ABSENT
            raise BakeError(
                f"Unresolvable data-model path {pointer!r}: {exc}"
            ) from exc

    if _is_call_expr(value):
        call = FunctionCall.model_validate(value)
        try:
            return _EVALUATOR.evaluate(
                call, data_model=data_model, scope_path=scope_path, index=index
            )
        except (KeyError, IndexError) as exc:
            raise BakeError(
                f"Unresolvable function call {call.call!r}: {exc}"
            ) from exc

    if isinstance(value, dict):
        resolved = {
            key: _resolve_value(
                item,
                data_model=data_model,
                scope_path=scope_path,
                index=index,
                optional_paths=optional_paths,
            )
            for key, item in value.items()
        }
        return {key: item for key, item in resolved.items() if item is not _ABSENT}
    if isinstance(value, list):
        items = [
            _resolve_value(
                item,
                data_model=data_model,
                scope_path=scope_path,
                index=index,
                optional_paths=optional_paths,
            )
            for item in value
        ]
        return [item for item in items if item is not _ABSENT]
    return value


def _has_live_binding(value: Any) -> bool:
    """Return whether ``value`` still contains any live ``path``/``call`` expression."""
    if _is_path_expr(value) or _is_call_expr(value):
        return True
    if isinstance(value, dict):
        return any(_has_live_binding(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_live_binding(item) for item in value)
    return False


def _optional_paths(component: Component) -> set[str]:
    """Extract ``metadata.extensions.parrot_optional`` (a list of pointers)."""
    if component.metadata is not None and component.metadata.extensions is not None:
        return set(component.metadata.extensions.root.get("parrot_optional") or [])
    return set()


def _bake_component(
    component: Component,
    *,
    data_model: dict[str, Any],
    scope_path: str,
    index: int | None,
    id_suffix: str = "",
) -> dict[str, Any]:
    """Bake a single component's own top-level props (not template expansion).

    Args:
        component: The component to bake.
        data_model: The envelope's data model.
        scope_path: The JSON Pointer of the current template item.
        index: The current 0-based template index, if any.
        id_suffix: Appended to ``id``/``child``/list-``children`` entries
            (``"-<i>"`` when baking a template clone; ``""`` otherwise).

    Returns:
        The baked component dict (v1.0 shape — top-level props).
    """
    dumped = component.model_dump(by_alias=True, mode="json", exclude_none=True)
    resolved = _resolve_value(
        dumped,
        data_model=data_model,
        scope_path=scope_path,
        index=index,
        optional_paths=_optional_paths(component),
    )
    resolved["id"] = f"{component.id}{id_suffix}"
    if id_suffix:
        if resolved.get("child"):
            resolved["child"] = f"{resolved['child']}{id_suffix}"
        if isinstance(resolved.get("children"), list):
            resolved["children"] = [f"{cid}{id_suffix}" for cid in resolved["children"]]
    return resolved


def _expand_template(
    template: ChildTemplate,
    *,
    by_id: dict[str, Component],
    data_model: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Expand a ``ChildTemplate`` into one baked clone per data-model list item.

    Args:
        template: The template (``componentId`` + ``path``).
        by_id: Every top-level component in the envelope, keyed by id.
        data_model: The envelope's data model.

    Returns:
        ``(clone_ids, clone_dicts)`` — the generated ids (for the parent's
        ``children``) and the baked clone dicts (appended to the flat output).

    Raises:
        BakeError: If the template component id is unknown, or ``path``
            does not resolve to a list.
    """
    template_component = by_id.get(template.component_id)
    if template_component is None:
        raise BakeError(
            f"ChildTemplate references unknown component id {template.component_id!r}."
        )
    jsonpointer = _load_jsonpointer()
    try:
        items = jsonpointer.resolve_pointer(data_model, template.path)
    except jsonpointer.JsonPointerException as exc:
        raise BakeError(
            f"ChildTemplate path {template.path!r} did not resolve: {exc}"
        ) from exc
    if not isinstance(items, list):
        raise BakeError(
            f"ChildTemplate path {template.path!r} must resolve to a list, "
            f"got {type(items)!r}."
        )

    clone_ids: list[str] = []
    clone_dicts: list[dict[str, Any]] = []
    for i in range(len(items)):
        clone = _bake_component(
            template_component,
            data_model=data_model,
            scope_path=f"{template.path}/{i}",
            index=i,
            id_suffix=f"-{i}",
        )
        clone_ids.append(clone["id"])
        clone_dicts.append(clone)
    return clone_ids, clone_dicts


def bake_envelope(envelope: CreateSurface) -> list[dict[str, Any]]:
    """Bake an envelope: resolve all bindings/calls, expand every template.

    Args:
        envelope: The ``createSurface`` envelope to bake.

    Returns:
        A flat list of resolved v1.0 component dicts (top-level props; every
        ``children: ChildTemplate`` replaced by concrete cloned-child ids)
        with zero live ``path``/``call`` expressions.

    Raises:
        BakeError: If any binding/call is unresolvable, a template's source
            component/path is invalid, or a live expression survives baking
            (post-condition guard).
        ImportError: If ``jsonpointer`` is unavailable (names the extra).
    """
    data_model = envelope.data_model
    by_id = {comp.id: comp for comp in envelope.components}
    template_source_ids = {
        comp.children.component_id
        for comp in envelope.components
        if isinstance(comp.children, ChildTemplate)
    }

    baked: list[dict[str, Any]] = []
    for comp in envelope.components:
        if comp.id in template_source_ids:
            continue  # consumed as a template pattern — never rendered standalone
        baked_comp = _bake_component(comp, data_model=data_model, scope_path="", index=None)
        if isinstance(comp.children, ChildTemplate):
            clone_ids, clone_dicts = _expand_template(
                comp.children, by_id=by_id, data_model=data_model
            )
            baked_comp["children"] = clone_ids
            baked.append(baked_comp)
            baked.extend(clone_dicts)
        else:
            baked.append(baked_comp)

    for entry in baked:
        if _has_live_binding(entry):  # pragma: no cover - defensive
            raise BakeError(
                f"Component {entry.get('id')!r} still contains a live binding "
                "after baking."
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
    now = datetime.now(UTC)
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
