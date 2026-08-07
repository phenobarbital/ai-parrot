"""Static validation of an ExecutionPlan against a live ToolManager.

The point of the planner/executor split is that a bad plan fails *before* any
tool runs. Pydantic already enforces the plan's internal consistency (ids,
cycles, declared dependencies, key collisions); this module adds everything
that needs the runtime environment:

* every ``tool`` name is registered
* declared ``args`` fit the tool's ``args_schema`` (required keys present, no
  unknown keys) — shape only, since placeholder strings resolve to other
  types at run time
* every ``when`` expression compiles
* every ``select`` / facet path parses
* guards only reference facets some upstream node actually publishes

That last check matters more than it looks: ``CELPredicateEvaluator`` is
fail-safe, so a typo in a facet name evaluates to ``False`` and silently
skips the node. Catching it here turns a silent no-op into a loud error.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional, Protocol, Sequence

from .guards import GuardCompilationError, compile_guard
from .models import ExecutionPlan, PlanNode
from .paths import PathError, compile_path

__all__ = ("PlanValidationError", "ValidationIssue", "ValidationReport", "validate_plan")

# ``ctx.artifacts.<node>.<facet>`` inside a guard expression.
_GUARD_FACET_RE = re.compile(r"\bctx\.artifacts\.([A-Za-z0-9_\-]+)\.([A-Za-z0-9_]+)")
_GUARD_STATUS_RE = re.compile(r"\bctx\.status\.([A-Za-z0-9_\-]+)")


class ToolManagerLike(Protocol):
    """The slice of ``ToolManager`` this validator needs."""

    def get_tool(self, tool_name: str) -> Optional[Any]:
        ...

    def list_tools(self) -> List[str]:
        ...


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding.

    Attributes:
        node_id: The offending node, or ``None`` for plan-level issues.
        code: Stable machine-readable identifier.
        message: Human-readable explanation, phrased so a planner model can
            correct the plan from it directly.
        severity: ``error`` blocks execution; ``warning`` does not.
    """

    node_id: Optional[str]
    code: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        where = f"node {self.node_id!r}: " if self.node_id else ""
        return f"[{self.severity}:{self.code}] {where}{self.message}"


@dataclass
class ValidationReport:
    """Aggregated validation result."""

    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        """Blocking issues."""
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        """Non-blocking issues."""
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        """``True`` when nothing blocks execution."""
        return not self.errors

    def raise_for_errors(self) -> None:
        """Raise :class:`PlanValidationError` when blocking issues exist."""
        if self.errors:
            raise PlanValidationError(self.errors)

    def __str__(self) -> str:
        if not self.issues:
            return "plan ok"
        return "\n".join(str(issue) for issue in self.issues)


class PlanValidationError(ValueError):
    """Raised when a plan cannot be executed as written."""

    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        self.issues = list(issues)
        super().__init__(
            "ExecutionPlan validation failed:\n"
            + "\n".join(f"  - {issue}" for issue in self.issues)
        )


def validate_plan(
    plan: ExecutionPlan,
    tool_manager: Optional[ToolManagerLike] = None,
    *,
    check_guards: bool = True,
) -> ValidationReport:
    """Validate ``plan`` and return every issue found.

    All checks run before returning — a planner model gets the complete list
    to fix in one pass instead of one error per round trip.

    Args:
        plan: The plan to validate. Already structurally valid (Pydantic).
        tool_manager: Live manager used to resolve tool names and schemas.
            When ``None``, tool checks are skipped and reported as warnings.
        check_guards: Compile ``when`` expressions. Disable only where
            ``cel-python`` is unavailable.

    Returns:
        A :class:`ValidationReport`; call ``raise_for_errors()`` to enforce.
    """
    report = ValidationReport()
    known_ids = {node.id for node in plan.nodes}

    if tool_manager is None:
        report.issues.append(
            ValidationIssue(
                None,
                "no_tool_manager",
                "No ToolManager supplied — tool names and argument schemas "
                "were not verified.",
                severity="warning",
            )
        )

    published = _published_facets(plan)

    for node in plan.nodes:
        _check_tool(node, tool_manager, report)
        _check_paths(node, report)
        if check_guards:
            _check_guard(node, plan, known_ids, published, report)
        _check_for_each(node, plan, report)

    return report


def _check_tool(
    node: PlanNode,
    tool_manager: Optional[ToolManagerLike],
    report: ValidationReport,
) -> None:
    """Verify the tool exists and the declared args fit its schema."""
    if tool_manager is None:
        return

    tool = tool_manager.get_tool(node.tool)
    if tool is None:
        available = sorted(tool_manager.list_tools() or [])
        suggestion = _closest(node.tool, available)
        hint = f" Did you mean {suggestion!r}?" if suggestion else ""
        report.issues.append(
            ValidationIssue(
                node.id,
                "unknown_tool",
                f"Tool {node.tool!r} is not registered.{hint}",
            )
        )
        return

    schema = getattr(tool, "args_schema", None)
    fields = getattr(schema, "model_fields", None)
    if not fields:
        return  # untyped tool — nothing to check against

    # ``for_each.alias`` names a template variable usable inside arg values
    # ({item}, {item.id}) — it is not itself a tool parameter.
    unknown = set(node.args) - set(fields) - _CONTEXT_ARGS
    if unknown:
        report.issues.append(
            ValidationIssue(
                node.id,
                "unknown_args",
                f"Tool {node.tool!r} has no parameter(s) {sorted(unknown)}. "
                f"Accepted: {sorted(fields)}.",
            )
        )

    missing = [
        name
        for name, info in fields.items()
        if info.is_required() and name not in node.args
    ]
    if missing:
        report.issues.append(
            ValidationIssue(
                node.id,
                "missing_args",
                f"Tool {node.tool!r} requires {sorted(missing)}, not provided.",
            )
        )


