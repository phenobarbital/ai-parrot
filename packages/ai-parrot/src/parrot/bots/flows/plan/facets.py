"""Facet extraction — the only thing a model ever learns about a payload.

A facet is a small, structural, cheap-to-compute value pulled out of a tool
result before the result is put away in working memory. Facets are what
``PlanNode.when`` guards read and what appears in the
:class:`~.models.ExecutionManifest`, so they are also the *entire* budget for
data-dependent control flow. Everything here is bounded by construction:
group counts are capped, strings are clipped, and nothing recurses into a
payload body.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping

from .models import FacetSpec
from .paths import PathError, select

__all__ = ("MAX_FACET_STR", "estimate_bytes", "extract_facets", "merge_facets")

# Longest string value kept verbatim in a facet. Facets exist to be cheap;
# a long one defeats the purpose.
MAX_FACET_STR = 200


def extract_facets(payload: Any, spec: FacetSpec) -> Dict[str, Any]:
    """Extract facets from one payload.

    A path that does not resolve yields no facet rather than a ``None``
    entry, so a guard reading it fails safe (and the validator is what warns
    about the typo — see ``validator._check_guard``).

    Args:
        payload: The tool result.
        spec: What to extract.

    Returns:
        A flat ``{facet_name: value}`` mapping.
    """
    facets: Dict[str, Any] = {}

    for name, path in spec.paths.items():
        value = _safe_select(payload, path)
        if value is not None:
            facets[name] = _clip(value)

    for name, path in spec.counts.items():
        value = _safe_select(payload, path)
        facets[name] = len(value) if isinstance(value, (list, tuple)) else 0

    for name, path in spec.group_counts.items():
        value = _safe_select(payload, path)
        if isinstance(value, (list, tuple)):
            facets[name] = _top_counts(value, spec.max_group_keys)
        else:
            facets[name] = {}

    return facets


def merge_facets(
    per_item: Iterable[Mapping[str, Any]], spec: FacetSpec
) -> Dict[str, Any]:
    """Combine per-item facets from a ``for_each`` node into one mapping.

    Counts sum, group counts merge key-wise (re-capped after merging), and
    plain paths collapse to the set of distinct values seen — capped, because
    a per-item path over 3.000 items is not a facet any more.

    Args:
        per_item: Facet mappings, one per successfully executed item.
        spec: The spec they were extracted with.

    Returns:
        The merged mapping.
    """
    items: List[Mapping[str, Any]] = [dict(entry) for entry in per_item]
    merged: Dict[str, Any] = {}

    for name in spec.counts:
        merged[name] = sum(int(entry.get(name, 0) or 0) for entry in items)

    for name in spec.group_counts:
        counter: Counter = Counter()
        for entry in items:
            group = entry.get(name)
            if isinstance(group, Mapping):
                counter.update({k: int(v) for k, v in group.items()})
        merged[name] = _top_counts_from_counter(counter, spec.max_group_keys)

    for name in spec.paths:
        distinct: List[Any] = []
        for entry in items:
            value = entry.get(name)
            if value is not None and value not in distinct:
                distinct.append(value)
            if len(distinct) > spec.max_group_keys:
                break
        if len(distinct) == 1:
            merged[name] = distinct[0]
        elif distinct:
            merged[name] = distinct[: spec.max_group_keys]

    return merged


def estimate_bytes(payload: Any) -> int:
    """Approximate the serialized size of ``payload``.

    Used only to surface rehydration cost in the manifest, so an estimate is
    enough — and it must never raise on an exotic object.

    Args:
        payload: Any tool result.

    Returns:
        Approximate size in bytes; ``0`` when it cannot be measured.
    """
    if payload is None:
        return 0
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return len(payload)
    if isinstance(payload, str):
        return len(payload.encode("utf-8", errors="ignore"))
    try:
        import json  # noqa: PLC0415

        return len(json.dumps(payload, default=str).encode("utf-8", errors="ignore"))
    except Exception:  # noqa: BLE001 - never fail a run over a size estimate
        try:
            return len(repr(payload).encode("utf-8", errors="ignore"))
        except Exception:  # noqa: BLE001  # pragma: no cover
            return 0


def _safe_select(payload: Any, path: str) -> Any:
    """Resolve ``path``, returning ``None`` on a malformed path.

    Paths are already checked by the validator; this guards the case where a
    plan was constructed programmatically and never validated.
    """
    try:
        return select(payload, path)
    except PathError:
        return None


def _top_counts(values: Iterable[Any], limit: int) -> Dict[str, int]:
    """Count occurrences of hashable-ish values, keeping the ``limit`` largest."""
    counter: Counter = Counter(_key_of(value) for value in values)
    return _top_counts_from_counter(counter, limit)


def _top_counts_from_counter(counter: Counter, limit: int) -> Dict[str, int]:
    """Return the ``limit`` most common entries, ties broken by key for stability."""
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return {str(key): int(count) for key, count in ordered[:limit]}


def _key_of(value: Any) -> str:
    """Coerce a grouping value into a stable string key."""
    if isinstance(value, str):
        return value[:MAX_FACET_STR]
    if isinstance(value, (int, float, bool)) or value is None:
        return str(value)
    return repr(value)[:MAX_FACET_STR]


def _clip(value: Any) -> Any:
    """Clip a scalar facet so one long string cannot bloat the manifest."""
    if isinstance(value, str) and len(value) > MAX_FACET_STR:
        return value[:MAX_FACET_STR] + "…"
    if isinstance(value, (list, tuple)):
        return [_clip(item) for item in value[:MAX_FACET_STR]]
    return value
