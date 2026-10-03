"""Fireflies → Obsidian LLM-Wiki Knowledge-Base ingest flow subsystem.

FEAT-481. Modeled on ``parrot/flows/dev_loop/`` (``definition.py`` +
``factories.py`` + ``nodes/`` + ``runner.py``). This package is
**additive-only** (spec G11): it never imports for the purpose of editing,
and never modifies, ``parrot/agents/obsidian.py``,
``parrot/agents/fireflies_wiki.py``, ``parrot/tools/obsidian.py``, or any
FEAT-472 file — it only reuses them by import/inheritance/composition.

See ``sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`` and the
operating contract ``sdd/references/obsidian-wiki-operating-contract.md``
for the full design.
"""

from __future__ import annotations
