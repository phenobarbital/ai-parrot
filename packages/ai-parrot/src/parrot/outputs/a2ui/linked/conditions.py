"""Canonical ``SourceRequest`` → QuerySource ``conditions`` derivation (FEAT-598 S5, spec §7).

Every executor re-implements these rules from ``contract/fixtures/conditions/*.json``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest

#: Keys a lane adds at fetch time; derive_conditions never emits them.
LANE_TIME_KEYS: frozenset[str] = frozenset({"querylimit", "refresh"})


def derive_conditions(request: SourceRequest, *, locked: Mapping[str, Any]) -> dict[str, Any]:
    """Return the deterministic QuerySource payload for ``request`` with ``locked`` values applied.

    Args:
        request: The structured, editable request.
        locked: Locked parameter values; they win over same-named placeholders.

    Returns:
        A new dict; key order is part of the contract.
    """
    payload: dict[str, Any] = dict(request.placeholders)
    for key, value in locked.items():
        payload[key] = value
    if request.filter:
        payload["filter"] = dict(request.filter)
    for key, val in (("fields", request.fields), ("ordering", request.ordering), ("grouping", request.grouping)):
        if val:
            payload[key] = list(val)
    if request.offset:
        payload["_offset"] = int(request.offset)
    return payload


def locked_values(source: LinkedDataSource) -> dict[str, Any]:
    """Return ``{name: value}`` for every locked name present in ``source.conditions``."""
    return {name: source.conditions[name] for name in source.locked if name in source.conditions}
