"""Lightweight decorator registries for evaluators and metrics.

FEAT-217 — Module 2. These registries are intentionally minimal: plain
``dict`` backed, import-cycle free (no dependency on the ABCs), and
independent from the bot-specific ``AgentRegistry``.

Usage::

    from parrot.eval.registry import register_evaluator, get_evaluator

    @register_evaluator("state_based")
    class StateBasedEvaluator(AbstractEvaluator):
        ...

    klass = get_evaluator("state_based")
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal registry dicts
# ---------------------------------------------------------------------------

_EVALUATORS: dict[str, type] = {}
_METRICS: dict[str, type] = {}


# ---------------------------------------------------------------------------
# Evaluator registry
# ---------------------------------------------------------------------------


def register_evaluator(name: str):
    """Class decorator that registers an evaluator under *name*.

    Args:
        name: Registry key.  Must be unique; a duplicate raises
            ``ValueError``.

    Returns:
        The class unchanged (decorator pattern).

    Raises:
        ValueError: If *name* is already registered.

    Example::

        @register_evaluator("state_based")
        class StateBasedEvaluator(AbstractEvaluator):
            ...
    """

    def deco(cls: type) -> type:
        if name in _EVALUATORS:
            raise ValueError(
                f"Evaluator '{name}' is already registered as "
                f"{_EVALUATORS[name]!r}. Use a unique name."
            )
        _EVALUATORS[name] = cls
        logger.debug("Registered evaluator '%s' → %r", name, cls)
        return cls

    return deco


def get_evaluator(name: str) -> type:
    """Return the evaluator class registered under *name*.

    Args:
        name: Registry key used with ``@register_evaluator``.

    Returns:
        The registered class.

    Raises:
        KeyError: If *name* has not been registered.
    """
    if name not in _EVALUATORS:
        raise KeyError(
            f"No evaluator registered under '{name}'. "
            f"Known evaluators: {list(_EVALUATORS)}"
        )
    return _EVALUATORS[name]


def list_evaluators() -> list[str]:
    """Return a sorted list of all registered evaluator names.

    Returns:
        Sorted list of evaluator registry keys.
    """
    return sorted(_EVALUATORS)


# ---------------------------------------------------------------------------
# Metric registry
# ---------------------------------------------------------------------------


def register_metric(name: str):
    """Class decorator that registers a metric under *name*.

    Args:
        name: Registry key.  Must be unique; a duplicate raises
            ``ValueError``.

    Returns:
        The class unchanged (decorator pattern).

    Raises:
        ValueError: If *name* is already registered.

    Example::

        @register_metric("state_match")
        class StateMatch(Metric):
            ...
    """

    def deco(cls: type) -> type:
        if name in _METRICS:
            raise ValueError(
                f"Metric '{name}' is already registered as "
                f"{_METRICS[name]!r}. Use a unique name."
            )
        _METRICS[name] = cls
        logger.debug("Registered metric '%s' → %r", name, cls)
        return cls

    return deco


def get_metric(name: str) -> type:
    """Return the metric class registered under *name*.

    Args:
        name: Registry key used with ``@register_metric``.

    Returns:
        The registered class.

    Raises:
        KeyError: If *name* has not been registered.
    """
    if name not in _METRICS:
        raise KeyError(
            f"No metric registered under '{name}'. "
            f"Known metrics: {list(_METRICS)}"
        )
    return _METRICS[name]


def list_metrics() -> list[str]:
    """Return a sorted list of all registered metric names.

    Returns:
        Sorted list of metric registry keys.
    """
    return sorted(_METRICS)
