"""Dotted-path selection and per-item templating for ExecutionPlan.

Deliberately *not* JSONPath. The grammar is three constructs — dotted keys,
``[]`` to flatten a list, and ``[n]`` to index one — which is enough for
``for_each.select`` and :class:`~models.FacetSpec`, small enough to audit,
and has no evaluator to sandbox.

Grammar::

    path    := segment ( '.' segment )*
    segment := key | key '[]' | key '[' int ']'

Examples::

    "keys[]"                  -> the list at .keys
    "findings[].severity"     -> severity of every finding
    "metadata.scanner"        -> a scalar
    "findings[0].id"          -> id of the first finding
"""
from __future__ import annotations

import re
from typing import Any, List

__all__ = ("PathError", "compile_path", "render_key", "select")

_SEGMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_\-]*)(\[\]|\[(\d+)\])?$")
_ITEM_VAR_RE = re.compile(r"\{(index|item(?:\.[A-Za-z0-9_]+)*)\}")


class PathError(ValueError):
    """Raised when a path is malformed or cannot be resolved."""


def compile_path(path: str) -> List[tuple[str, str, int]]:
    """Parse ``path`` into segments, raising on malformed input.

    Parsing is separated from evaluation so a plan's paths can be checked at
    validation time, before any tool runs.

    Args:
        path: A dotted path, e.g. ``"findings[].severity"``.

    Returns:
        A list of ``(key, mode, index)`` triples where ``mode`` is one of
        ``"get"``, ``"flatten"`` or ``"index"``.

    Raises:
        PathError: If the path is empty or a segment is malformed.
    """
    text = path.strip()
    if not text:
        raise PathError("Empty path")
    segments: List[tuple[str, str, int]] = []
    for raw in text.split("."):
        match = _SEGMENT_RE.match(raw)
        if match is None:
            raise PathError(f"Malformed path segment {raw!r} in {path!r}")
        key, bracket, digits = match.group(1), match.group(2), match.group(3)
        if bracket is None:
            segments.append((key, "get", 0))
        elif digits is None:
            segments.append((key, "flatten", 0))
        else:
            segments.append((key, "index", int(digits)))
    return segments


def select(data: Any, path: str | None, *, default: Any = None) -> Any:
    """Resolve ``path`` against ``data``.

    A path containing ``[]`` always yields a list (flattened one level per
    marker); a path without one yields a single value. Missing keys resolve to
    ``default`` rather than raising, so a facet spec that does not match a
    particular payload degrades to a missing facet instead of failing the run.

    Args:
        data: The payload to read.
        path: A dotted path, or ``None`` to return ``data`` unchanged.
        default: Value returned when the path does not resolve.

    Returns:
        The selected value, a list when the path flattens, or ``default``.

    Raises:
        PathError: If the path is malformed.
    """
    if path is None:
        return data

    segments = compile_path(path)
    # Whether the result is a list is a property of the *path*, not of the
    # data: "findings[].id" against a payload with no findings must yield [],
    # not the scalar default. Otherwise a for_each over an empty result would
    # fan out over `None` instead of doing nothing.
    yields_list = any(mode == "flatten" for _, mode, _ in segments)

    current: Any = [data]
    for key, mode, index in segments:
        nxt: List[Any] = []
        for item in current:
            if not isinstance(item, dict) or key not in item:
                continue
            value = item[key]
            if mode == "get":
                nxt.append(value)
            elif mode == "flatten":
                if isinstance(value, (list, tuple)):
                    nxt.extend(value)
                else:
                    nxt.append(value)
            else:  # index
                if isinstance(value, (list, tuple)) and -len(value) <= index < len(value):
                    nxt.append(value[index])
        current = nxt
        if not current:
            break

    if yields_list:
        return current
    if not current:
        return default
    return current[0]


def render_key(template: str, *, item: Any, index: int) -> str:
    """Expand ``{index}``, ``{item}`` and ``{item.<field>}`` in a key template.

    Used for ``PlanNode.store_as`` under ``for_each``. Anything not matching a
    known variable is left untouched, so a literal brace in a key is
    preserved rather than silently mangled.

    Args:
        template: The key template, e.g. ``"report_{item.id}"``.
        item: The current item.
        index: The current zero-based position.

    Returns:
        The expanded key.

    Raises:
        PathError: If an ``{item.<field>}`` reference does not resolve.
    """

    def _substitute(match: re.Match) -> str:
        expr = match.group(1)
        if expr == "index":
            return str(index)
        if expr == "item":
            return str(item)
        field_path = expr[len("item."):]
        value = select(item, field_path, default=_MISSING)
        if value is _MISSING:
            raise PathError(
                f"Key template {template!r}: '{{{expr}}}' does not resolve "
                f"for item {item!r}"
            )
        return str(value)

    return _ITEM_VAR_RE.sub(_substitute, template)


class _Missing:
    """Sentinel distinguishing 'absent' from a legitimate ``None``."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<missing>"


_MISSING = _Missing()
