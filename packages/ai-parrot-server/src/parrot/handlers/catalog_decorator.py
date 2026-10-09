"""Host hook that decorates the catalogue rows a caller is shown (PA-6).

A host registers ONE callable under :data:`STUDIO_CATALOG_DECORATOR`::

    app[STUDIO_CATALOG_DECORATOR] = lambda kind, row: {**row, "label": LABELS.get(row["slug"], row["slug"])}

``kind`` is one of :data:`CATALOG_KINDS` (``"tools"``, ``"base-classes"``, ``"llm-clients"``); ``row`` is a COPY of the
catalogue row (the shared process-wide cache is never mutated); the return value replaces the row, and ``None``
hides it. It runs synchronously after the policy filtering, once per visible row. A decorator that raises hides
the row (fail closed) and is logged once per request and kind.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Mapping
from typing import Any, Literal

logger = logging.getLogger(__name__)

STUDIO_CATALOG_DECORATOR = "studio_catalog_decorator"
CatalogKind = Literal["tools", "base-classes", "llm-clients"]
CATALOG_KINDS: tuple[str, ...] = ("tools", "base-classes", "llm-clients")
CatalogDecorator = Callable[[str, dict[str, Any]], "dict[str, Any] | None"]


def decorate_rows(app: Mapping[str, Any], kind: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``rows`` after the host decorator (a copy; ``rows`` itself is returned untouched when none is registered)."""
    decorator = app.get(STUDIO_CATALOG_DECORATOR)
    if decorator is None:
        return rows
    out: list[dict[str, Any]] = []
    failed = False
    for row in rows:
        try:
            decorated = decorator(kind, copy.deepcopy(row))
        except Exception:  # pylint: disable=broad-except
            if not failed:
                logger.exception("catalogue decorator failed for kind %r; hiding the row (fail closed)", kind)
                failed = True
            continue
        if decorated is not None:
            out.append(decorated)
    return out
