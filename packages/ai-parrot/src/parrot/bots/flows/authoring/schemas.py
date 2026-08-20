"""JSON Schemas handed to the authoring model, and a schema-level check.

Two things a static ``model_json_schema()`` cannot express on its own:

* which node **kinds** are legal — that depends on the live
  ``NODE_REGISTRY`` and the chosen engine, and the registry is populated by
  import side effects, so it can only be known at call time;
* which **tools** exist — that is the catalog, which varies per install and
  per allowlist.

Injecting both as ``enum`` constraints turns "please do not invent names"
from a prompt instruction into something the schema itself states. Providers
with native structured output (OpenAI, Google, Groq) enforce the enum during
decoding, so a hallucinated tool name frequently cannot be produced at all
rather than being caught downstream.

:func:`validate_against_schema` is the explicit JSON-Schema pass, kept
separate from the Pydantic parse so a document can be checked before it is
coerced into a model — useful when reporting *why* a raw LLM response failed.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from .blueprint import (
    BlueprintNode,
    BlueprintSkeleton,
    BlueprintTransition,
    WorkflowBlueprint,
)
from .catalog import ComponentCatalog

__all__ = (
    "blueprint_json_schema",
    "node_config_json_schema",
    "node_json_schema",
    "skeleton_json_schema",
    "transitions_json_schema",
    "validate_against_schema",
)

logger = logging.getLogger(__name__)


def _inject_enum(schema: Dict[str, Any], pointer: Sequence[str], values: List[str]) -> None:
    """Set an ``enum`` on a nested property, if the path exists.

    Args:
        schema: The schema to mutate in place.
        pointer: Property names to walk, e.g. ``("nodes", "items", "kind")``.
        values: Allowed values. A no-op when empty — an empty enum would
            make every document invalid, which is worse than no constraint.
    """
    if not values:
        return
    node: Any = schema
    for key in pointer:
        if not isinstance(node, dict):
            return
        node = node.get(key)
        if node is None:
            return
    if isinstance(node, dict):
        node.pop("$ref", None)
        node.pop("allOf", None)
        node.pop("anyOf", None)
        node["type"] = "string"
        node["enum"] = values


def _properties(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return a schema's ``properties`` map, or an empty dict."""
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


def skeleton_json_schema(
    catalog: ComponentCatalog, *, engine: Optional[str] = None
) -> Dict[str, Any]:
    """Schema for the stage-1 skeleton, with ``kind`` constrained.

    Args:
        catalog: The live component catalog.
        engine: When given, restricts ``kind`` to that engine's node types.

    Returns:
        A JSON Schema document.
    """
    schema = BlueprintSkeleton.model_json_schema()
    kinds = (
        catalog.kinds_for(engine)
        if engine
        else sorted(set(catalog.kinds_for("crew")) | set(catalog.kinds_for("flow")))
    )
    # $defs carries NodeStub when the model is nested by reference.
    for defs in (schema.get("$defs") or {}).values():
        if isinstance(defs, dict) and "kind" in _properties(defs):
            _inject_enum(defs, ("properties", "kind"), kinds)
    _inject_enum(schema, ("properties", "nodes", "items", "properties", "kind"), kinds)
    return schema


def node_json_schema(
    catalog: ComponentCatalog,
    *,
    engine: str = "flow",
    kind: Optional[str] = None,
) -> Dict[str, Any]:
    """Schema for one authored node, constrained to what actually exists.

    Args:
        catalog: The live component catalog.
        engine: Compile target, deciding the legal node kinds.
        kind: When given, pins ``kind`` to this single value so the model
            cannot drift from the stub it was asked to author.

    Returns:
        A JSON Schema document.
    """
    schema = BlueprintNode.model_json_schema()
    kinds = [kind] if kind else catalog.kinds_for(engine)
    _inject_enum(schema, ("properties", "kind"), kinds)

    tool_names = sorted(catalog.tool_names())
    _inject_enum(schema, ("properties", "tool"), tool_names)
    _inject_enum(schema, ("properties", "tools", "items"), tool_names)
    if engine == "flow":
        _inject_enum(schema, ("properties", "agent_ref"), sorted(catalog.agent_names()))
    return schema


def transitions_json_schema(node_ids: Sequence[str]) -> Dict[str, Any]:
    """Schema for the transition list, with endpoints pinned to real nodes.

    Args:
        node_ids: The declared node ids.

    Returns:
        A JSON Schema for an object holding a ``transitions`` array.
    """
    transition = BlueprintTransition.model_json_schema()
    ids = list(node_ids)
    for prop in ("source", "target"):
        target = _properties(transition).get(prop)
        if isinstance(target, dict):
            target.pop("anyOf", None)
            target.pop("$ref", None)
            target.update(
                {
                    "anyOf": [
                        {"type": "string", "enum": ids},
                        {"type": "array", "items": {"type": "string", "enum": ids}},
                    ]
                }
            )
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["transitions"],
        "properties": {"transitions": {"type": "array", "items": transition}},
        "$defs": transition.pop("$defs", {}),
    }


def blueprint_json_schema(
    catalog: ComponentCatalog, *, engine: Optional[str] = None
) -> Dict[str, Any]:
    """Schema for a whole blueprint.

    Mostly useful for documentation and for validating a blueprint that
    arrived from outside the authoring loop; the loop itself constrains the
    smaller per-stage schemas.

    Args:
        catalog: The live component catalog.
        engine: When given, restricts node kinds to that engine.

    Returns:
        A JSON Schema document.
    """
    schema = WorkflowBlueprint.model_json_schema()
    kinds = (
        catalog.kinds_for(engine)
        if engine
        else sorted(set(catalog.kinds_for("crew")) | set(catalog.kinds_for("flow")))
    )
    tool_names = sorted(catalog.tool_names())
    for defs in (schema.get("$defs") or {}).values():
        if not isinstance(defs, dict):
            continue
        props = _properties(defs)
        if "kind" in props:
            _inject_enum(defs, ("properties", "kind"), kinds)
        if "tool" in props:
            _inject_enum(defs, ("properties", "tool"), tool_names)
        if "tools" in props:
            _inject_enum(defs, ("properties", "tools", "items"), tool_names)
    return schema


def node_config_json_schema(node_type: str) -> Optional[Dict[str, Any]]:
    """Return the JSON Schema of a node type's ``config`` block.

    Args:
        node_type: A ``NODE_REGISTRY`` key.

    Returns:
        The schema, or ``None`` when the type declares no config model.
    """
    from parrot.bots.flows.flow.flow import NODE_CONFIG_MODELS  # noqa: PLC0415

    model = NODE_CONFIG_MODELS.get(node_type)
    return model.model_json_schema() if model is not None else None


def validate_against_schema(
    document: Any, schema: Dict[str, Any]
) -> List[str]:
    """Validate ``document`` against ``schema``, returning error strings.

    Args:
        document: The parsed JSON document.
        schema: The JSON Schema to check against.

    Returns:
        Human-readable error messages, empty when the document conforms. If
        ``jsonschema`` is not installed the check is skipped and an empty
        list returned — the Pydantic parse still enforces the same shape, so
        the optional dependency only costs the nicer error text.
    """
    try:
        import jsonschema  # noqa: PLC0415
    except ImportError:  # pragma: no cover - optional dependency
        logger.debug("jsonschema not installed; skipping schema-level validation")
        return []

    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    ]