def _check_paths(node: PlanNode, report: ValidationReport) -> None:
    """Verify every ``select`` and facet path parses."""
    candidates: list[tuple[str, str]] = []
    if node.for_each is not None and node.for_each.select:
        candidates.append(("for_each.select", node.for_each.select))
    for label, mapping in (
        ("facets.paths", node.facets.paths),
        ("facets.counts", node.facets.counts),
        ("facets.group_counts", node.facets.group_counts),
    ):
        for name, path in mapping.items():
            candidates.append((f"{label}.{name}", path))

    for where, path in candidates:
        try:
            compile_path(path)
        except PathError as exc:
            report.issues.append(
                ValidationIssue(node.id, "bad_path", f"{where}: {exc}")
            )

    for name, path in node.facets.counts.items():
        if "[]" not in path:
            report.issues.append(
                ValidationIssue(
                    node.id,
                    "count_not_a_list",
                    f"facets.counts.{name} = {path!r} does not contain '[]', so "
                    "it does not resolve to a list and cannot be counted.",
                )
            )
    for name, path in node.facets.group_counts.items():
        if "[]" not in path:
            report.issues.append(
                ValidationIssue(
                    node.id,
                    "group_count_not_a_list",
                    f"facets.group_counts.{name} = {path!r} does not contain "
                    "'[]', so there is nothing to group.",
                )
            )


def _check_guard(
    node: PlanNode,
    plan: ExecutionPlan,
    known_ids: set[str],
    published: dict[str, set[str]],
    report: ValidationReport,
) -> None:
    """Compile the guard and verify the facets/nodes it references exist."""
    if node.when is None:
        return

    try:
        compile_guard(node.when)
    except GuardCompilationError as exc:
        report.issues.append(ValidationIssue(node.id, "bad_guard", str(exc)))
        return

    upstream = _ancestors(node.id, plan)

    for ref_node, facet in _GUARD_FACET_RE.findall(node.when):
        if ref_node not in known_ids:
            report.issues.append(
                ValidationIssue(
                    node.id,
                    "guard_unknown_node",
                    f"'when' references ctx.artifacts.{ref_node} but no such "
                    "node exists.",
                )
            )
            continue
        if ref_node not in upstream:
            report.issues.append(
                ValidationIssue(
                    node.id,
                    "guard_not_upstream",
                    f"'when' reads ctx.artifacts.{ref_node} but {ref_node!r} is "
                    f"not an ancestor of {node.id!r}, so its facets may not "
                    "exist yet when the guard runs.",
                )
            )
            continue
        if facet not in published.get(ref_node, set()):
            report.issues.append(
                ValidationIssue(
                    node.id,
                    "guard_unknown_facet",
                    f"'when' reads ctx.artifacts.{ref_node}.{facet} but node "
                    f"{ref_node!r} publishes {sorted(published.get(ref_node, ())) or 'no facets'}. "
                    "CEL is fail-safe, so this would silently evaluate to false "
                    "and skip the node.",
                )
            )

    for ref_node in _GUARD_STATUS_RE.findall(node.when):
        if ref_node not in known_ids:
            report.issues.append(
                ValidationIssue(
                    node.id,
                    "guard_unknown_node",
                    f"'when' references ctx.status.{ref_node} but no such node "
                    "exists.",
                )
            )


def _check_for_each(
    node: PlanNode, plan: ExecutionPlan, report: ValidationReport
) -> None:
    """Verify the fan-out source is a declared dependency."""
    if node.for_each is None:
        return
    source = node.for_each.source_node
    if source not in node.depends_on:
        report.issues.append(
            ValidationIssue(
                node.id,
                "for_each_not_dependency",
                f"for_each iterates {{artifacts.{source}}} but {source!r} is not "
                "in depends_on, so it may not have run yet.",
            )
        )
    if node.for_each.max_concurrency > plan.metadata.max_parallel_tasks:
        report.issues.append(
            ValidationIssue(
                node.id,
                "concurrency_above_flow_cap",
                f"for_each.max_concurrency={node.for_each.max_concurrency} "
                f"exceeds metadata.max_parallel_tasks="
                f"{plan.metadata.max_parallel_tasks}; the flow cap wins.",
                severity="warning",
            )
        )


def _published_facets(plan: ExecutionPlan) -> dict[str, set[str]]:
    """Return ``{node_id: {facet names it publishes}}``."""
    return {
        node.id: set(node.facets.paths)
        | set(node.facets.counts)
        | set(node.facets.group_counts)
        for node in plan.nodes
    }


def _ancestors(node_id: str, plan: ExecutionPlan) -> set[str]:
    """Return every node that must complete before ``node_id`` runs."""
    deps = {node.id: set(node.depends_on) for node in plan.nodes}
    seen: set[str] = set()
    stack = list(deps.get(node_id, ()))
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(deps.get(current, ()))
    return seen


def _closest(name: str, candidates: Iterable[str]) -> Optional[str]:
    """Return the nearest candidate name, for a 'did you mean' hint."""
    import difflib  # noqa: PLC0415

    matches = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.7)
    return matches[0] if matches else None


# Injected by ToolManager.execute_tool rather than declared in a plan.
_CONTEXT_ARGS = frozenset(
    {
        "_permission_context",
        "_resolver",
        "_broker",
        "_cred_channel",
        "_cred_user_id",
    }
)
