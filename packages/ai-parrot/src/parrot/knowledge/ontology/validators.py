"""AQL security validation for LLM-generated queries.

Ensures that dynamic AQL from the intent resolver is read-only,
depth-limited, and does not access system collections or execute JavaScript.
"""
from __future__ import annotations

import re

from .exceptions import AQLValidationError

# Mutation keywords that indicate a write operation
_MUTATION_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|REMOVE|REPLACE|UPSERT)\b",
    re.IGNORECASE,
)

# System collections that must never be accessed
_SYSTEM_COLLECTIONS = re.compile(
    r"\b(_system|_graphs|_modules|_analyzers|_jobs|_queues)\b",
    re.IGNORECASE,
)

# JavaScript execution keywords
_JS_PATTERN = re.compile(
    r"\b(APPLY|CALL|V8)\s*\(",
    re.IGNORECASE,
)

# Traversal depth pattern: matches "1..N" or "..N" in traversal syntax
_TRAVERSAL_DEPTH_PATTERN = re.compile(
    r"\b(\d+)\.\.(\d+)\b"
)


async def validate_aql(
    aql: str,
    max_depth: int | None = None,
) -> str:
    """Validate LLM-generated AQL for safety.

    Checks (in order):
        1. No mutation keywords (INSERT, UPDATE, REMOVE, REPLACE, UPSERT).
        2. No system collection access (_system, _graphs, _modules, etc.).
        3. No inline JavaScript execution (APPLY, CALL, V8).
        4. Traversal depth does not exceed ``max_depth``.

    Args:
        aql: The AQL query string to validate.
        max_depth: Maximum allowed traversal depth. If None, uses
            ``ONTOLOGY_MAX_TRAVERSAL_DEPTH`` from conf.

    Returns:
        The validated AQL string (unchanged).

    Raises:
        AQLValidationError: If any safety check fails, with a message
            indicating which check was violated.
    """
    if max_depth is None:
        try:
            from parrot.conf import ONTOLOGY_MAX_TRAVERSAL_DEPTH
            max_depth = ONTOLOGY_MAX_TRAVERSAL_DEPTH
        except (ImportError, AttributeError):
            max_depth = 4
        if max_depth is None:
            max_depth = 4

    # 1. No mutations
    match = _MUTATION_PATTERN.search(aql)
    if match:
        raise AQLValidationError(
            f"AQL contains mutation keyword '{match.group()}'. "
            f"Only read-only queries are allowed for dynamic AQL."
        )

    # 2. No system collections
    match = _SYSTEM_COLLECTIONS.search(aql)
    if match:
        raise AQLValidationError(
            f"AQL accesses system collection '{match.group()}'. "
            f"System collections are not allowed in dynamic AQL."
        )

    # 3. No JavaScript execution
    match = _JS_PATTERN.search(aql)
    if match:
        raise AQLValidationError(
            f"AQL contains JavaScript execution '{match.group().strip()}'. "
            f"JavaScript execution is not allowed in dynamic AQL."
        )

    # 4. Traversal depth check
    for depth_match in _TRAVERSAL_DEPTH_PATTERN.finditer(aql):
        depth = int(depth_match.group(2))
        if depth > max_depth:
            raise AQLValidationError(
                f"AQL traversal depth {depth} exceeds maximum allowed "
                f"depth of {max_depth}. Reduce the traversal range."
            )

    return aql
