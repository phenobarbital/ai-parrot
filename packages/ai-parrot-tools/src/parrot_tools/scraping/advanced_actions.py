"""Advanced action dispatch — Loop, Conditional, and template substitution.

Stateless async helpers extracted from the legacy ``WebScrapingTool`` so the
modern executor, the legacy tool, and the ``FlowExecutor`` can all share a
single implementation of Loop / Conditional dispatch (FEAT-222, Module 3).

The functions accept an :class:`AbstractDriver` plus a ``dispatch_step_fn``
callback for recursive step execution.  This decouples them from any specific
execution context (executor, tool, or flow engine).

The ``dispatch_step_fn`` callback signature mirrors
``executor._dispatch_step``::

    async def dispatch_step_fn(
        driver: AbstractDriver,
        step: ScrapingStep,
        url: str,
        timeout: int,
        step_extracted: Dict[str, Any],
    ) -> bool: ...
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .drivers.abstract import AbstractDriver
from .models import Conditional, Loop, ScrapingStep

logger = logging.getLogger(__name__)

# Callback used to dispatch a single step back to the caller's executor.
DispatchStepFn = Callable[
    [AbstractDriver, ScrapingStep, str, int, Dict[str, Any]], Awaitable[bool]
]

# Matches a brace expression containing one of the loop variable tokens
# (i / index / iteration). Mirrors the legacy regex at tool.py:3326.
_TEMPLATE_VAR_RE = re.compile(r"\{([^}]*(?:i|index|iteration)[^}]*)\}")


def substitute_template_vars(
    value: Any,
    index: int,
    start_index: int = 0,
    values: Optional[List[Any]] = None,
    value_name: str = "value",
) -> Any:
    """Recursively substitute loop template variables in *value*.

    Supported tokens (inside ``{...}``):
        - ``{i}``, ``{index}``, ``{iteration}`` — the current iteration,
          offset by *start_index*.
        - Arithmetic expressions — ``{i+1}``, ``{i-1}``, ``{i*2}``,
          ``{index+1}`` — evaluated with a no-builtins ``eval`` for safety.
        - ``{value}`` (and ``{<value_name>}``) — the current value when
          iterating over a *values* list.

    Non-string scalars (int, bool, None) pass through unchanged; dicts and
    lists are walked recursively.

    Args:
        value: The value to substitute (str, dict, list, or scalar).
        index: Current iteration counter (0-based).
        start_index: Offset applied to the exposed index (default 0).
        values: Optional list being iterated over; ``values[index]`` becomes
            the current value.
        value_name: Variable name exposed for the current value (default
            ``"value"``).

    Returns:
        The value with all template variables substituted.
    """
    if isinstance(value, str):
        actual_index = start_index + index
        current_value: Any = None
        if values is not None and 0 <= index < len(values):
            current_value = values[index]

        # Replace standalone tokens first (longest-first is unnecessary here
        # because each is brace-delimited and mutually exclusive).
        value = value.replace("{i}", str(actual_index))
        value = value.replace("{index}", str(actual_index))
        value = value.replace("{iteration}", str(actual_index))

        if current_value is not None:
            value = value.replace("{value}", str(current_value))
            if value_name and value_name != "value":
                value = value.replace("{" + value_name + "}", str(current_value))

        def _eval_expr(match: "re.Match[str]") -> str:
            expr = match.group(1)
            # Replace variable tokens longest-first so 'index'/'iteration'
            # are not corrupted by the single-letter 'i' substitution.
            expr = re.sub(r"\biteration\b", str(actual_index), expr)
            expr = re.sub(r"\bindex\b", str(actual_index), expr)
            expr = re.sub(r"\bi\b", str(actual_index), expr)
            try:
                return str(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307
            except Exception:  # noqa: BLE001 — keep original on any failure
                return match.group(0)

        return _TEMPLATE_VAR_RE.sub(_eval_expr, value)

    if isinstance(value, dict):
        return {
            k: substitute_template_vars(v, index, start_index, values, value_name)
            for k, v in value.items()
        }

    if isinstance(value, list):
        return [
            substitute_template_vars(item, index, start_index, values, value_name)
            for item in value
        ]

    return value


def _substitute_action_vars(
    action: Any,
    index: int,
    start_index: int = 0,
    values: Optional[List[Any]] = None,
    value_name: str = "value",
) -> Any:
    """Return a copy of *action* with template variables substituted.

    The action is dumped to a dict, run through :func:`substitute_template_vars`,
    and reconstructed via its own class so the result is a fresh model
    instance (the original is never mutated).
    """
    action_dict = action.model_dump()
    substituted = substitute_template_vars(
        action_dict, index, start_index, values, value_name
    )
    return type(action)(**substituted)


async def _evaluate_js_condition(driver: AbstractDriver, condition: str) -> bool:
    """Evaluate a JavaScript boolean condition through the driver."""
    result = await driver.evaluate(f"Boolean({condition})")
    return bool(result)


async def exec_loop(
    driver: AbstractDriver,
    loop_action: Loop,
    dispatch_step_fn: DispatchStepFn,
    base_url: str = "",
    timeout: int = 10,
) -> bool:
    """Execute a :class:`Loop` action.

    Supports fixed iteration counts, iteration over a ``values`` list with
    ``{value}`` substitution, JavaScript condition-controlled loops,
    ``break_on_error``, the ``max_iterations`` safety limit, and the
    ``start_index`` offset.

    Args:
        driver: Browser driver implementing :class:`AbstractDriver`.
        loop_action: The :class:`Loop` model to execute.
        dispatch_step_fn: Callback dispatching a single step (enables
            recursive loop-within-loop execution).
        base_url: Base URL forwarded to each dispatched step.
        timeout: Default per-step timeout in seconds.

    Returns:
        ``True`` when the loop completed; ``False`` when it stopped early due
        to a failed step while ``break_on_error`` is set.
    """
    start_index = loop_action.start_index
    value_name = loop_action.value_name or "value"
    values = loop_action.values

    if values:
        max_iter = len(values)
        logger.info(
            "Starting loop over %d values, start_index=%d", max_iter, start_index
        )
    else:
        max_iter = loop_action.iterations or loop_action.max_iterations
        logger.info(
            "Starting loop: %d iterations, start_index=%d", max_iter, start_index
        )

    # Local accumulator. Callers that need extract results to propagate wrap
    # dispatch_step_fn in a closure over their own step_extracted dict.
    step_extracted: Dict[str, Any] = {}
    iteration = 0

    while iteration < max_iter:
        # Optional JS condition gate.
        if loop_action.condition:
            should_continue = await _evaluate_js_condition(driver, loop_action.condition)
            if not should_continue:
                logger.info("Loop condition false at iteration %d; stopping", iteration)
                break

        for sub_action in loop_action.actions:
            if loop_action.do_replace:
                action_obj = _substitute_action_vars(
                    sub_action, iteration, start_index, values, value_name
                )
            else:
                action_obj = sub_action

            step = ScrapingStep(action=action_obj)
            success = await dispatch_step_fn(
                driver, step, base_url, timeout, step_extracted
            )

            if not success and loop_action.break_on_error:
                logger.warning("Loop stopped at iteration %d due to error", iteration)
                return False

        iteration += 1

        # Stop once the requested fixed-iteration count is reached.
        if loop_action.iterations and iteration >= loop_action.iterations:
            break

        # Small randomized delay between iterations (anti-bot pacing).
        await asyncio.sleep(random.uniform(0.1, 0.5))

    logger.info("Loop completed %d iterations", iteration)
    return True


async def exec_conditional(
    driver: AbstractDriver,
    cond_action: Conditional,
    dispatch_step_fn: DispatchStepFn,
    base_url: str = "",
    timeout: int = 10,
) -> bool:
    """Execute a :class:`Conditional` action.

    Evaluates the configured condition against the page and dispatches the
    ``actions_if_true`` or ``actions_if_false`` branch accordingly.

    Supported ``condition_type`` values: ``exists``, ``not_exists``,
    ``text_contains``, ``text_equals``, ``attribute_equals`` (the latter
    expects ``expected_value`` formatted as ``"attr=value"``).

    Args:
        driver: Browser driver implementing :class:`AbstractDriver`.
        cond_action: The :class:`Conditional` model to evaluate.
        dispatch_step_fn: Callback dispatching a single step.
        base_url: Base URL forwarded to each dispatched step.
        timeout: Default per-step timeout in seconds.

    Returns:
        ``True`` when the selected branch executed without failures (or there
        was no branch to run); ``False`` on an unknown condition type or when
        a dispatched sub-action failed.
    """
    target = cond_action.target
    target_type = cond_action.target_type or "css"
    condition_type = cond_action.condition_type
    expected_value = cond_action.expected_value
    cond_timeout = cond_action.timeout or 5

    selector = f"xpath={target}" if target_type == "xpath" else target

    logger.info(
        "Evaluating conditional: %s on %s='%s' with value '*%s*'",
        condition_type, target_type, target, expected_value,
    )

    # Detect element presence (state='attached' — matches legacy behaviour).
    exists = False
    if selector:
        try:
            await driver.wait_for_selector(
                selector, timeout=cond_timeout, state="attached"
            )
            exists = True
        except Exception:  # noqa: BLE001 — absence is a valid outcome
            exists = False

    if condition_type == "exists":
        condition_result = exists
    elif condition_type == "not_exists":
        condition_result = not exists
    elif condition_type == "text_contains":
        text = await driver.get_text(selector, timeout=cond_timeout) if exists else ""
        condition_result = expected_value in (text or "")
    elif condition_type == "text_equals":
        text = await driver.get_text(selector, timeout=cond_timeout) if exists else ""
        condition_result = (text or "") == expected_value
    elif condition_type == "attribute_equals":
        attr, _, val = expected_value.partition("=")
        actual = (
            await driver.get_attribute(selector, attr.strip(), timeout=cond_timeout)
            if exists else None
        )
        condition_result = actual == val.strip()
    else:
        logger.error("Unknown condition type: %s", condition_type)
        return False

    logger.info("Condition result: %s", condition_result)

    actions_to_execute = (
        cond_action.actions_if_true if condition_result
        else (cond_action.actions_if_false or [])
    ) or []

    if not actions_to_execute:
        logger.info("No actions to execute for condition result: %s", condition_result)
        return True

    logger.info(
        "Executing %d action(s) based on condition result", len(actions_to_execute)
    )

    step_extracted: Dict[str, Any] = {}
    all_success = True
    for sub_action in actions_to_execute:
        step = ScrapingStep(action=sub_action)
        success = await dispatch_step_fn(
            driver, step, base_url, timeout, step_extracted
        )
        if not success:
            logger.warning("Conditional sub-action failed: %s", sub_action.description)
            all_success = False
            # Continue executing remaining actions even if one fails.

    return all_success
