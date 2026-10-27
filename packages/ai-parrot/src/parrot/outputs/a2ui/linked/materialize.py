"""Pure helpers that turn a chat turn into a linked-widget origin (FEAT-757).

No I/O and no LLM: the origin is read from the turn's recorded tool invocations, the component from the
envelope the caller already holds.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.memory.compaction.models import ToolInvocation, ToolStatus

__all__ = [
    "EXECUTE_TOOL", "LINKED_TOOLS", "NEUTRAL_TOOLS", "SUPPORTED_ROOTS", "REQUEST_KEYS",
    "REASON_TURN_NOT_FOUND", "REASON_NO_SLUG_ORIGIN", "REASON_MULTI_SOURCE_TURN", "REASON_UNSUPPORTED_COMPONENT",
    "REASON_NO_ENVELOPE", "REASON_NO_QUERYSOURCE_TOOLKIT", "REASON_BUILD_FAILED", "REASON_NO_PUBLISH_SURFACE",
    "REASON_PIN_FAILED",
    "SlugOrigin", "OriginOutcome", "MaterializeWidgetResult", "extract_slug_origin", "component_from_envelope",
]

EXECUTE_TOOL = "qs_execute_slug"
LINKED_TOOLS: frozenset[str] = frozenset({"qs_build_linked_surface", "qs_build_linked_dashboard"})
#: Read-only tools tolerated between the query and the answer (spec §8 Q3). Anything else invalidates the origin.
NEUTRAL_TOOLS: frozenset[str] = frozenset({
    "qs_list_slugs", "qs_describe_slug", "qs_get_dialect_reference", "qs_list_components", "qs_validate_pipeline",
    "read_omitted_content", "search_tools",
    "list_skill_commands", "load_skill", "read_skill_asset", "search_skills", "read_skill", "list_skills",
})
SUPPORTED_ROOTS: frozenset[str] = frozenset({"Chart", "DataTable", "KPICard"})
#: qs_execute_slug args carried into build_linked_surface's ``request`` (offset/refresh are dropped on purpose).
REQUEST_KEYS: tuple[str, ...] = ("placeholders", "filter", "fields", "ordering", "grouping", "limit")

REASON_TURN_NOT_FOUND = "turn_not_found"
REASON_NO_SLUG_ORIGIN = "no_slug_origin"
REASON_MULTI_SOURCE_TURN = "multi_source_turn"
REASON_UNSUPPORTED_COMPONENT = "unsupported_component"
REASON_NO_ENVELOPE = "no_envelope"
REASON_NO_QUERYSOURCE_TOOLKIT = "no_querysource_toolkit"
REASON_BUILD_FAILED = "build_failed"
REASON_NO_PUBLISH_SURFACE = "no_publish_surface"
REASON_PIN_FAILED = "pin_failed"


class SlugOrigin(BaseModel):
    """The re-runnable data origin of a turn: one query slug plus its request."""

    slug: str
    tenant: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)


class OriginOutcome(BaseModel):
    """Result of :func:`extract_slug_origin`."""

    kind: Literal["slug", "already_linked", "multi_source", "none"]
    origin: SlugOrigin | None = None


class MaterializeWidgetResult(BaseModel):
    """What ``materialize_widget`` returns (spec §2 Data Models)."""

    status: Literal["materialized", "already_linked", "snapshot_only", "not_materializable"]
    reason: str | None = None
    message: str | None = None
    a2ui_envelope: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    surface_id: str | None = None
    pinned: bool = False
    refreshable: bool = False
    origin: SlugOrigin | None = None


def extract_slug_origin(invocations: Sequence[ToolInvocation]) -> OriginOutcome:
    """Decide a turn's data origin from its recorded tool invocations.

    Rules, in order: ignore invocations whose ``status`` is not ``ToolStatus.COMPLETED``; if any remaining
    invocation is outside ``NEUTRAL_TOOLS | LINKED_TOOLS | {EXECUTE_TOOL}`` -> ``none``; if the last relevant
    invocation is in ``LINKED_TOOLS`` -> ``already_linked``; collect ``qs_execute_slug`` origins — zero -> ``none``,
    more than one distinct origin -> ``multi_source``, otherwise ``slug`` with the last one.
    """
    completed = [invocation for invocation in invocations if invocation.status == ToolStatus.COMPLETED]
    allowed_tools = NEUTRAL_TOOLS | LINKED_TOOLS | {EXECUTE_TOOL}
    if any(invocation.tool_name not in allowed_tools for invocation in completed):
        return OriginOutcome(kind="none")

    origins: list[SlugOrigin] = []
    relevant: list[ToolInvocation] = []
    for invocation in completed:
        if invocation.tool_name not in LINKED_TOOLS | {EXECUTE_TOOL}:
            continue
        relevant.append(invocation)
        if invocation.tool_name != EXECUTE_TOOL:
            continue
        if "input" in invocation.omitted or not isinstance(invocation.input.get("slug"), str):
            return OriginOutcome(kind="none")
        origins.append(_origin_from_input(invocation.input))

    if relevant and relevant[-1].tool_name in LINKED_TOOLS:
        return OriginOutcome(kind="already_linked")
    if not origins:
        return OriginOutcome(kind="none")
    if len({origin.model_dump_json() for origin in origins}) > 1:
        return OriginOutcome(kind="multi_source")
    return OriginOutcome(kind="slug", origin=origins[-1])


def _origin_from_input(data: Mapping[str, Any]) -> SlugOrigin:
    """Build a SlugOrigin from a qs_execute_slug ``input`` dict, keeping only non-empty REQUEST_KEYS."""
    request = {key: data[key] for key in REQUEST_KEYS if data.get(key) not in (None, {}, [])}
    return SlugOrigin(slug=str(data["slug"]), tenant=data.get("tenant") or None, request=request)


def component_from_envelope(envelope: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the envelope's root component without its data binding, or None when it cannot be relinked.

    The root is the component whose ``id`` is ``"root"``, else the first component. Returns None when the
    envelope has no components or the root's ``component`` is not in ``SUPPORTED_ROOTS``.
    """
    payload = envelope.get("createSurface", envelope)
    components = payload.get("components") or []
    if not components:
        return None
    root = next((component for component in components if component.get("id") == "root"), components[0])
    if root.get("component") not in SUPPORTED_ROOTS:
        return None

    component = dict(root)
    if component["component"] in {"Chart", "DataTable"}:
        component.pop("data", None)
        return component

    value = component.get("value")
    if isinstance(value, str):
        return component
    if not isinstance(value, Mapping):
        return None
    path = value.get("path")
    if not isinstance(path, str) or "/rows/0/" not in path:
        return None
    column = path.rsplit("/", maxsplit=1)[-1]
    if not column:
        return None
    component["value"] = column
    return component
