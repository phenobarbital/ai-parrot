"""``parrot.outputs.a2ui.catalog.basic`` — vendored official A2UI v1.0 spec.

Ships the six official JSON Schema documents from
``google/A2UI@90157ec10f36cf8e192daa71c95d2684af20c756``
(``specification/v1_0/{catalogs/basic/catalog,json/common_types,
json/agent_to_renderer,json/renderer_to_agent,json/catalog_definition,
json/agent_capabilities}.json``), pinned by commit SHA, plus a
:func:`schema_registry` that resolves every ``$ref`` between them.

This is the ONLY module in ``parrot.outputs.a2ui`` that is allowed to depend
on the exact upstream document shapes — everything else (models, catalog
validation) is verified against these vendored copies, never fetched live.
:func:`load_spec` is the single read path; :func:`schema_registry` builds
the ``referencing.Registry`` jsonschema validators need.

One-way import rule (G8): this module MUST NEVER import from
``parrot.bots``, ``parrot.clients``, agents, or DatasetManager.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any, Literal

from referencing import Registry, Resource

from parrot.outputs.a2ui.catalog.base import FunctionDefinition

__all__ = [
    "BASIC_CATALOG_ID",
    "SPEC_COMMIT",
    "SPEC_FILES",
    "SpecName",
    "basic_components",
    "basic_functions",
    "load_spec",
    "schema_registry",
]

#: The official basic catalog's own ``$id`` (verified against the vendored
#: ``catalog.json``, spec §2/AC-G2).
BASIC_CATALOG_ID = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"

#: The pinned upstream commit every vendored document in ``spec/`` was
#: fetched from. Bumping this is a deliberate, changelog-worthy act (spec §7
#: Known Risks: "Drift de la spec").
SPEC_COMMIT = "90157ec10f36cf8e192daa71c95d2684af20c756"

_SPEC_DIR = Path(__file__).parent / "spec"

SpecName = Literal[
    "catalog",
    "common_types",
    "agent_to_renderer",
    "renderer_to_agent",
    "catalog_definition",
    "agent_capabilities",
]

#: Logical spec name -> vendored filename under ``spec/``.
SPEC_FILES: dict[SpecName, str] = {
    "catalog": "catalog.json",
    "common_types": "common_types.json",
    "agent_to_renderer": "agent_to_renderer.json",
    "renderer_to_agent": "renderer_to_agent.json",
    "catalog_definition": "catalog_definition.json",
    "agent_capabilities": "agent_capabilities.json",
}

#: ``agent_to_renderer.json``'s ``Component`` def and ``common_types.json``'s
#: ``FunctionCall`` def both ``$ref`` a relative ``"catalog.json#/$defs/..."``
#: — resolved (relative to THEIR OWN base ``$id``,
#: ``https://a2ui.org/specification/v1_0/{agent_to_renderer,common_types}.json``)
#: to ``https://a2ui.org/specification/v1_0/catalog.json``. That is NOT the
#: basic catalog's own ``$id`` (``BASIC_CATALOG_ID``, under
#: ``.../catalogs/basic/catalog.json``) — verified directly against the
#: pinned upstream documents. This is deliberate upstream design: the
#: message schemas are catalog-agnostic, and ``"catalog.json"`` is a
#: well-known relative alias for "whichever catalog is active", resolved by
#: whoever builds the registry for a given validation. Here, the only
#: catalog vendored is the basic one, so :func:`schema_registry` aliases it
#: under this id. TASK-2535's per-surface/per-message registry build on
#: this pattern to swap in the ACTUALLY-active catalog (basic or parrot).
_CATALOG_ALIAS_ID = "https://a2ui.org/specification/v1_0/catalog.json"


@functools.cache
def load_spec(name: SpecName) -> dict:
    """Load one of the six vendored, SHA-pinned A2UI v1.0 JSON Schemas.

    Args:
        name: One of ``"catalog"``, ``"common_types"``, ``"agent_to_renderer"``,
            ``"renderer_to_agent"``, ``"catalog_definition"``,
            ``"agent_capabilities"``.

    Returns:
        The parsed JSON Schema document. Cached — treat the result as
        read-only; callers must not mutate it.

    Raises:
        ValueError: If ``name`` is not a recognized spec name.
    """
    try:
        filename = SPEC_FILES[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown A2UI spec name {name!r}. Valid names: {sorted(SPEC_FILES)}."
        ) from exc
    path = _SPEC_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def schema_registry() -> Registry:
    """Build a ``referencing.Registry`` resolving every vendored ``$ref``.

    Registers all six vendored documents under their own ``$id``, plus the
    basic catalog a second time under the ``"catalog.json"`` relative-ref
    alias the message schemas actually resolve against (see
    ``_CATALOG_ALIAS_ID``).

    Returns:
        A ``referencing.Registry`` ready to back a
        ``jsonschema.Draft202012Validator``.
    """
    registry = Registry()
    for name in SPEC_FILES:
        doc = load_spec(name)
        registry = registry.with_resource(doc["$id"], Resource.from_contents(doc))
    registry = registry.with_resource(
        _CATALOG_ALIAS_ID, Resource.from_contents(load_spec("catalog"))
    )
    return registry


def _register_primitives() -> None:
    """Register the 18 official Basic Catalog primitives (TASK-2536).

    Imported and called once, below, at package import time. Local imports
    (rather than top-of-module) avoid a circular import: ``register_component``
    lives in the PARENT package (``parrot.outputs.a2ui.catalog``), which itself
    only ever imports ``catalog.basic`` lazily, inside function bodies (see
    ``catalog/__init__.py``'s ``_component_exists``/``validate_message``) —
    never at ITS OWN module top level — so by the time anything actually
    triggers this package's import, the parent is guaranteed fully loaded.

    None of the 18 primitives declare ``allowedParents``/``allowedChildren``
    in the vendored ``catalog.json`` (that constraint is only used by the
    reserved ``Surface`` container in ``common_types.json``, not by regular
    catalog components) — so none is passed here either.
    """
    from parrot.outputs.a2ui.catalog import register_component
    from parrot.outputs.a2ui.catalog.basic.inputs import (
        Button,
        CheckBox,
        ChoicePicker,
        DateTimeInput,
        Slider,
        TextField,
    )
    from parrot.outputs.a2ui.catalog.basic.layout import (
        Card,
        Column,
        Divider,
        List,
        Modal,
        Row,
        Tabs,
    )
    from parrot.outputs.a2ui.catalog.basic.media import (
        AudioPlayer,
        Icon,
        Image,
        Text,
        Video,
    )

    for cls in (
        Text,
        Image,
        Icon,
        Video,
        AudioPlayer,
        Row,
        Column,
        List,
        Card,
        Tabs,
        Modal,
        Divider,
        Button,
        TextField,
        CheckBox,
        ChoicePicker,
        Slider,
        DateTimeInput,
    ):
        register_component(
            cls.__name__, catalog_id=BASIC_CATALOG_ID, is_primitive=True
        )(cls)


def basic_components() -> list:
    """Return the :class:`ComponentDefinition` of every registered primitive.

    Ensures the 18 primitives are registered (idempotent — ``register_component``
    just overwrites the same entry) before listing them.

    Returns:
        The 18 Basic Catalog primitives' definitions, filtered from the full
        catalog registry.
    """
    from parrot.outputs.a2ui.catalog import list_components

    _register_primitives()
    return [d for d in list_components() if d.catalog_id == BASIC_CATALOG_ID]


def basic_functions() -> list[FunctionDefinition]:
    """Return the :class:`FunctionDefinition` of every official Basic Catalog function.

    Source of truth: the vendored ``catalog.json``'s ``functions`` object
    (TASK-2537's ``FunctionEvaluator`` implements their behavior; this just
    exposes their metadata). Also registers each into the catalog's function
    registry (idempotent — mirrors :func:`basic_components`'s registration
    side effect).

    Returns:
        The 14 Basic Catalog functions' definitions (name-sorted).
    """
    from parrot.outputs.a2ui.catalog import register_function

    definitions: list[FunctionDefinition] = []
    for name, spec in load_spec("catalog")["functions"].items():
        args_schema: dict[str, Any] = {}
        for sub in spec.get("allOf", []):
            args_prop = sub.get("properties", {}).get("args")
            if args_prop is not None:
                args_schema = args_prop
        definition = FunctionDefinition(
            name=name,
            catalog_id=BASIC_CATALOG_ID,
            args_schema=args_schema,
            return_type=spec.get("returnType", "any"),
            requires_user_activation=bool(spec.get("requiresUserActivation", False)),
        )
        register_function(definition)
        definitions.append(definition)
    return sorted(definitions, key=lambda d: d.name)


# Register the 18 primitives + 14 functions as soon as this package is
# imported, so that `parrot.outputs.a2ui.catalog`'s own resolution
# (`_component_exists` et al.) and any renderer/producer code can rely on
# them being present without every caller having to remember to call
# `basic_components()`/`basic_functions()` first.
_register_primitives()
basic_functions()
