"""Declarative §27 ingest-pipeline topology (FEAT-481, spec Module 6).

Unlike ``parrot/flows/dev_loop/definition.py`` (a branching DAG executed by
the ``AgentsFlow`` engine), the wiki-ingest pipeline is a **linear,
per-meeting sequence** (contract §27's 24 ordered steps, spec Module 6) —
so this module lists the step order as plain data for introspection and
testing, rather than building a :class:`~parrot.bots.flows.flow.definition.
FlowDefinition` graph. :mod:`~parrot.flows.wiki_ingest.runner` executes the
steps directly as ordered async calls into :mod:`~parrot.flows.wiki_ingest.
nodes`.

Stub in Module 1 (TASK-2660) — step ids are filled in as their owning
nodes are implemented by later tasks.
"""

from __future__ import annotations

#: Ordered ingest pipeline step ids (spec §27 / Module 6). Each id names a
#: ``nodes.<id>`` module once implemented. Empty in Module 1.
INGEST_PIPELINE_STEPS: tuple[str, ...] = ()
