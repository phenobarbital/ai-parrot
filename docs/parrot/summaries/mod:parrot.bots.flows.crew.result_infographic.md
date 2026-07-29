---
type: Wiki Summary
title: parrot.bots.flows.crew.result_infographic
id: mod:parrot.bots.flows.crew.result_infographic
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Deterministic Tab-Assembly Helper for AgentCrew Infographic (FEAT-308).
relates_to:
- concept: func:parrot.bots.flows.crew.result_infographic.build_deterministic_tabs
  rel: defines
- concept: func:parrot.bots.flows.crew.result_infographic.merge_tab1_blocks
  rel: defines
- concept: mod:parrot.bots.flows.core.storage.memory
  rel: references
- concept: mod:parrot.tools.infographic_toolkit
  rel: references
---

# `parrot.bots.flows.crew.result_infographic`

Deterministic Tab-Assembly Helper for AgentCrew Infographic (FEAT-308).

Spec: ``sdd/specs/agentcrew-node-infographic.spec.md`` §3 Module 2.

Reads a crew's ``ExecutionMemory`` and builds the deterministic block list
for the ``crew_report`` infographic template: the Final-Result tab (Tab 2)
plus one tab per research agent (Tabs 3...N), excluding the ResultAgent's own
``node_id``. Large or non-text results are summarized (truncated with a
note) or linked out via an optional ``ArtifactStore``-like object, never
dumped raw into a tab. The LLM-authored Tab 1 (Executive Summary & Insights)
is merged in front by ``merge_tab1_blocks``.

Codebase Contract corrections (verified against
``parrot/models/infographic.py`` on 2026-07-14):
    - Block dicts are discriminated by the ``"type"`` key (e.g.
      ``{"type": "title", ...}``), NOT ``"block_type"`` as an earlier draft
      of this task's pseudo-code suggested. Verified via
      ``InfographicToolkit._validate_blocks`` (``block_raw.get("type")``,
      infographic_toolkit.py:981).
    - ``TitleBlock`` uses a ``title`` field, not ``content``
      (infographic.py:213-220).
    - ``TabPane`` requires an ``id`` field (unique slug), not just ``label``
      (infographic.py:196-206).
    - Per-tab content blocks use ``SummaryBlock`` (``type="summary"``,
      ``content: str``), which has its own hard ``max_length=2000``
      constraint (infographic.py:365-377) — independent of and much smaller
      than ``_INLINE_THRESHOLD`` (50_000, infographic_toolkit.py:49, which
      gates the *page-level* ``html_inline`` decision). Content is therefore
      always truncated to fit within ``SummaryBlock.content``'s limit, with
      an explicit truncation note appended whenever the underlying result
      exceeds ``_INLINE_THRESHOLD`` or the block's own max length.
    - ``ArtifactStore`` (``parrot/storage/artifacts.py``) requires
      ``user_id``/``agent_id``/``session_id`` plus initialised backends to
      call ``save_artifact()`` — none of which this pure(ish) helper has
      access to. ``artifact_store`` therefore accepts an optional duck-typed
      object exposing ``publish(key: str, content: str) -> Optional[str]``;
      when absent (the default), large results fall back to truncation +
      note. TODO: wire the real ``ArtifactStore`` once a session context is
      threaded through ``AgentCrew._finalize_infographic`` (TASK-1779).

## Functions

- `def build_deterministic_tabs(execution_memory: ExecutionMemory, final_output: Any, exclude_node_id: Optional[str]=None, artifact_store: Optional[Any]=None) -> List[Dict[str, Any]]` — Build the deterministic ``crew_report`` block list.
- `def merge_tab1_blocks(tab1_blocks: List[Dict[str, Any]], deterministic_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]` — Insert the LLM-authored Tab 1 as the first tab in the ``tab_view``.
