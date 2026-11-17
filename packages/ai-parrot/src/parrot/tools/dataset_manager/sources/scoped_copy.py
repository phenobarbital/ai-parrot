"""Request-scoped copies of :class:`DataSource` instances.

RLS injection must never mutate a source that outlives the request: the
``AuthorizingDataSource`` wrapper and the per-user ``DatasetManager`` clones both
hold long-lived references, so an in-place rewrite leaks one subject's predicates
into another subject's queries (``issue:90cf04ce8edd``).
"""

from __future__ import annotations

import copy

from .base import DataSource

__all__ = ("request_scoped_copy",)


def request_scoped_copy(source: DataSource) -> DataSource:
    """Return a copy of ``source`` that RLS injection may safely mutate.

    A shallow copy is enough for every attribute the RLS injectors rebind
    (``sql``, ``required_filter``), but ``inject_rls_table_source`` and
    ``inject_rls_query_slug`` write *into* ``_permanent_filter``, so that dict is
    replaced with a fresh one. A deep copy is deliberately avoided: sources carry
    credentials objects and cached schema, which are expensive and sometimes
    impossible to deep-copy.

    Args:
        source: The data source to isolate for the current request.

    Returns:
        A copy safe to mutate; ``source`` itself is left untouched.
    """
    scoped = copy.copy(source)
    permanent_filter = getattr(scoped, "_permanent_filter", None)
    if isinstance(permanent_filter, dict):
        scoped._permanent_filter = dict(permanent_filter)
    return scoped
