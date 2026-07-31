---
type: Wiki Summary
title: parrot.bots.flows.result_agent
id: mod:parrot.bots.flows.result_agent
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ResultAgent — Registered Agent for Crew Infographic Rendering (FEAT-308).
relates_to:
- concept: class:parrot.bots.flows.result_agent.ResultAgent
  rel: defines
- concept: mod:parrot.bots.agent
  rel: references
- concept: mod:parrot.bots.flows.crew.result_infographic
  rel: references
- concept: mod:parrot.registry
  rel: references
- concept: mod:parrot.storage.artifacts
  rel: references
- concept: mod:parrot.storage.backends
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
- concept: mod:parrot.tools.infographic_toolkit
  rel: references
---

# `parrot.bots.flows.result_agent`

ResultAgent — Registered Agent for Crew Infographic Rendering (FEAT-308).

Spec: ``sdd/specs/agentcrew-node-infographic.spec.md`` §3 Module 3.

An internal ``Agent`` subclass, registered as ``"result-agent"`` in the
``AgentRegistry``, that carries an ``InfographicToolkit``. It receives a
crew's synthesis ``summary`` and the deterministic tab blocks (built by
:mod:`parrot.bots.flows.crew.result_infographic`), LLM-authors the Tab 1
(Executive Summary & Insights) blocks from the summary, merges them with the
deterministic blocks, and renders the merged block list through the
``crew_report`` template.

Codebase Contract corrections (verified against the real registry / toolkit
implementations on 2026-07-14):
    - ``@register_agent(...)`` (``agent_registry.register_bot_decorator``) is
      **keyword-only** (``def register_bot_decorator(self, *, name=None,
      ...)``, registry/registry.py:1205-1216). ``@register_agent("result-agent")``
      (positional, as shown in the spec's own §2 pseudo-code) raises
      ``TypeError``; the correct form is ``@register_agent(name="result-agent")``.
    - ``AgentRegistry`` has **no** ``.get(name)`` method. The verified
      lookup API is ``get_metadata(name) -> Optional[BotMetadata]``, whose
      ``.factory`` attribute holds the registered class
      (registry/registry.py:513-514, :43-63).
    - ``InfographicToolkit.__init__`` requires ``artifact_store: ArtifactStore``
      as a mandatory keyword-only argument (infographic_toolkit.py:134-141);
      there is no zero-arg constructor. Building the real ``ArtifactStore``
      (``build_conversation_backend()`` + ``.initialize()``) is async, but
      ``agent_tools()`` is called synchronously from ``BasicAgent.__init__``
      (agent.py:110). ``_LazyArtifactStore`` below defers the real backend
      construction to the first actual ``save_artifact()`` call (inside the
      async ``render()`` path), so ``ResultAgent()`` can be constructed
      without requiring a caller-supplied ``ArtifactStore``.
    - Default LLM: ``BasicAgent.__init__`` already falls back to
      ``GoogleGenAIClient()`` (whose ``_default_model`` is
      ``GoogleModel.GEMINI_FLASH_LATEST``) when no ``llm`` is supplied
      (agent.py:104-108) — no hardcoded model-id string is needed here,
      resolving the spec's §8 open question.

## Classes

- **`ResultAgent(Agent)`** — Internal agent that renders a crew's ExecutionMemory into a crew_report infographic.
