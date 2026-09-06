"""A2UI component catalog — public decorator, lookup, and envelope validation.

Registration pattern mirrors :func:`parrot.outputs.formats.register_renderer`
(module-level registry dict + decorator that inserts and returns the class), with
the added registration-time enforcement of the mandatory ``lower()`` contract.

A registrable component class MUST:

* implement a callable ``lower(self, component, data_model) -> BasicTree``
  (pure and deterministic — golden-file tested in Module 3), UNLESS it
  registers with ``is_primitive=True`` (the 18 official Basic Catalog
  primitives, TASK-2536, which ARE the lowering target); and
* optionally expose class attributes ``SCHEMA`` (dict) and ``INSTRUCTIONS`` (str),
  which the decorator folds into the component's :class:`ComponentDefinition`.

v1.0 catalog resolution (spec §2 G2): a component without an explicit
``catalogId`` resolves against its surface's default ``catalogId``
(:func:`resolve_catalog`). The Parrot catalog (:data:`DEFAULT_CATALOG_ID`)
``$ref``-includes the official Basic Catalog by design, so a bare component
name (``"Text"``, ``"Button"``, ...) resolves under either — until TASK-2539
migrates the Parrot catalog's own components into the Python registry, the
Basic Catalog's 18 names are checked directly against the vendored
``catalog.json`` (the source of truth), not the (currently basic-empty)
Python registry.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable, Sequence
from typing import Any

import jsonschema

from parrot.outputs.a2ui.catalog.base import (
    ACTION_NOT_ALLOWED_FOR_LLM,
    CATALOG_UNRESOLVED,
    DANGLING_CHILD,
    DEFAULT_CATALOG_ID,
    DUPLICATE_ID,
    INLINE_DATA_NOT_ALLOWED_FOR_LLM,
    MISSING_ROOT,
    TOOL_ONLY_NOT_ALLOWED_FOR_LLM,
    UNALLOWED_CHILD,
    UNALLOWED_PARENT,
    UNKNOWN_COMPONENT,
    BasicNode,
    BasicTree,
    CatalogError,
    CatalogValidationError,
    ComponentContractError,
    ComponentDefinition,
    FunctionDefinition,
    ProducerOrigin,
    RegisteredComponent,
)
from parrot.outputs.a2ui.models import (
    A2UIAgentMessage,
    A2UIRendererMessage,
    ChildTemplate,
    Component,
    CreateSurface,
    UpdateComponents,
)

__all__ = [
    "DEFAULT_CATALOG_ID",
    "BasicNode",
    "BasicTree",
    "CatalogError",
    "CatalogValidationError",
    "ComponentContractError",
    "ComponentDefinition",
    "FunctionDefinition",
    "ProducerOrigin",
    "RegisteredComponent",
    "catalog_header_instructions",
    "catalog_instructions",
    "get_component",
    "get_function",
    "list_components",
    "list_functions",
    "register_component",
    "register_function",
    "resolve_catalog",
    "unregister_component",
    "validate_envelope",
    "validate_message",
]

logger = logging.getLogger(__name__)

#: Global component allowlist, keyed by ``(catalog_id, name)`` (FEAT-529 Module 0 —
#: was bare-name keyed; rekeyed so a second catalog may register the same name,
#: e.g. a future viz-core ``Chart`` alongside the Parrot ``Chart``).
_CATALOG: dict[tuple[str, str], RegisteredComponent] = {}

#: Global function allowlist, keyed by function name.
_FUNCTIONS: dict[str, FunctionDefinition] = {}

#: Structured-output components whose ``data``/``datasets`` prop MUST be a
#: ``{"path": ...}`` data-model binding — never an inline list — when the
#: envelope originates from the LLM producer (FEAT-473 G8). TOOL-origin
#: surfaces (the FEAT-473 core adapter) are exempt; they inline rows directly.
_STRUCTURED_INLINE_DATA_COMPONENTS = frozenset({"Chart", "DataTable", "Map"})
_STRUCTURED_INLINE_DATA_FIELDS = ("data", "datasets")


def register_component(
    name: str,
    *,
    requires_actions: bool = False,
    catalog_id: str = DEFAULT_CATALOG_ID,
    is_primitive: bool = False,
    allowed_parents: list[str] | None = None,
    allowed_children: list[str] | None = None,
    tool_only: bool = False,
) -> Callable[[type], type]:
    """Register a catalog component under ``name``.

    Enforces the mandatory lowering contract at registration time: a class without
    a callable ``lower()`` cannot register (raises :class:`ComponentContractError`)
    UNLESS ``is_primitive=True`` (spec G4).

    Args:
        name: The component type name used in envelopes (e.g. ``"Chart"``).
        requires_actions: Marks the component as action-bearing (D10b). LLM-produced
            envelopes containing it are rejected by :func:`validate_envelope`.
        catalog_id: Owning catalog id; defaults to the Parrot custom catalog.
        is_primitive: ``True`` for an official Basic Catalog primitive — no
            ``lower()`` is required.
        allowed_parents: If set, restricts which component types this one may
            appear under.
        allowed_children: If set, restricts which component types this one
            may contain as ``child``/``children``.
        tool_only: Marks the component as tool-only (FEAT-527). LLM-produced
            envelopes containing it are rejected by :func:`validate_envelope`
            (same gate mechanism as ``requires_actions``).

    Returns:
        The class decorator.

    Raises:
        ComponentContractError: If the decorated class lacks a callable ``lower()``
            and is not registered with ``is_primitive=True``.
        CatalogError: If ``(catalog_id, name)`` is already registered to a
            DIFFERENT class (FEAT-529 Module 0 — the SAME name in a
            DIFFERENT catalog is allowed and does not raise; re-registering
            the identical ``(catalog_id, name, cls)`` triple is a no-op,
            preserving the Basic Catalog's idempotent re-registration
            pattern, e.g. ``basic_components()`` calling
            ``_register_primitives()`` on every invocation).
    """

    def decorator(cls: type) -> type:
        lower = getattr(cls, "lower", None)
        if not is_primitive and not callable(lower):
            raise ComponentContractError(
                f"Component {name!r} ({cls.__name__}) cannot register: it must "
                "implement a callable lower(self, component, data_model) -> BasicTree "
                "(spec G4 — lowering is enforced, not conventional), unless "
                "registered with is_primitive=True."
            )
        key = (catalog_id, name)
        existing = _CATALOG.get(key)
        if existing is not None and existing.component_cls is not cls:
            raise CatalogError(
                f"Component {name!r} is already registered under catalog {catalog_id!r} "
                f"(by {existing.component_cls.__name__!r})."
            )
        definition = ComponentDefinition(
            name=name,
            catalog_id=catalog_id,
            schema=dict(getattr(cls, "SCHEMA", {}) or {}),
            instructions=str(getattr(cls, "INSTRUCTIONS", "") or ""),
            requires_actions=requires_actions,
            is_primitive=is_primitive,
            allowed_parents=allowed_parents,
            allowed_children=allowed_children,
            tool_only=tool_only,
        )
        _CATALOG[key] = RegisteredComponent(definition=definition, component_cls=cls)
        # Attach for convenient access from instances / renderers.
        cls.definition = definition  # type: ignore[attr-defined]
        logger.debug("Registered A2UI catalog component %r under catalog %r (%s)", name, catalog_id, cls.__name__)
        return cls

    return decorator


def unregister_component(name: str, catalog_id: str = DEFAULT_CATALOG_ID) -> None:
    """Remove a component from the catalog (primarily for test isolation).

    Args:
        name: The component name.
        catalog_id: The catalog it was registered under. Defaults to the
            Parrot catalog (matches :func:`register_component`'s default),
            so existing bare ``unregister_component(name)`` call sites keep
            working unchanged.
    """
    _CATALOG.pop((catalog_id, name), None)


def get_component(name: str, catalog_id: str | None = None) -> RegisteredComponent:
    """Return the registered component for ``name``.

    Args:
        name: The component name.
        catalog_id: When given, an exact ``(catalog_id, name)`` lookup. When
            omitted (the default — every pre-FEAT-529 call site), resolves
            to the unique catalog registering ``name``; if more than one
            catalog does, raises :class:`CatalogError` naming the candidates
            (FEAT-529 Module 0 — no name is ambiguous today; the
            ``a2ui-viz-core-charts`` sibling spec is expected to introduce
            the first one, at which point its call sites must pass
            ``catalog_id`` explicitly).

    Raises:
        KeyError: If ``name`` is not registered under ``catalog_id`` (when
            given), or not registered under ANY catalog (when omitted).
        CatalogError: If ``catalog_id`` is omitted and ``name`` is registered
            under more than one catalog.
    """
    if catalog_id is not None:
        try:
            return _CATALOG[(catalog_id, name)]
        except KeyError as exc:
            raise KeyError(f"No component {name!r} registered under catalog {catalog_id!r}.") from exc

    matches = [(cid, entry) for (cid, nm), entry in _CATALOG.items() if nm == name]
    if not matches:
        raise KeyError(name)
    if len(matches) > 1:
        candidates = sorted(cid for cid, _ in matches)
        error = CatalogError(
            f"Component name {name!r} is ambiguous: registered under multiple "
            f"catalogs {candidates}. Pass catalog_id= explicitly."
        )
        # Set post-construction (not a `CatalogError.__init__` kwarg — that
        # class is shared, untouched, base-catalog machinery, spec §7 out of
        # scope for this task) so callers can inspect the candidate ids
        # without parsing the message.
        error.candidates = candidates
        raise error
    return matches[0][1]


def list_components(catalog_id: str | None = None) -> list[ComponentDefinition]:
    """Return the definitions of registered components (name-sorted).

    Args:
        catalog_id: When given, only components registered under this
            catalog. ``None`` (default) returns every registered component
            across every catalog (today's behavior, preserved).
    """
    entries = _CATALOG.values()
    if catalog_id is not None:
        entries = [entry for entry in entries if entry.definition.catalog_id == catalog_id]
    return [entry.definition for entry in sorted(entries, key=lambda e: (e.definition.name, e.definition.catalog_id))]


def register_function(definition: FunctionDefinition) -> None:
    """Register a catalog function definition (primarily the Basic Catalog's 14).

    Args:
        definition: The function's :class:`FunctionDefinition`.
    """
    _FUNCTIONS[definition.name] = definition
    logger.debug("Registered A2UI catalog function %r", definition.name)


def get_function(name: str) -> FunctionDefinition:
    """Return the registered function definition for ``name``.

    Raises:
        KeyError: If ``name`` is not registered.
    """
    return _FUNCTIONS[name]


def list_functions() -> list[FunctionDefinition]:
    """Return all registered function definitions (name-sorted)."""
    return [d for _, d in sorted(_FUNCTIONS.items())]


def catalog_header_instructions(catalog_id: str) -> str | None:
    """Return ``catalog_id``'s own header-level instructions block, if any.

    Unlike a component's per-name ``instructions`` (folded into
    :func:`catalog_instructions` as ``"<name>: <instructions>"`` lines), a
    catalog HEADER is guidance that applies to the whole catalog regardless
    of which (or how many) of its components are registered — e.g. the
    viz-core catalog's nine guideline rules (FEAT-529 Module 0). The Parrot
    and Basic catalogs have no header today.

    Args:
        catalog_id: The catalog id.

    Returns:
        The header text, or ``None`` if that catalog declares no header.
    """
    from parrot.outputs.a2ui.catalog import viz_core  # local: see _component_exists note

    if catalog_id == viz_core.VIZ_CORE_CATALOG_ID:
        return viz_core.VIZ_CORE_INSTRUCTIONS
    return None


def catalog_instructions(catalog_ids: Sequence[str] | None = None) -> str:
    """Aggregate registered components' embedded ``instructions`` for the LLM producer.

    Args:
        catalog_ids: When given, scopes the aggregate to only these catalogs:
            each catalog's own header block (:func:`catalog_header_instructions`,
            if any) followed by ``"<name>: <instructions>"`` lines for
            components registered under one of these ids. ``None`` (default)
            aggregates every registered catalog (today's behavior), prefixed
            by the header of every catalog that declares one.

    Returns:
        A newline-joined instructions block.
    """
    # NOTE (bug fix, TASK-2535): a prior `.rstrip(": ")` here would silently
    # eat a legitimate trailing colon/space from an instructions string that
    # happened to end that way — `list_components()` is already filtered to
    # `d.instructions` truthy, so no stripping is needed at all.
    if catalog_ids is None:
        defs = list_components()
        header_ids = sorted({d.catalog_id for d in defs})
    else:
        catalog_id_set = set(catalog_ids)
        defs = [d for d in list_components() if d.catalog_id in catalog_id_set]
        header_ids = list(catalog_ids)

    headers = [h for h in (catalog_header_instructions(cid) for cid in header_ids) if h]
    lines = [f"{d.name}: {d.instructions}" for d in defs if d.instructions]
    return "\n".join([*headers, *lines])


def resolve_catalog(component_catalog_id: str | None, surface_catalog_id: str | None) -> str:
    """Resolve the effective catalog id for a component (spec §2 G2).

    Precedence: the component's own ``catalogId`` wins; otherwise the
    surface's default ``catalogId`` applies.

    Args:
        component_catalog_id: The component's own ``catalogId``, if any.
        surface_catalog_id: The surface's default ``catalogId``, if any.

    Returns:
        The resolved catalog id.

    Raises:
        CatalogValidationError: (code ``CATALOG_UNRESOLVED``) if neither is set.
    """
    resolved = component_catalog_id or surface_catalog_id
    if not resolved:
        raise CatalogValidationError(
            "Component has no catalogId and its surface has no default "
            "catalogId — cannot resolve which catalog to validate against.",
            code=CATALOG_UNRESOLVED,
        )
    return resolved


def _basic_component_names() -> frozenset[str]:
    """The 18 official Basic Catalog primitive names (source of truth: vendored JSON)."""
    from parrot.outputs.a2ui.catalog import basic  # local: see note below

    return frozenset(basic.load_spec("catalog")["components"].keys())


def _component_exists(name: str, resolved_catalog_id: str) -> bool:
    """Whether ``name`` is a known component under ``resolved_catalog_id``.

    Checks the vendored Basic Catalog JSON directly (source of truth, since
    the Python registry has no basic primitives registered until TASK-2536)
    and/or the Python registry (Parrot catalog components, TASK-2539+).
    Per spec G2, the Parrot catalog `$ref`-includes the Basic Catalog, so a
    component resolved against :data:`DEFAULT_CATALOG_ID` may be either.

    NOTE: ``parrot.outputs.a2ui.catalog.basic`` is imported LOCALLY (here and
    in :func:`_basic_component_names`/:func:`validate_message`), never at
    this module's top level. ``catalog.basic`` (TASK-2536) registers its 18
    primitives via ``register_component`` from THIS module at its own
    import time — a top-level ``from parrot.outputs.a2ui.catalog import
    basic`` here would deadlock that as a circular import (this module
    would not yet have defined ``register_component`` when ``catalog.basic``
    tries to import it back).
    """
    from parrot.outputs.a2ui.catalog import basic

    if resolved_catalog_id == basic.BASIC_CATALOG_ID:
        return name in _basic_component_names()
    if resolved_catalog_id == DEFAULT_CATALOG_ID:
        if name in _basic_component_names():
            return True
        return (DEFAULT_CATALOG_ID, name) in _CATALOG
    return (resolved_catalog_id, name) in _CATALOG


#: Serializes access to :func:`_unicode_aware_jsonschema`'s module-global patch
#: (jsonschema itself has no per-call regex-engine hook — see its docstring).
_UNICODE_JSONSCHEMA_LOCK = threading.Lock()


@contextlib.contextmanager
def _unicode_aware_jsonschema():
    """Patch ``jsonschema``'s internal ``re`` references to a Unicode-property-aware engine.

    The vendored ``common_types.json#/$defs/Extensions`` pattern
    (``^[\\p{XID_Start}_][\\p{XID_Continue}]*$``, spec §7 "claves UAX #31")
    uses PCRE/ECMA-style ``\\p{}`` Unicode property escapes that Python's
    stdlib ``re`` module does not support (``re.error: bad escape \\p``).
    ``jsonschema``'s ``pattern``/``patternProperties``/``additionalProperties``/
    ``unevaluatedProperties`` keywords all resolve this pattern via plain
    module-level ``re`` references in ``jsonschema._keywords``/
    ``jsonschema._utils`` — with no per-call regex-engine hook to override
    instead. Every envelope carrying a non-empty ``metadata.extensions``
    (i.e. virtually every LOWERED Parrot-catalog component — this is how
    presentation semantics like ``parrot_role``/``parrot_variant`` are
    carried, spec G4) would otherwise crash validation entirely instead of
    passing/failing it (surfaced by TASK-2548's conformance sweep — this was
    never previously exercised because ``test_validate_message_agent_to_renderer``,
    TASK-2535, only ever validated a plain ``BASIC_CATALOG_ID`` envelope with
    no ``metadata.extensions``).

    Swaps in the ``regex`` package (drop-in ``re``-API-compatible, supports
    ``\\p{}``) for the duration of one ``validate_message`` call when
    importable — restored in a ``finally`` (lock-serialized: this mutates
    shared module state, so concurrent callers must not interleave the
    swap). A no-op when ``regex`` is unavailable (only patterns that use
    ``\\p{}`` were ever broken; everything else validates exactly as before).
    """
    try:
        import regex as _regex
    except ImportError:
        yield
        return

    import jsonschema._keywords as _kw
    import jsonschema._utils as _ut

    with _UNICODE_JSONSCHEMA_LOCK:
        original = (_kw.re, _ut.re)
        _kw.re, _ut.re = _regex, _regex
        try:
            yield
        finally:
            _kw.re, _ut.re = original


def validate_message(message: A2UIAgentMessage | A2UIRendererMessage) -> None:
    """Validate a full v1.0 envelope against the official wire JSON Schemas.

    Args:
        message: An :class:`A2UIAgentMessage` or :class:`A2UIRendererMessage`.

    Raises:
        TypeError: If ``message`` is neither envelope type.
        jsonschema.exceptions.ValidationError: If it does not match the
            corresponding official schema (``agent_to_renderer.json`` /
            ``renderer_to_agent.json``).
    """
    from parrot.outputs.a2ui.catalog import basic
    from parrot.outputs.a2ui.serialization import serialize

    if isinstance(message, A2UIAgentMessage):
        schema_name = "agent_to_renderer"
    elif isinstance(message, A2UIRendererMessage):
        schema_name = "renderer_to_agent"
    else:
        raise TypeError(
            f"validate_message expects an A2UIAgentMessage or A2UIRendererMessage, " f"got {type(message)!r}."
        )

    payload = serialize(message)
    schema = basic.load_spec(schema_name)
    registry = basic.schema_registry()
    validator_cls = jsonschema.validators.validator_for(schema)
    with _unicode_aware_jsonschema():
        validator_cls(schema, registry=registry).validate(payload)


def _child_ids(component: Component) -> list[str]:
    """Every child component id ``component`` references (``child``/``children``)."""
    ids: list[str] = []
    if component.child is not None:
        ids.append(component.child)
    if isinstance(component.children, list):
        ids.extend(component.children)
    elif isinstance(component.children, ChildTemplate):
        ids.append(component.children.component_id)
    return ids


def validate_envelope(
    envelope: CreateSurface | UpdateComponents,
    *,
    origin: ProducerOrigin = ProducerOrigin.TOOL,
    surface_catalog_id: str | None = None,
) -> None:
    """Validate a v1.0 envelope's components against the catalog + structure rules.

    Reports ALL problems found (not just the first), so a producer's retry
    loop can re-prompt with full error context (spec §7).

    Checks:

    * Every component's ``catalogId`` resolves (:func:`resolve_catalog`) and
      names a known component (``UNKNOWN_COMPONENT``/``CATALOG_UNRESOLVED``).
    * Exactly one component has ``id == "root"`` (``MISSING_ROOT``).
    * No two components share an ``id`` (``DUPLICATE_ID``).
    * Every ``child``/``children`` reference points at an existing id
      (``DANGLING_CHILD``).
    * ``allowed_parents``/``allowed_children`` (when declared) are respected
      (``UNALLOWED_PARENT``/``UNALLOWED_CHILD``).
    * For ``origin=LLM``, no component carries a non-null ``action`` OR is
      registered with ``requires_actions=True``
      (``ACTION_NOT_ALLOWED_FOR_LLM`` — G2/D10b gate).
    * For ``origin=LLM``, no component is registered with ``tool_only=True``
      (``TOOL_ONLY_NOT_ALLOWED_FOR_LLM`` — FEAT-527 gate; e.g.
      ``HtmlDocument``, which carries raw HTML and may only be emitted by
      deterministic tool producers).
    * For ``origin=LLM``, ``Chart``/``DataTable``/``Map`` components do not
      inline a ``data``/``datasets`` row list — only a ``{"path": ...}``
      data-model binding is allowed (``INLINE_DATA_NOT_ALLOWED_FOR_LLM`` —
      FEAT-473 G8 gate; ``origin=TOOL`` surfaces, e.g. the structured-output
      adapter, are exempt and may inline rows directly).

    Args:
        envelope: The :class:`CreateSurface`/:class:`UpdateComponents` envelope.
        origin: Producer origin. The action gate applies ONLY to
            :attr:`ProducerOrigin.LLM` envelopes.
        surface_catalog_id: The owning surface's default ``catalogId``. If
            omitted, falls back to ``envelope.catalog_id`` when present
            (``CreateSurface`` carries it; ``UpdateComponents`` does not, so
            callers updating an existing surface should pass it explicitly).

    Raises:
        CatalogValidationError: Aggregating every problem found, via ``.issues``.
    """
    effective_surface_catalog_id = surface_catalog_id or getattr(envelope, "catalog_id", None)

    components = envelope.components
    ids = [c.id for c in components]
    id_counts: dict[str, int] = {}
    for cid in ids:
        id_counts[cid] = id_counts.get(cid, 0) + 1

    issues: list[dict[str, Any]] = []
    unknown_components: list[str] = []
    action_components: list[str] = []
    #: component id -> its resolved catalog id (FEAT-529 Module 0 — populated
    #: below as each component's catalog is resolved, so the keyed registry
    #: lookups later in this function use the SAME resolution instead of a
    #: bare-name `_CATALOG.get`, which would silently pick whichever catalog
    #: happened to insert last once names may collide across catalogs).
    resolved_catalog_by_id: dict[str, str] = {}

    if "root" not in ids:
        issues.append(
            {
                "code": MISSING_ROOT,
                "message": "No component with id 'root' found in the envelope.",
                "path": None,
            }
        )
    for cid, count in id_counts.items():
        if count > 1:
            issues.append(
                {
                    "code": DUPLICATE_ID,
                    "message": f"Component id {cid!r} is used {count} times.",
                    "path": cid,
                }
            )

    id_set = set(ids)
    for comp in components:
        for child_id in _child_ids(comp):
            if child_id not in id_set:
                issues.append(
                    {
                        "code": DANGLING_CHILD,
                        "message": f"Component {comp.id!r} references nonexistent child {child_id!r}.",
                        "path": comp.id,
                    }
                )

        resolved_catalog_id: str | None
        try:
            resolved_catalog_id = resolve_catalog(comp.catalog_id, effective_surface_catalog_id)
        except CatalogValidationError as exc:
            resolved_catalog_id = None
            issues.append({"code": exc.code, "message": str(exc), "path": comp.id})
        else:
            resolved_catalog_by_id[comp.id] = resolved_catalog_id
            if not _component_exists(comp.component, resolved_catalog_id):
                unknown_components.append(comp.component)
                issues.append(
                    {
                        "code": UNKNOWN_COMPONENT,
                        "message": (
                            f"Component {comp.component!r} (id={comp.id!r}) is not "
                            f"registered under catalog {resolved_catalog_id!r}."
                        ),
                        "path": comp.id,
                    }
                )

        # Keyed lookup (FEAT-529 Module 0): resolve against the SAME catalog id
        # just computed above, not a bare-name `_CATALOG.get` — a name may now
        # be registered under more than one catalog.
        entry_for_gate = _CATALOG.get((resolved_catalog_id, comp.component)) if resolved_catalog_id else None
        is_action_bearing = comp.action is not None or (
            entry_for_gate is not None and entry_for_gate.definition.requires_actions
        )
        if origin is ProducerOrigin.LLM and is_action_bearing:
            action_components.append(comp.component)
            issues.append(
                {
                    "code": ACTION_NOT_ALLOWED_FOR_LLM,
                    "message": (
                        f"LLM-produced envelopes may not contain an 'action' "
                        f"(component {comp.component!r}, id={comp.id!r})."
                    ),
                    "path": comp.id,
                }
            )

        if origin is ProducerOrigin.LLM and entry_for_gate is not None and entry_for_gate.definition.tool_only:
            issues.append(
                {
                    "code": TOOL_ONLY_NOT_ALLOWED_FOR_LLM,
                    "message": (
                        f"Component {comp.component!r} (id={comp.id!r}) is tool-only and "
                        "cannot appear in an LLM-produced envelope."
                    ),
                    "path": comp.id,
                }
            )

        if origin is ProducerOrigin.LLM and comp.component in _STRUCTURED_INLINE_DATA_COMPONENTS:
            extra = comp.model_extra or {}
            for field in _STRUCTURED_INLINE_DATA_FIELDS:
                if isinstance(extra.get(field), list):
                    issues.append(
                        {
                            "code": INLINE_DATA_NOT_ALLOWED_FOR_LLM,
                            "message": (
                                f"LLM-produced envelopes may not inline '{field}' rows on "
                                f"{comp.component!r} (id={comp.id!r}); use a "
                                '{"path": "/pointer"} data-model binding instead.'
                            ),
                            "path": comp.id,
                        }
                    )
            # Bug fix (post-review): a Map's OWN top-level `data`/`datasets`
            # is rarely used — the real per-component row binding for Map
            # lives PER-LAYER at `layers[i].data` (spec §2, /layers/<i>/features).
            # The top-level-only check above never inspected this nested
            # binding, so an LLM-origin envelope inlining rows under
            # `layers[i].data` was never rejected. Check it explicitly.
            if comp.component == "Map":
                for i, layer in enumerate(extra.get("layers") or []):
                    if isinstance(layer, dict) and isinstance(layer.get("data"), list):
                        issues.append(
                            {
                                "code": INLINE_DATA_NOT_ALLOWED_FOR_LLM,
                                "message": (
                                    f"LLM-produced envelopes may not inline 'data' rows on "
                                    f"Map layer {i} (id={comp.id!r}); use a "
                                    '{"path": "/pointer"} data-model binding instead.'
                                ),
                                "path": comp.id,
                            }
                        )

    by_id = {c.id: c for c in components}
    for comp in components:
        resolved = resolved_catalog_by_id.get(comp.id)
        entry = _CATALOG.get((resolved, comp.component)) if resolved else None
        allowed_children = entry.definition.allowed_children if entry else None
        for child_id in _child_ids(comp):
            child_comp = by_id.get(child_id)
            if child_comp is None:
                continue  # already reported as DANGLING_CHILD
            if allowed_children is not None and child_comp.component not in allowed_children:
                issues.append(
                    {
                        "code": UNALLOWED_CHILD,
                        "message": (
                            f"Component {comp.component!r} (id={comp.id!r}) does not "
                            f"allow child {child_comp.component!r} (id={child_id!r})."
                        ),
                        "path": comp.id,
                    }
                )
            child_resolved = resolved_catalog_by_id.get(child_comp.id)
            child_entry = _CATALOG.get((child_resolved, child_comp.component)) if child_resolved else None
            allowed_parents = child_entry.definition.allowed_parents if child_entry else None
            if allowed_parents is not None and comp.component not in allowed_parents:
                issues.append(
                    {
                        "code": UNALLOWED_PARENT,
                        "message": (
                            f"Component {child_comp.component!r} (id={child_id!r}) does "
                            f"not allow parent {comp.component!r} (id={comp.id!r})."
                        ),
                        "path": child_id,
                    }
                )

    if issues:
        summary = "; ".join(f"{i['code']}: {i['message']}" for i in issues)
        raise CatalogValidationError(
            summary,
            issues=issues,
            unknown_components=sorted(set(unknown_components)),
            action_components=sorted(set(action_components)),
        )
