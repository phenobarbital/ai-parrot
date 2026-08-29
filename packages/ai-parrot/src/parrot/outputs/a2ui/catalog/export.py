"""``export_catalog_definition`` — the parrot catalog's ``catalog_definition.json``
(Module 5, FEAT-470 TASK-2540).

Produces a document valid against the official ``catalog_definition.json``
schema (vendored, TASK-2534), describing the Parrot catalog
(:data:`~parrot.outputs.a2ui.catalog.base.DEFAULT_CATALOG_ID`) for consumption
by any A2UI-aware tool (LLM system prompt, external renderer catalog
resolution, ...). Basic Catalog components/functions are included by ``$ref``
(spec G2) rather than duplicated, so the Parrot catalog stays a thin overlay.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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

__all__ = ["export_catalog_definition", "write_catalog_definition"]


def export_catalog_definition(*, catalog_id: str = DEFAULT_CATALOG_ID, include_basic: bool = True) -> dict[str, Any]:
    """Build the catalog definition document for ``catalog_id`` (spec §2).

    Args:
        catalog_id: The catalog to export. Defaults to the Parrot catalog.
        include_basic: If ``True`` (default), every official Basic Catalog
            component/function is included as a ``$ref`` to
            ``catalog.json#/components/<Name>``/``#/functions/<Name>`` — so a
            bare component name (``"Text"``, ``"Button"``, ...) resolves
            under the Parrot catalog too (spec G2).

    Returns:
        A dict valid against the vendored ``catalog_definition.json`` schema
        (``protocolVersion``, ``catalogId``, ``instructions``, ``components``,
        ``functions``).
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
