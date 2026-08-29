"""``export_catalog_definition`` — the parrot catalog's ``catalog_definition.json``
(Module 5, FEAT-470 TASK-2540); ``export_functions``/``agent_capabilities``
(FEAT-469 TASK-2571, spec §3 Module 4, goal G4).

Produces a document valid against the official ``catalog_definition.json``
schema (vendored, TASK-2534), describing the Parrot catalog
(:data:`~parrot.outputs.a2ui.catalog.base.DEFAULT_CATALOG_ID`) for consumption
by any A2UI-aware tool (LLM system prompt, external renderer catalog
resolution, ...). Basic Catalog components/functions are included by ``$ref``
(spec G2) rather than duplicated, so the Parrot catalog stays a thin overlay.

``export_functions()`` adds a THIRD source to the ``functions`` map: the
agent's own tools (a ``FunctionExecutor``, spec §2/G1). It never imports
``parrot.tools``/``parrot.memory`` — it only depends on the
``FunctionExecutor`` protocol's return type
(:class:`~parrot.outputs.a2ui.catalog.base.FunctionDefinition`), preserving
G8.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from parrot.outputs.a2ui.catalog import (
    catalog_instructions,
    list_components,
    list_functions,
)
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog.basic import (
    BASIC_CATALOG_ID,
    basic_components,
    load_spec,
)

if TYPE_CHECKING:  # pragma: no cover - import-rule guard (G8)
    from parrot.outputs.a2ui.runtime import FunctionExecutor

__all__ = [
    "agent_capabilities",
    "export_catalog_definition",
    "export_functions",
    "write_catalog_definition",
]

logger = logging.getLogger(__name__)


def _is_xid_start_char(ch: str) -> bool:
    """True if ``ch`` alone is already a valid Python identifier (UAX #31 XID_Start-ish)."""
    return ch.isidentifier()


def _is_xid_continue_char(ch: str) -> bool:
    """True if ``ch`` is valid as a NON-leading identifier character (UAX #31 XID_Continue).

    A lone digit/combining char is not itself a valid identifier (fails
    ``isidentifier()``), but IS valid after a leading letter — probing with a
    harmless prefix (``"a"``) distinguishes "valid continuation char" from
    "not an identifier character at all" without hand-rolling Unicode tables.
    """
    probe = "a" + ch
    return len(probe) == 2 and probe.isidentifier()


def _sanitize_uax31_name(name: str) -> str:
    """Sanitize ``name`` into a UAX #31-conformant identifier.

    A2UI function names must be valid identifiers; ai-parrot tool names
    routinely contain ``-``/``.``. Every character that would break
    ``str.isidentifier()`` is replaced with ``_``, distinguishing the leading
    character (must satisfy XID_Start) from the rest (XID_Continue is more
    permissive — digits are fine there, not as the first character).

    Args:
        name: The original tool/function name.

    Returns:
        A UAX #31-conformant name. Idempotent: returns ``name`` unchanged if
        it is already a valid identifier.
    """
    if name.isidentifier():
        return name

    out: list[str] = []
    for index, ch in enumerate(name):
        if index == 0:
            out.append(ch if _is_xid_start_char(ch) else "_")
        else:
            out.append(ch if _is_xid_continue_char(ch) else "_")
    candidate = "".join(out)

    if not candidate or not candidate.isidentifier():
        # Extremely unlikely fallback (e.g. an empty/all-symbol name).
        candidate = f"fn_{abs(hash(name)) % 10**8}"
    return candidate


def export_functions(executor: FunctionExecutor) -> dict[str, dict[str, Any]]:
    """Export ``executor``'s tools as A2UI ``functions`` (spec §2/G4).

    Names are sanitized to UAX #31 identifiers when needed (a warning is
    logged per sanitized name); the caller must NOT assume the returned keys
    equal ``FunctionDefinition.name`` verbatim. A tool whose (possibly
    sanitized) name collides with a Basic Catalog function, an existing
    parrot-catalog function, or another tool (post-sanitization) is a hard
    error — a silent overwrite would let a renderer invoke the wrong
    function.

    Tools already excluded from ``executor.list_functions()`` (i.e.
    ``a2ui_hidden=True``, TASK-2570) never reach this function at all.

    Args:
        executor: The agent's ``FunctionExecutor`` (``ToolManagerExecutor`` in
            production).

    Returns:
        ``{name: {..args schema.., "returnType", "allowedCallers",
        "requiresUserActivation"}}`` — the same flat shape
        :func:`export_catalog_definition` already uses for catalog-registered
        functions (``catalog_definition.json#/$defs/FunctionDefinition`` has
        ``unevaluatedProperties: false``, so the args schema keys and the
        three metadata keys must sit at the same level).

    Raises:
        ValueError: On any name collision (Basic Catalog, parrot catalog, or
            another tool after sanitization).
    """
    basic_names = set(load_spec("catalog")["functions"].keys())
    catalog_names = {definition.name for definition in list_functions()}

    functions: dict[str, dict[str, Any]] = {}
    sanitized_from: dict[str, str] = {}

    for definition in executor.list_functions():
        original_name = definition.name
        sanitized = _sanitize_uax31_name(original_name)
        if sanitized != original_name:
            logger.warning(
                "Sanitized A2UI function name %r -> %r to satisfy UAX #31 (Unicode identifier syntax).",
                original_name,
                sanitized,
            )

        if sanitized in basic_names or sanitized in catalog_names:
            raise ValueError(
                f"A2UI function name collision: tool {original_name!r} (exported as {sanitized!r}) "
                "collides with an existing Basic Catalog or parrot-catalog function."
            )
        if sanitized in sanitized_from:
            raise ValueError(
                f"A2UI function name collision after UAX #31 sanitization: "
                f"{sanitized_from[sanitized]!r} and {original_name!r} both sanitize to {sanitized!r}."
            )
        sanitized_from[sanitized] = original_name

        # `catalog_definition.json#/$defs/FunctionDefinition`'s third `allOf`
        # branch: `requiresUserActivation: true` FORCES `allowedCallers` to
        # `"rendererOnly"` (verified against the vendored schema AND the
        # Basic Catalog's own `openUrl`, which sets `requiresUserActivation:
        # true` and omits `allowedCallers` entirely, defaulting to
        # `"rendererOnly"`). A gesture-gated function has no "user
        # activation" context when the agent would invoke it itself, so this
        # is a real defense-in-depth constraint, not an arbitrary schema
        # quirk — do not set "rendererOrAgent" here when
        # `requires_user_activation` is true.
        allowed_callers = "rendererOnly" if definition.requires_user_activation else "rendererOrAgent"

        # `catalog_definition.json#/$defs/FunctionDefinition`'s FIRST `allOf`
        # branch is `FunctionCallValidationSchema` — a META-schema requiring
        # the flattened dict to describe a wire-level `{call, args}` FunctionCall
        # object (`properties.call = {"const": <name>}`, `properties.args` = the
        # tool's own argument schema), NOT a bare params schema at the top
        # level (verified: `{"type":"object","properties":{"location":...}}}`
        # alone fails `oneOf` — confirmed against the Basic Catalog's own
        # `openUrl`, which wraps its args the same way).
        functions[sanitized] = {
            "type": "object",
            "properties": {
                "call": {"const": sanitized},
                "args": dict(definition.args_schema) if definition.args_schema else {"type": "object"},
            },
            "required": ["call"],
            "additionalProperties": False,
            "returnType": definition.return_type,
            "allowedCallers": allowed_callers,
            "requiresUserActivation": definition.requires_user_activation,
        }

    return functions


def agent_capabilities(catalog_ids: list[str]) -> dict[str, Any]:
    """Build the ``agent_capabilities`` document (spec §2, G5).

    Args:
        catalog_ids: The catalog ids this agent supports (e.g.
            ``[DEFAULT_CATALOG_ID, BASIC_CATALOG_ID]``).

    Returns:
        A dict valid against the vendored ``agent_capabilities.json`` schema.
        ``acceptsInlineCatalogs`` is hard ``False`` — spec §1 Non-Goals
        excludes the renderer's ``inlineCatalogs`` function.
    """
    return {
        "v1.0": {
            "supportedCatalogIds": list(catalog_ids),
            "acceptsInlineCatalogs": False,
        }
    }


def export_catalog_definition(
    *,
    catalog_id: str = DEFAULT_CATALOG_ID,
    include_basic: bool = True,
    executor: FunctionExecutor | None = None,
) -> dict[str, Any]:
    """Build the catalog definition document for ``catalog_id`` (spec §2).

    Args:
        catalog_id: The catalog to export. Defaults to the Parrot catalog.
        include_basic: If ``True`` (default), every official Basic Catalog
            component/function is included as a ``$ref`` to
            ``catalog.json#/components/<Name>``/``#/functions/<Name>`` — so a
            bare component name (``"Text"``, ``"Button"``, ...) resolves
            under the Parrot catalog too (spec G2).
        executor: Optional ``FunctionExecutor`` (spec §2/G4, FEAT-469). When
            given, :func:`export_functions` is merged into ``functions`` —
            the agent's own tools become part of the exported document. Any
            collision with an existing (Basic or parrot-catalog) function
            name is a hard error.

    Returns:
        A dict valid against the vendored ``catalog_definition.json`` schema
        (``protocolVersion``, ``catalogId``, ``instructions``, ``components``,
        ``functions``).

    Raises:
        ValueError: If ``executor`` is given and a tool function name
            collides with an existing catalog function.
    """
    components: dict[str, Any] = {}
    functions: dict[str, Any] = {}

    if include_basic:
        for definition in basic_components():
            components[definition.name] = {"$ref": f"{BASIC_CATALOG_ID}#/components/{definition.name}"}
        # Functions' schema (`catalog_definition.json#/$defs/FunctionDefinition`)
        # requires an inline `returnType` (`unevaluatedProperties: false`) — a
        # bare `$ref` doesn't satisfy it the way a component `$ref` does.
        # Copy the official function definitions verbatim (known-valid, since
        # they ARE the schema's own source) instead.
        basic_functions_spec = load_spec("catalog")["functions"]
        for name, spec in basic_functions_spec.items():
            functions[name] = spec

    for definition in list_components():
        if definition.catalog_id != catalog_id or definition.is_primitive:
            continue
        schema: dict[str, Any] = dict(definition.schema_) if definition.schema_ else {"type": "object"}
        if definition.allowed_parents is not None:
            schema["allowedParents"] = list(definition.allowed_parents)
        if definition.allowed_children is not None:
            schema["allowedChildren"] = list(definition.allowed_children)
        components[definition.name] = schema

    for fn_definition in list_functions():
        if fn_definition.catalog_id != catalog_id:
            continue
        functions[fn_definition.name] = {
            **(dict(fn_definition.args_schema) if fn_definition.args_schema else {"type": "object"}),
            "returnType": fn_definition.return_type,
            "allowedCallers": fn_definition.allowed_callers,
            "requiresUserActivation": fn_definition.requires_user_activation,
        }

    if executor is not None:
        for name, spec in export_functions(executor).items():
            if name in functions:
                raise ValueError(
                    f"A2UI function name collision: tool function {name!r} collides with an "
                    "existing Basic Catalog or parrot-catalog function."
                )
            functions[name] = spec

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "protocolVersion": "1.0",
        "catalogId": catalog_id,
        "instructions": catalog_instructions(),
        "components": components,
        "functions": functions,
    }


def write_catalog_definition(path: Path) -> None:
    """Write :func:`export_catalog_definition`'s output to ``path`` as JSON.

    Args:
        path: The destination file path.
    """
    import json

    path.write_text(json.dumps(export_catalog_definition(), indent=2, sort_keys=True) + "\n")
