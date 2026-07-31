"""Plain ``{param}`` substitution and built-in relative-date resolvers (Module 1, FEAT-324).

Deliberately NOT a Jinja/expression engine: only exact ``{name}`` placeholders
are replaced from a validated dict. Unknown placeholders and undeclared
override params both raise — this is the typo-protection acceptance
criterion (spec §5).

Core-side, dependency-free (spec G8): stdlib only (``re``, ``datetime``,
``zoneinfo``).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from parrot.outputs.a2ui.recipes.models import RecipeParam

__all__ = [
    "resolve_date",
    "resolve_params",
    "substitute",
]

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")

#: Names of the five built-in relative-date resolvers (spec G3).
DATE_RESOLVERS = (
    "current_month",
    "previous_month",
    "today",
    "yesterday",
    "first_of_month",
)


def resolve_date(resolver: str, *, tz: str = "UTC", now: datetime | None = None) -> str:
    """Resolve a built-in relative-date resolver name to a literal string value.

    Args:
        resolver: One of ``"current_month"``, ``"previous_month"``, ``"today"``,
            ``"yesterday"``, ``"first_of_month"``.
        tz: IANA timezone name used to compute "now" (default ``"UTC"``).
        now: Injectable current time for deterministic testing; defaults to
            ``datetime.now(tz)``.

    Returns:
        ``"YYYY-MM"`` for month resolvers, ``"YYYY-MM-DD"`` for day resolvers.

    Raises:
        ValueError: If ``resolver`` is not a recognized built-in resolver name.
    """
    current = now or datetime.now(ZoneInfo(tz))

    if resolver == "current_month":
        return current.strftime("%Y-%m")
    if resolver == "previous_month":
        first_of_current = current.replace(day=1)
        last_of_previous = first_of_current - timedelta(days=1)
        return last_of_previous.strftime("%Y-%m")
    if resolver == "today":
        return current.strftime("%Y-%m-%d")
    if resolver == "yesterday":
        return (current - timedelta(days=1)).strftime("%Y-%m-%d")
    if resolver == "first_of_month":
        return current.replace(day=1).strftime("%Y-%m-%d")

    raise ValueError(
        f"Unknown date resolver {resolver!r}; expected one of {DATE_RESOLVERS!r}"
    )


def _is_resolver(value: str | None) -> bool:
    return value in DATE_RESOLVERS


def resolve_params(
    declared: list[RecipeParam],
    overrides: dict[str, Any] | None = None,
    *,
    tz: str = "UTC",
    now: datetime | None = None,
) -> dict[str, str]:
    """Resolve a recipe's declared parameters to their final string values.

    Precedence: an override wins over the declared default. Defaults that name
    a built-in resolver (see :data:`DATE_RESOLVERS`) are resolved via
    :func:`resolve_date`; overrides are never resolver names — always taken
    literally (an operator supplying an override is choosing an exact value).

    Args:
        declared: The recipe's declared :class:`RecipeParam` list.
        overrides: Caller-supplied override values, keyed by param name.
        tz: IANA timezone name for resolver evaluation (default ``"UTC"``).
        now: Injectable current time for deterministic testing.

    Returns:
        A flat ``{name: value}`` dict, one entry per declared param.

    Raises:
        ValueError: If ``overrides`` contains a name not present in ``declared``
            (undeclared override / typo protection).
    """
    overrides = overrides or {}
    declared_names = {p.name for p in declared}
    unknown = set(overrides) - declared_names
    if unknown:
        raise ValueError(
            "Override parameter(s) not declared on this recipe: "
            f"{sorted(unknown)!r}"
        )

    resolved: dict[str, str] = {}
    for param in declared:
        if param.name in overrides:
            resolved[param.name] = str(overrides[param.name])
        elif _is_resolver(param.default):
            resolved[param.name] = resolve_date(param.default, tz=tz, now=now)
        elif param.default is not None:
            resolved[param.name] = param.default
        else:
            raise ValueError(
                f"Parameter {param.name!r} has no default and no override was supplied"
            )
    return resolved


def substitute(template: str, values: dict[str, str]) -> str:
    """Substitute exact ``{name}`` placeholders in ``template`` from ``values``.

    Non-eval by design: only literal placeholder replacement, never expression
    evaluation. Every placeholder found in ``template`` must have a matching
    key in ``values``.

    Args:
        template: A string possibly containing ``{name}`` placeholders.
        values: Resolved parameter values, keyed by name.

    Returns:
        ``template`` with every placeholder replaced.

    Raises:
        ValueError: If ``template`` contains a placeholder absent from
            ``values``.
    """

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise ValueError(
                f"Placeholder {{{name}}} has no resolved value "
                f"(available: {sorted(values)!r})"
            )
        return values[name]

    return _PLACEHOLDER_RE.sub(_replace, template)
