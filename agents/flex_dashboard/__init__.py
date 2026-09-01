"""``agents/flex_dashboard`` — asset package for the Flex A2UI dashboard agent.

Companion package to ``agents/flex_dashboard.py`` (FEAT-491) — the two
share the same name at the same level of ``agents/``. Two corrections to
this package's original citation (external code-review findings, adopted;
see ``agents/flex_dashboard.py``'s module docstring for the full
consequence of this naming collision):

- ``agents/finance_reporter.py`` has NO sibling ``agents/finance_reporter/``
  directory — the spec's "same file+directory coexistence pattern" citation
  of it is inaccurate; FinanceReporter is a single file.
- ``agents/porygon.py`` + ``agents/porygon/`` are NOT tracked in git
  (``/agents/`` is blanket-ignored and neither was ever force-added) — they
  exist only in one developer's local working tree, so this precedent is
  unverifiable from a fresh clone or in CI.

Contains:

- :mod:`agents.flex_dashboard.normalize` — pure input canonicalization
  (currency parsing, month-grain alignment, column renames).
- :mod:`agents.flex_dashboard.transformers` — registered
  ``@infographic_transformer`` functions (TASK-2694).
- ``skills/`` — composite skill definitions (TASK-2698).
- ``kb/`` — knowledge-base markdown documents, one per KPI (TASK-2695).
"""

from __future__ import annotations
