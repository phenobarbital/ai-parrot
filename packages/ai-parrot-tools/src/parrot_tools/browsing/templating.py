"""
Parameter templating and safety bounds for catalogued action steps.

Substitutes ``{{name}}`` placeholders in step string fields with caller
parameters, and enforces an upper bound on every ``loop`` step so a
catalogued script can never run unbounded.

Only *known* parameter names are substituted — unknown placeholders (the
Loop executor's ``{{index}}``/``{{index_1}}``/``{{value_name}}`` among
them) pass through untouched, so loop-internal templating keeps working.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Set

from .models import ActionParam, RESERVED_PLACEHOLDERS

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

#: Nested-step list fields of the DSL (Loop / Conditional).
_NESTED_KEYS = ("actions", "actions_if_true", "actions_if_false")


def resolve_params(
    declared: Dict[str, ActionParam],
    provided: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Merge caller-provided values with declared defaults.

    Args:
        declared: The action's declared parameters.
        provided: Values supplied by the caller (may be ``None``).

    Returns:
        Final parameter mapping used for substitution. Extra provided
        keys are kept (they may feed placeholders of composed children).

    Raises:
        ValueError: A required parameter has neither a value nor a
            default. All missing names are reported at once.
    """
    provided = dict(provided or {})
    resolved: Dict[str, Any] = {}
    missing: List[str] = []
    for name, spec in declared.items():
        if name in provided:
            resolved[name] = provided.pop(name)
        elif spec.default is not None or not spec.required:
            resolved[name] = spec.default
        else:
            missing.append(name)
    if missing:
        raise ValueError(
            f"Missing required parameter(s): {', '.join(sorted(missing))}"
        )
    resolved.update(provided)
    return resolved


def render_value(value: Any, params: Dict[str, Any]) -> Any:
    """Recursively substitute ``{{name}}`` placeholders in *value*.

    A string that is exactly one placeholder is replaced by the raw
    parameter value (type-preserving, so a list can feed ``Loop.values``);
    otherwise placeholders are interpolated as strings. Placeholders whose
    name is not in *params* are left untouched.
    """
    if isinstance(value, str):
        exact = _PLACEHOLDER_RE.fullmatch(value.strip())
        if exact and exact.group(1) in params:
            return params[exact.group(1)]

        def _sub(match: re.Match[str]) -> str:
            name = match.group(1)
            if name in params:
                return str(params[name])
            return match.group(0)

        return _PLACEHOLDER_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: render_value(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(item, params) for item in value]
    return value


def render_steps(
    steps: List[Dict[str, Any]],
    params: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return a deep copy of *steps* with parameters substituted.

    Args:
        steps: Raw DSL step dicts (never mutated).
        params: Fully-resolved parameter mapping
            (see :func:`resolve_params`).

    Returns:
        New step dicts ready for execution.
    """
    return [render_value(copy.deepcopy(step), params) for step in steps]


def collect_placeholders(steps: List[Dict[str, Any]]) -> Set[str]:
    """Collect every ``{{name}}`` placeholder appearing in *steps*.

    Loop-reserved names (``index``, ``index_1``, ``value``) and each
    loop's declared ``value_name`` are excluded — those are runtime
    placeholders owned by the Loop executor, not action parameters.

    Args:
        steps: Raw DSL step dicts.

    Returns:
        Set of parameter-like placeholder names.
    """
    found: Set[str] = set()
    loop_names: Set[str] = set(RESERVED_PLACEHOLDERS)

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            found.update(_PLACEHOLDER_RE.findall(node))
            return
        if isinstance(node, dict):
            if node.get("action") == "loop" and node.get("value_name"):
                loop_names.add(str(node["value_name"]))
            for v in node.values():
                _walk(v)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(steps)
    return found - loop_names


def validate_loop_bounds(
    steps: List[Dict[str, Any]],
    max_iterations: int,
    *,
    strict: bool = True,
) -> List[Dict[str, Any]]:
    """Enforce an upper bound on every ``loop`` step, recursively.

    Loops are allowed but only bounded: each loop must resolve to at most
    *max_iterations* iterations. In strict mode (save time) a violation
    raises; in non-strict mode (run time, defense in depth) offending
    values are clamped.

    Args:
        steps: Raw DSL step dicts (never mutated).
        max_iterations: Hard per-loop iteration cap.
        strict: Raise instead of clamping.

    Returns:
        A deep copy of *steps* with loop bounds enforced.

    Raises:
        ValueError: In strict mode, when a loop exceeds or lacks a bound.
    """
    bounded = copy.deepcopy(steps)

    def _check_loop(node: Dict[str, Any], path: str) -> None:
        iterations = node.get("iterations")
        values = node.get("values")
        cap = node.get("max_iterations")

        if isinstance(iterations, int) and iterations > max_iterations:
            if strict:
                raise ValueError(
                    f"{path}: loop iterations={iterations} exceeds the "
                    f"allowed maximum of {max_iterations}"
                )
            node["iterations"] = max_iterations
        if isinstance(values, list) and len(values) > max_iterations:
            if strict:
                raise ValueError(
                    f"{path}: loop values has {len(values)} entries, "
                    f"exceeding the allowed maximum of {max_iterations}"
                )
            node["values"] = values[:max_iterations]
        if not isinstance(cap, int) or cap > max_iterations or cap < 1:
            if strict and isinstance(cap, int) and cap > max_iterations:
                raise ValueError(
                    f"{path}: loop max_iterations={cap} exceeds the "
                    f"allowed maximum of {max_iterations}"
                )
            node["max_iterations"] = max_iterations

    def _walk(items: Any, path: str) -> None:
        if not isinstance(items, list):
            return
        for idx, node in enumerate(items):
            if not isinstance(node, dict):
                continue
            here = f"{path}[{idx}]"
            if node.get("action") == "loop":
                _check_loop(node, here)
            for key in _NESTED_KEYS:
                if key in node:
                    _walk(node[key], f"{here}.{key}")

    _walk(bounded, "steps")
    return bounded
