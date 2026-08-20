"""Authoritative server-side rule evaluator for FormSchema conditional sections.

Given a :class:`~parrot_formdesigner.core.schema.FormSchema` and a dict of
current field answers, :class:`RuleEvaluator` resolves visibility, required
state, computed values (from ``DependencyOperation``), and cascade-clears —
processing pre-dependencies, post-dependencies, and operations in topological
order.

Design notes (spec §8):
- The JSON schema representation is *declarative* and intended for client-side
  interpretation.  This Python evaluator is the **authoritative** server-side
  implementation.
- Evaluation order: topological sort of the dependency graph; cycles were
  already rejected by :class:`~parrot_formdesigner.services.validators.FormValidator`
  — any residual cycle is skipped with a warning.
- ``NOT`` logic negates the AND-combination of conditions (spec §8 explicit
  default).
- ``reload_options`` and ARRAY-operand aggregation scope are open questions in
  the spec (§8).  The evaluator records ``reload_options`` targets in
  ``computed`` as a sentinel (``"__reload__"``) and uses a flat list for
  AGGREGATE operands.  TODO(FEAT-234 open question): revisit once spec §8 is
  finalised.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from ..core.constraints import (
    ConditionOperator,
    DependencyOperation,
    DependencyRule,
    FieldCondition,
    PostDependency,
)
from ..core.resolution import find_field_by_uid, resolve_answer
from ..core.schema import FormField, FormSchema, walk_fields


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public output model
# ---------------------------------------------------------------------------


class RuleResolution(BaseModel):
    """Result of evaluating all conditional-section rules for a form submission.

    Attributes:
        visible: Maps ``field_id`` → ``True`` (visible) / ``False`` (hidden).
            Fields with no applicable rule default to ``True``.
        required: Maps ``field_id`` → ``True`` (required) / ``False`` (not
            required).  Inherits the ``FormField.required`` baseline; rules may
            flip this.
        computed: Maps ``field_id`` → computed value produced by a
            ``DependencyOperation`` or ``post_depends`` set/calc effect.
            ``"__reload__"`` is a sentinel for ``reload_options`` targets
            (TODO(FEAT-234 open question)).
        cleared: List of ``field_id`` values whose answers should be cleared
            (``cascade_clear`` effect).
    """

    visible: dict[str, bool] = {}
    required: dict[str, bool] = {}
    computed: dict[str, Any] = {}
    cleared: list[str] = []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_comparable(value: Any) -> Any:
    """Coerce a value to a comparable type for condition evaluation.

    Args:
        value: Arbitrary answer value from the submission dict.

    Returns:
        The value coerced to a Python primitive if necessary.
    """
    if isinstance(value, (int, float, bool, str, type(None))):
        return value
    # Fallback: stringify for comparison
    return str(value)


def _ref_to_field_id(ref: str, form: FormSchema) -> str:
    """Translate a rule reference (authored ``field_id`` or resolved
    ``field_uid`` string, FEAT-393) to the referenced field's CURRENT
    ``field_id`` — for use as a result-map key (``visible``/``required``/
    ``computed``/``cleared`` stay ``field_id``-keyed per spec).

    Best-effort, never raises: a reference that isn't UID-shaped, or that
    doesn't resolve to a known field, is returned unchanged.

    Args:
        ref: The rule reference (``dep_op.target`` / ``post.target`` /
            an operand string).
        form: The form the reference belongs to.

    Returns:
        The referenced field's current ``field_id``, or ``ref`` unchanged
        if it cannot be resolved.
    """
    try:
        field_uid = uuid.UUID(ref)
    except (ValueError, TypeError, AttributeError):
        return ref
    found = find_field_by_uid(form, field_uid)
    return found[0].field_id if found else ref


def _answer_for_ref(ref: str, form: FormSchema, answers: dict[str, Any]) -> Any:
    """Read an answer value for a rule reference (authored ``field_id`` or
    resolved ``field_uid`` string, FEAT-393) from a ``field_id``-keyed
    answers dict.

    Args:
        ref: The rule reference (an operation operand string).
        form: The form the reference belongs to.
        answers: Current answer dict, keyed by ``field_id``.

    Returns:
        The answer value, or ``None`` if the reference cannot be resolved
        or has no answer.
    """
    try:
        field_uid = uuid.UUID(ref)
    except (ValueError, TypeError, AttributeError):
        return answers.get(ref)
    return resolve_answer(form, field_uid, answers)


def _eval_condition(
    condition: FieldCondition,
    answers: dict[str, Any],
    form: FormSchema,
    location_vars: dict[str, Any] | None = None,
    visit_context: dict[str, Any] | None = None,
) -> bool:
    """Evaluate a single :class:`~parrot_formdesigner.core.constraints.FieldCondition`.

    Args:
        condition: The condition to evaluate.
        answers: Current answer dict keyed by ``field_id``.
        form: The form ``condition`` belongs to (FEAT-393) — used to resolve
            ``condition.field_uid`` back to the field's current
            ``field_id`` for the answers-dict read.
        location_vars: Org-graph location variables (FEAT-301), keyed by name.
        visit_context: Visit-level metadata (FEAT-301), keyed by name.

    Returns:
        ``True`` if the condition is satisfied, ``False`` otherwise.
        Never raises — a missing source value returns ``False`` for relational
        operators and ``True`` for ``is_empty`` (key-missing semantics).

    The value source is selected by ``condition.source``:
    ``"field"`` (default) → ``answers[field_id]`` (resolved via
    ``condition.field_uid``, FEAT-393);
    ``"location_variable"`` → ``location_vars[key]``;
    ``"visit_context"`` → ``visit_context[key]``.
    """
    source = getattr(condition, "source", "field") or "field"
    if source == "location_variable":
        raw = (location_vars or {}).get(condition.key)
    elif source == "visit_context":
        raw = (visit_context or {}).get(condition.key)
    else:
        raw = resolve_answer(form, condition.field_uid, answers) if condition.field_uid else None
    op = condition.operator
    expected = condition.value

    # Nullity operators
    if op == ConditionOperator.IS_EMPTY:
        return raw is None or raw == "" or raw == []
    if op == ConditionOperator.IS_NOT_EMPTY:
        return raw is not None and raw != "" and raw != []

    # Missing value → treat as non-matching for relational operators
    if raw is None:
        return False

    actual = _to_comparable(raw)
    exp = _to_comparable(expected)

    match op:
        case ConditionOperator.EQ:
            return actual == exp
        case ConditionOperator.NEQ:
            return actual != exp
        case ConditionOperator.IN:
            if isinstance(expected, list):
                return actual in [_to_comparable(v) for v in expected]
            return actual == exp
        case ConditionOperator.NOT_IN:
            if isinstance(expected, list):
                return actual not in [_to_comparable(v) for v in expected]
            return actual != exp
        case ConditionOperator.GT:
            try:
                return float(actual) > float(exp)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
        case ConditionOperator.LT:
            try:
                return float(actual) < float(exp)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
        case ConditionOperator.GTE:
            try:
                return float(actual) >= float(exp)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
        case ConditionOperator.LTE:
            try:
                return float(actual) <= float(exp)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
        case _:
            logger.warning("Unknown condition operator: %s", op)
            return False


def _eval_logic(
    conditions: list[FieldCondition],
    logic: str,
    answers: dict[str, Any],
    form: FormSchema,
    location_vars: dict[str, Any] | None = None,
    visit_context: dict[str, Any] | None = None,
) -> bool:
    """Evaluate a list of conditions under the given logic gate.

    Args:
        conditions: List of :class:`FieldCondition` instances.
        logic: One of ``"and"``, ``"or"``, ``"xor"``, ``"not"``.
        answers: Current answer dict.
        form: The form ``conditions`` belong to (FEAT-393) — threaded
            through to :func:`_eval_condition`.

    Returns:
        Boolean result of the combined evaluation.
    """
    if not conditions:
        # No conditions → rule always fires (spec §8: empty condition list = unconditional)
        return True
    results = [
        _eval_condition(c, answers, form, location_vars, visit_context) for c in conditions
    ]
    match logic:
        case "and":
            return all(results)
        case "or":
            return any(results)
        case "xor":
            return sum(bool(r) for r in results) == 1
        case "not":
            # NOT negates the AND-group (spec §8 default)
            return not all(results)
        case _:
            logger.warning("Unknown logic gate: %s; defaulting to 'and'", logic)
            return all(results)


def _apply_operation(
    dep_op: DependencyOperation,
    answers: dict[str, Any],
    form: FormSchema,
) -> Any:
    """Apply a :class:`~parrot_formdesigner.core.constraints.DependencyOperation`.

    Args:
        dep_op: The operation to apply.
        answers: Current answer dict.
        form: The form ``dep_op`` belongs to (FEAT-393) — used to resolve
            ``dep_op.operands`` (resolved ``field_uid`` strings) back to
            each field's current ``field_id`` for the answers-dict read.

    Returns:
        The computed value, or ``None`` if the operation cannot be applied
        safely (missing/invalid operands — never raises).
    """
    operand_values = [_answer_for_ref(ref, form, answers) for ref in dep_op.operands]

    try:
        match dep_op.op:
            case "copy":
                # Copy first operand's value to target
                return operand_values[0] if operand_values else None

            case "add" | "subtract" | "multiply" | "divide" | "percent":
                nums = [float(v) for v in operand_values if v is not None]
                if not nums:
                    return None
                if dep_op.op == "add":
                    return sum(nums)
                elif dep_op.op == "subtract":
                    result = nums[0]
                    for n in nums[1:]:
                        result -= n
                    return result
                elif dep_op.op == "multiply":
                    result_m = nums[0]
                    for n in nums[1:]:
                        result_m *= n
                    return result_m
                elif dep_op.op == "divide":
                    result_d = nums[0]
                    for n in nums[1:]:
                        if n == 0:
                            logger.warning(
                                "DependencyOperation divide: division by zero; op target=%s",
                                dep_op.target,
                            )
                            return None
                        result_d /= n
                    return result_d
                else:  # percent
                    if len(nums) < 2:
                        return None
                    base, pct = nums[0], nums[1]
                    return base * pct / 100.0

            case "concat":
                parts = [str(v) for v in operand_values if v is not None]
                sep = (dep_op.options or {}).get("sep", "")
                return sep.join(parts)

            case "format":
                template: str = (dep_op.options or {}).get("template", "")
                if not template:
                    return " ".join(str(v) for v in operand_values if v is not None)
                # Simple positional replacement: {0}, {1}, ...
                # Force all values to plain str to prevent attribute traversal via {0.attr}
                return template.format(*[str(v) if v is not None else "" for v in operand_values])

            case "date_diff":
                if len(operand_values) < 2:
                    return None
                d1, d2 = operand_values[0], operand_values[1]
                unit = (dep_op.options or {}).get("unit", "days")
                if d1 is None or d2 is None:
                    return None
                # Parse ISO date strings if needed
                if isinstance(d1, str):
                    d1 = date.fromisoformat(d1)
                if isinstance(d2, str):
                    d2 = date.fromisoformat(d2)
                if isinstance(d1, datetime):
                    d1 = d1.date()
                if isinstance(d2, datetime):
                    d2 = d2.date()
                delta = (d2 - d1).days
                if unit == "weeks":
                    return delta // 7
                return delta

            case "lookup":
                # TODO(FEAT-234 open question): lookup table support not yet specified in §8
                # Conservative no-op — returns None; the renderer/client handles UI lookup.
                logger.debug(
                    "DependencyOperation lookup: server-side lookup not implemented; target=%s",
                    dep_op.target,
                )
                return None

            case "aggregate":
                # TODO(FEAT-234 open question): ARRAY-operand aggregation scope
                # Conservative implementation: numeric sum over flat operand values.
                func = (dep_op.options or {}).get("fn", "sum")
                nums_agg = [float(v) for v in operand_values if v is not None]
                if not nums_agg:
                    return None
                match func:
                    case "sum":
                        return sum(nums_agg)
                    case "avg" | "average":
                        return sum(nums_agg) / len(nums_agg)
                    case "min":
                        return min(nums_agg)
                    case "max":
                        return max(nums_agg)
                    case "count":
                        return len(nums_agg)
                    case _:
                        logger.warning(
                            "DependencyOperation aggregate: unknown func=%s", func
                        )
                        return sum(nums_agg)

            case _:
                logger.warning("Unknown DependencyOperation op: %s", dep_op.op)
                return None

    except (TypeError, ValueError, AttributeError) as exc:
        logger.warning(
            "DependencyOperation %s failed for target=%s: %s",
            dep_op.op,
            dep_op.target,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# Topological sort helper
# ---------------------------------------------------------------------------


def _topo_order(fields: list[FormField]) -> list[FormField]:
    """Return ``fields`` in topological evaluation order.

    Uses a depth-first-search topological sort based on ``depends_on`` and
    ``post_depends`` edges. If a cycle is detected (should not happen after
    validation) the algorithm falls back to the original field order.

    FEAT-393: ``field_map``/edges are keyed by ``field_uid`` (str) — rule
    references (``cond.field_uid``, ``dep_op.operands``) are resolved
    UUIDs, not ``field_id``s.

    Args:
        fields: List of form fields to sort.

    Returns:
        Fields in topological order (sources first, dependants later).
    """
    field_map: dict[str, FormField] = {str(f.field_uid): f for f in fields}
    # Build forward edges: for each field, collect which fields it depends on
    edges: dict[str, set[str]] = {str(f.field_uid): set() for f in fields}
    for field in fields:
        field_uid = str(field.field_uid)
        if field.depends_on:
            for cond in field.depends_on.conditions:
                src = str(cond.field_uid) if cond.field_uid else None
                if src in field_map:
                    edges[field_uid].add(src)
            if field.depends_on.operations:
                for dep_op in field.depends_on.operations:
                    for op_ref in dep_op.operands:
                        if op_ref in field_map:
                            edges[field_uid].add(op_ref)

    visited: set[str] = set()
    in_stack: set[str] = set()
    order: list[str] = []
    has_cycle = False

    def _dfs(field_uid: str) -> None:
        nonlocal has_cycle
        if field_uid in in_stack:
            has_cycle = True
            return
        if field_uid in visited:
            return
        in_stack.add(field_uid)
        for dep in edges.get(field_uid, set()):
            _dfs(dep)
        in_stack.discard(field_uid)
        visited.add(field_uid)
        order.append(field_uid)

    for field in fields:
        _dfs(str(field.field_uid))

    if has_cycle:
        logger.warning(
            "RuleEvaluator: cycle detected in dependency graph; "
            "falling back to original field order"
        )
        return fields

    result_map = {uid: field_map[uid] for uid in order if uid in field_map}
    return list(result_map.values())


# ---------------------------------------------------------------------------
# RuleEvaluator
# ---------------------------------------------------------------------------


class RuleEvaluator:
    """Authoritative server-side rule evaluator for FormSchema conditional sections.

    Given a :class:`~parrot_formdesigner.core.schema.FormSchema` and current
    answers, resolves visibility, required state, computed values, and
    cascade-clears for all fields.

    Pre-dependencies (``FormField.depends_on``) are evaluated first, then
    post-dependencies (``FormField.post_depends``) in topological order.

    Example::

        evaluator = RuleEvaluator()
        resolution = await evaluator.resolve(form_schema, {"age": 30})
        if not resolution.visible.get("guardian_name", True):
            # field is hidden — skip it
            ...
    """

    def __init__(self) -> None:
        """Initialize RuleEvaluator."""
        self.logger = logging.getLogger(__name__)

    async def resolve(
        self,
        form: FormSchema,
        answers: dict[str, Any],
        *,
        locale: str = "en",
        location_vars: dict[str, Any] | None = None,
        visit_context: dict[str, Any] | None = None,
    ) -> RuleResolution:
        """Resolve all conditional-section rules for ``form`` against ``answers``.

        Args:
            form: The form schema to evaluate.
            answers: Current answer dict, keyed by ``field_id``.
            locale: BCP 47 locale tag (reserved for future localised-label ops).

        Returns:
            :class:`RuleResolution` with visibility, required-state, computed
            values, and cleared fields.
        """
        all_fields = list(form.iter_all_fields())

        # Initialise resolution with form defaults
        visible: dict[str, bool] = {}
        required: dict[str, bool] = {}
        computed: dict[str, Any] = {}
        cleared: list[str] = []

        for field in all_fields:
            visible[field.field_id] = True
            required[field.field_id] = bool(getattr(field, "required", False))

        # Process fields in topological order
        ordered = _topo_order(all_fields)

        for field in ordered:
            await self._apply_pre_dependency(
                field, answers, form, visible, required, computed, location_vars, visit_context
            )

        for field in ordered:
            await self._apply_post_dependencies(
                field, answers, form, visible, required, computed, cleared,
                location_vars, visit_context,
            )

        # Section gating runs LAST and wins: a section the answers do not
        # reveal hides everything inside it, whatever the fields' own rules
        # or post-dependencies concluded. Without this, `FormSection`'s
        # `depends_on` — populated by the designer and by the networkninja
        # importer — was evaluated by nothing on the server, so a hidden
        # section's required fields still blocked a submission the rep had
        # completed correctly.
        self._apply_section_visibility(
            form, answers, visible, required, location_vars, visit_context
        )

        return RuleResolution(
            visible=visible,
            required=required,
            computed=computed,
            cleared=cleared,
        )

    def _apply_section_visibility(
        self,
        form: FormSchema,
        answers: dict[str, Any],
        visible: dict[str, bool],
        required: dict[str, bool],
        location_vars: dict[str, Any] | None = None,
        visit_context: dict[str, Any] | None = None,
    ) -> None:
        """Hide every field of a section whose ``depends_on`` does not fire.

        A field inside a hidden section is not merely invisible, it is also
        not required — that pairing is the whole point: ``FormValidator``
        reads ``required`` to decide what a submission must carry, and
        demanding an answer to a question the form never displayed is how a
        correctly-filled submission gets rejected.

        Only hides. A section whose rule fires leaves its fields exactly as
        the field-level passes left them, so this can never reveal something
        a field rule hid.

        Args:
            form: The form being resolved.
            answers: Current answer dict, keyed by ``field_id``.
            visible: Mutable visibility dict to update.
            required: Mutable required dict to update.
            location_vars: Org-graph location variables, keyed by name.
            visit_context: Visit-level metadata, keyed by name.
        """
        for section in form.sections:
            rule = section.depends_on
            if rule is None:
                continue

            fired = _eval_logic(
                rule.conditions, rule.logic, answers, form,
                location_vars, visit_context,
            )
            shown = fired if rule.effect != "hide" else not fired
            if shown:
                continue

            for field in walk_fields(section.fields):
                visible[field.field_id] = False
                required[field.field_id] = False

    async def _apply_pre_dependency(
        self,
        field: FormField,
        answers: dict[str, Any],
        form: FormSchema,
        visible: dict[str, bool],
        required: dict[str, bool],
        computed: dict[str, Any],
        location_vars: dict[str, Any] | None = None,
        visit_context: dict[str, Any] | None = None,
    ) -> None:
        """Apply ``FormField.depends_on`` (pre-dependency) to resolution dicts.

        Args:
            field: The field whose pre-dependency to evaluate.
            answers: Current answers.
            form: The form ``field`` belongs to (FEAT-393) — threaded
                through to condition/operation reference resolution.
            visible: Mutable visibility dict to update.
            required: Mutable required dict to update.
            computed: Mutable computed dict for operation results.
        """
        rule: DependencyRule | None = field.depends_on
        if rule is None:
            return

        fired = _eval_logic(rule.conditions, rule.logic, answers, form, location_vars, visit_context)

        # Apply visibility/required effect
        effect = rule.effect
        match effect:
            case "show":
                visible[field.field_id] = fired
            case "hide":
                visible[field.field_id] = not fired
            case "require":
                if fired:
                    required[field.field_id] = True
            case "disable":
                # Disable is surfaced as "not visible" in the resolution
                if fired:
                    visible[field.field_id] = False
            case _:
                self.logger.warning(
                    "Unknown pre-dependency effect=%s on field=%s", effect, field.field_id
                )

        # Apply inline operations (if any)
        if rule.operations:
            for dep_op in rule.operations:
                if fired:
                    result = _apply_operation(dep_op, answers, form)
                    if result is not None:
                        computed[_ref_to_field_id(dep_op.target, form)] = result

    async def _apply_post_dependencies(
        self,
        field: FormField,
        answers: dict[str, Any],
        form: FormSchema,
        visible: dict[str, bool],
        required: dict[str, bool],
        computed: dict[str, Any],
        cleared: list[str],
        location_vars: dict[str, Any] | None = None,
        visit_context: dict[str, Any] | None = None,
    ) -> None:
        """Apply ``FormField.post_depends`` (post-dependencies) to resolution dicts.

        Args:
            field: The field whose post-dependencies to evaluate.
            answers: Current answers.
            form: The form ``field`` belongs to (FEAT-393) — threaded
                through to condition/operation reference resolution.
            visible: Mutable visibility dict to update.
            required: Mutable required dict to update.
            computed: Mutable computed dict for operation results.
            cleared: Mutable list of cleared field ids.
        """
        post_list: list[PostDependency] | None = field.post_depends
        if not post_list:
            return

        # Use the owner field's current answer as implicit source when no
        # conditions — the owner is a field OBJECT here (not a reference),
        # so the read stays via field.field_id (FEAT-393: unaffected).
        owner_answer = answers.get(field.field_id)

        for post in post_list:
            # Evaluate conditions (if any)
            if post.conditions:
                fired = _eval_logic(
                    post.conditions, post.logic, answers, form, location_vars, visit_context
                )
            else:
                # No conditions: post-dep fires if the owner field has a non-empty value
                fired = owner_answer is not None and owner_answer != "" and owner_answer != []

            # post.target is a resolved field_uid string (FEAT-393); result
            # maps stay field_id-keyed, so translate it back.
            target = _ref_to_field_id(post.target, form)

            match post.effect:
                case "show":
                    if fired:
                        visible[target] = True
                case "hide":
                    if fired:
                        visible[target] = False
                case "require":
                    if fired:
                        required[target] = True
                case "set":
                    if fired and post.operation is not None:
                        result = _apply_operation(post.operation, answers, form)
                        if result is not None:
                            computed[target] = result
                case "calc":
                    if fired and post.operation is not None:
                        result = _apply_operation(post.operation, answers, form)
                        if result is not None:
                            computed[target] = result
                case "reload_options":
                    # TODO(FEAT-234 open question): reload_options timing not finalised in §8
                    # Conservative: mark target as needing options reload via sentinel value
                    if fired:
                        computed[target] = "__reload__"
                case "cascade_clear":
                    if fired and target not in cleared:
                        cleared.append(target)
                case _:
                    self.logger.warning(
                        "Unknown post-dependency effect=%s on field=%s → target=%s",
                        post.effect,
                        field.field_id,
                        target,
                    )
