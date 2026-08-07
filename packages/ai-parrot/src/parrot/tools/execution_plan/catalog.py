"""Tool catalog + allowlist validation layering (spec §3 Module 5).

An ``ExecutionPlan`` is code written by a model that may share its
``ToolManager`` with writers, so the explicit ``allowed_tools`` allowlist is
both the security boundary — a plan naming a non-allowlisted tool fails
validation before any tool runs — and the planner's tool catalog (the
planner only ever sees allowlisted tools). The frozen
``parrot.bots.flows.plan.validator`` module knows nothing about allowlists;
the ``tool_not_allowed`` check is layered on top here, never patched into
it.
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence, Type

from pydantic import BaseModel, ConfigDict, Field

from parrot.bots.flows.plan import ExecutionPlan
from parrot.bots.flows.plan.validator import ValidationIssue, ValidationReport, validate_plan
from ..abstract import AbstractToolArgsSchema

__all__ = (
    "ArgSummary",
    "ToolCatalogEntry",
    "build_catalog",
    "check_allowlist",
    "validate_with_allowlist",
)

# Bounds so the catalog stays small enough for a planner prompt (spec §2:
# "description + args_schema summary per tool", never a full JSON schema).
_MAX_DESCRIPTION_CHARS = 200
_MAX_ARG_DESCRIPTION_CHARS = 120


class ArgSummary(BaseModel):
    """Compact rendering of one tool argument — never the full JSON schema."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    required: bool
    description: str = ""


class ToolCatalogEntry(BaseModel):
    """One tool the planner (and the allowlist) may reference.

    Attributes:
        name: Registered tool name.
        description: Tool description, bounded to
            :data:`_MAX_DESCRIPTION_CHARS`.
        args_summary: Compact per-argument summaries; empty for a tool with
            no declared ``args_schema`` (or the default
            ``AbstractToolArgsSchema``).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    args_summary: List[ArgSummary] = Field(default_factory=list)


def build_catalog(
    tool_manager: Any, allowed_tools: Optional[Sequence[str]] = None
) -> List[ToolCatalogEntry]:
    """Build the catalog = ``allowed_tools`` ∩ ``tool_manager.list_tools()``.

    Args:
        tool_manager: Live manager exposing ``list_tools()``/``get_tool()``.
        allowed_tools: Explicit allowlist. ``None`` means every manager
            tool is allowed.

    Returns:
        Catalog entries, in ``tool_manager.list_tools()`` order (stable —
        never re-sorted by allowlist order or set iteration).

    Raises:
        ValueError: If ``allowed_tools`` names a tool the manager does not
            have registered — a misconfigured allowlist must not fail
            silently.
    """
    available = list(tool_manager.list_tools() or [])

    if allowed_tools is None:
        names = available
    else:
        allowed_set = set(allowed_tools)
        unregistered = sorted(allowed_set - set(available))
        if unregistered:
            raise ValueError(
                f"allowed_tools names not registered on tool_manager: {unregistered}"
            )
        names = [name for name in available if name in allowed_set]

    entries: List[ToolCatalogEntry] = []
    for name in names:
        tool = tool_manager.get_tool(name)
        description = (getattr(tool, "description", None) or "")[:_MAX_DESCRIPTION_CHARS]
        args_schema = getattr(tool, "args_schema", None)
        entries.append(
            ToolCatalogEntry(
                name=name,
                description=description,
                args_summary=_build_args_summary(args_schema),
            )
        )
    return entries


def check_allowlist(
    plan: ExecutionPlan, allowed_tools: Optional[Sequence[str]]
) -> List[ValidationIssue]:
    """Return one ``tool_not_allowed`` issue per node outside ``allowed_tools``.

    Args:
        plan: The plan being validated.
        allowed_tools: Explicit allowlist. ``None`` means every tool is
            allowed (no issues raised).

    Returns:
        Error-severity :class:`ValidationIssue`s, phrased so a planner
        model can correct the plan directly.
    """
    if allowed_tools is None:
        return []

    allowed_set = set(allowed_tools)
    issues: List[ValidationIssue] = []
    for node in plan.nodes:
        if node.tool not in allowed_set:
            issues.append(
                ValidationIssue(
                    node.id,
                    "tool_not_allowed",
                    f"Tool {node.tool!r} is not in the allowed_tools list. "
                    f"Allowed: {sorted(allowed_set)}.",
                )
            )
    return issues


def validate_with_allowlist(
    plan: ExecutionPlan,
    tool_manager: Optional[Any],
    allowed_tools: Optional[Sequence[str]] = None,
    *,
    check_guards: bool = True,
) -> ValidationReport:
    """Run ``validate_plan`` and append allowlist issues into the same report.

    Args:
        plan: The plan to validate.
        tool_manager: Live manager, forwarded to ``validate_plan``.
        allowed_tools: Explicit allowlist forwarded to :func:`check_allowlist`.
        check_guards: Forwarded to ``validate_plan``.

    Returns:
        The single, combined :class:`ValidationReport` — validator issues
        and allowlist issues in one pass, one list.
    """
    report = validate_plan(plan, tool_manager, check_guards=check_guards)
    report.issues.extend(check_allowlist(plan, allowed_tools))
    return report


def _build_args_summary(args_schema: Optional[Type[BaseModel]]) -> List[ArgSummary]:
    """Render an ``args_schema`` into bounded :class:`ArgSummary` entries."""
    if args_schema is None or args_schema is AbstractToolArgsSchema:
        return []

    context_fields = getattr(args_schema, "_context_fields", frozenset())
    summaries: List[ArgSummary] = []
    for field_name, field_info in args_schema.model_fields.items():
        if field_name in context_fields:
            continue
        description = (field_info.description or "")[:_MAX_ARG_DESCRIPTION_CHARS]
        summaries.append(
            ArgSummary(
                name=field_name,
                type=_type_name(field_info.annotation),
                required=field_info.is_required(),
                description=description,
            )
        )
    return summaries


def _type_name(annotation: Any) -> str:
    """Render a type annotation as a short, prompt-friendly string."""
    name = getattr(annotation, "__name__", None)
    if name:
        return name
    return str(annotation).replace("typing.", "")
