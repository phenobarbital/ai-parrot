"""The ``viz-core`` A2UI catalog — identity and instructions (FEAT-529 Module 0).

``viz-core`` is the third A2UI catalog (alongside the official Basic Catalog
and the Parrot catalog): a library-agnostic, "describe what, never how"
visualization vocabulary. This module carries only the catalog's IDENTITY —
its id and its header-level LLM instructions (spec §2 Overview) — not any
registered component. ``Graph`` (FEAT-529 Module 2, ``catalog/viz_core/
graph.py``) is the first component to register under
:data:`VIZ_CORE_CATALOG_ID`; importing it here for its registration side
effect is that module's job, not this one's — this package intentionally
registers nothing so Module 0 can land and be tested on its own.

:data:`VIZ_CORE_INSTRUCTIONS` is copied VERBATIM from the design artifact's
own ``instructions`` field (vendored at ``catalog/viz_core/spec/catalog.json``,
a copy of ``sdd/proposals/assets/a2ui-viz-core/viz-core.catalog.json`` — not
loaded at runtime by this module; it exists so the ``a2ui-viz-core-charts``
sibling spec has a drift guard to test against later).
"""

from __future__ import annotations

from typing import Final

__all__ = ["VIZ_CORE_CATALOG_ID", "VIZ_CORE_INSTRUCTIONS"]

#: The viz-core catalog's own ``$id``/``catalogId`` (verified against the
#: vendored ``spec/catalog.json``, spec §8 open question: kept as authored).
VIZ_CORE_CATALOG_ID: Final[str] = "https://ai-parrot.dev/a2ui/catalogs/viz-core/1.0/catalog.json"

#: The nine viz-core guideline rules (verbatim from the vendored catalog
#: draft's ``instructions`` field) — prepended by
#: :func:`~parrot.outputs.a2ui.catalog.catalog_instructions` whenever a
#: caller scopes the LLM system prompt to include ``VIZ_CORE_CATALOG_ID``
#: (:func:`~parrot.outputs.a2ui.catalog.catalog_header_instructions`).
VIZ_CORE_INSTRUCTIONS: Final[str] = (
    "## Viz Core Guidelines\n"
    "\n"
    "1. Pick the form by the data's job, not by taste: change over time -> "
    "`line` (or `area` only for a single series or a stacked total); "
    "magnitude across categories -> `bar` (horizontal when labels are long); "
    "part-to-whole -> `bar` with `stack: \"percent\"`, or `arc` ONLY with <= 5 "
    "categories; correlation -> `point`; one headline number -> `Stat`, not a "
    "chart.\n"
    "2. ONE y axis per Chart. Never ask for two y scales. Two measures of "
    "different magnitude -> two Charts side by side (Row) or index both to a "
    "common base.\n"
    "3. Bind data with a path to an array of row objects in the data model "
    '(`"data": {"path": "/sales/rows"}`). Prepare the rows before binding '
    "(tidy, sorted, aggregated); the renderer does not transform data.\n"
    "4. Wide data: one `Series` per value column (`field`). Long data (one "
    "category column, one value column): set `seriesBy` on the Chart to the "
    "category field and ONE Series with the value `field`.\n"
    "5. Always give `x.type`: `temporal` for dates/times, `quantitative` for "
    "numbers, `ordinal` for ordered buckets, `nominal` for names. The "
    "renderer cannot infer this reliably.\n"
    "6. Color is semantic. Never send hex. Series get `color.role: "
    '"categorical"` (default, assigned in fixed slot order by the '
    'renderer\'s theme) or `"status"` with a `value` (good/warning/serious/'
    "critical). Use `sequential`/`diverging` only for `rect` (heatmap-like) "
    "marks.\n"
    "7. Formats are semantic (`unit`, `format: \"currency\"|\"percent\"|"
    '"compact"|"integer"`), never printf strings; the renderer applies '
    "locale.\n"
    "8. More than 8 series is a design error: fold to \"Other\" before "
    "binding, or facet into several Charts.\n"
    "9. Do not set `metadata.extensions` render hints unless a human asked "
    "for a library-specific override; they are non-portable."
)
