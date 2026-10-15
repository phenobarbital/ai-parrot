"""Node-dependency factories for the wiki-ingest pipeline (FEAT-481,
spec Module 6).

Mirrors ``parrot/flows/dev_loop/factories.py``'s role — building the live
dependencies (tiered LLM clients, vault access, registry) each pipeline
node needs — adapted to this subsystem's linear-pipeline shape (see
:mod:`~parrot.flows.wiki_ingest.definition`): callers construct node
callables directly rather than materializing a DAG's node factories.

Stub in Module 1 (TASK-2660) — populated as nodes are implemented by
later tasks.
"""

from __future__ import annotations
