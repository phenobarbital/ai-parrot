"""Extras computation and cap enforcement for the unknown-fields policy.

This module holds the two pure functions that carry the tricky logic in
FEAT-458 — deliberately isolated from any form, handler, or database so the
hard cases (a declared-but-empty answer, a nested GROUP child, a payload one
byte over the cap) are plain unit tests.

This module is intentionally **policy-blind**: it does not read
``FormSchema.unknown_fields`` and imports nothing from the wider package
namespace. The caller (the handler) decides what to do with the extras
this module computes and the caps it enforces.
"""

from __future__ import annotations

import json
from typing import Any, Literal

MAX_EXTRA_KEYS: int = 256
MAX_EXTRA_BYTES: int = 256 * 1024  # 256 KiB, serialized JSON


class ExtrasCapExceeded(ValueError):
    """Raised when captured extras exceed a configured cap.

    Attributes:
        limit: Which cap was exceeded — ``"keys"`` or ``"bytes"``.
        actual: The measured value.
        maximum: The configured ceiling.
    """

    def __init__(self, *, limit: Literal["keys", "bytes"], actual: int, maximum: int) -> None:
        self.limit = limit
        self.actual = actual
        self.maximum = maximum
        super().__init__(f"Captured extras exceed the {limit} cap: {actual} > {maximum}")


def compute_extra_data(
    payload: dict[str, Any],
    declared_field_ids: set[str],
) -> dict[str, Any]:
    """Return the payload's top-level keys that no declared field_id covers.

    Pure, synchronous, and policy-free. ``declared_field_ids`` MUST come from
    the recursive traversal — never from ``sanitized_data.keys()``, which
    omits declared fields whose coerced value was ``None``.

    Args:
        payload: The submitted answers, AFTER ``visit_context`` extraction
            and AFTER the ``onBeforeSubmit`` hook may have replaced them.
        declared_field_ids: Every ``field_id`` the schema declares, from the
            recursive traversal (GROUP ``children`` and ARRAY
            ``item_template`` included).

    Returns:
        A new dict of the undeclared entries. Empty dict when there are none.
    """
    return {k: v for k, v in payload.items() if k not in declared_field_ids}


def enforce_extras_cap(
    extras: dict[str, Any],
    *,
    max_keys: int = MAX_EXTRA_KEYS,
    max_bytes: int = MAX_EXTRA_BYTES,
) -> None:
    """Raise ``ExtrasCapExceeded`` when ``extras`` exceeds either cap.

    Never truncates — truncation would reintroduce the silent-loss defect
    this feature exists to remove. Does not mutate ``extras``.

    Args:
        extras: The captured undeclared keys to check.
        max_keys: Maximum number of top-level keys allowed.
        max_bytes: Maximum serialized (UTF-8 encoded) JSON size, in bytes.

    Raises:
        ExtrasCapExceeded: When the key count or serialized byte size
            exceeds its cap.
    """
    key_count = len(extras)
    if key_count > max_keys:
        raise ExtrasCapExceeded(limit="keys", actual=key_count, maximum=max_keys)

    byte_count = len(json.dumps(extras).encode("utf-8"))
    if byte_count > max_bytes:
        raise ExtrasCapExceeded(limit="bytes", actual=byte_count, maximum=max_bytes)
