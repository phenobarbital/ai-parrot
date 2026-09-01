"""``agents/flex_dashboard`` — asset package for the Flex A2UI dashboard agent.

Companion package to ``agents/flex_dashboard.py`` (FEAT-491), mirroring the
file+directory coexistence pattern used by ``agents/porygon.py`` /
``agents/finance_reporter.py``. Contains:

- :mod:`agents.flex_dashboard.normalize` — pure input canonicalization
  (currency parsing, month-grain alignment, column renames).
- :mod:`agents.flex_dashboard.transformers` — registered
  ``@infographic_transformer`` functions (TASK-2694).
- ``skills/`` — composite skill definitions (TASK-2698).
- ``kb/`` — knowledge-base markdown documents, one per KPI (TASK-2695).
"""

from __future__ import annotations
