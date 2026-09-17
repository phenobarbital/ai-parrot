---
id: F008
query_id: Q008
type: read
intent: Attribution must survive final context packing
executed_at: 2026-09-17T21:50:09.640444+00:00
duration_ms: null
parent_id: null
depth: 1
---

# F008 — Attribution must survive final context packing

## Summary

MemoryContext stores strings and token counts without an injected-ID manifest. UnifiedMemoryManager gathers text sections and ContextAssembler truncates them to section budgets. Tracking candidates before packing would credit memories not actually delivered to the model. The two coder prompt copies request prose about checked patterns; this is not verified structured evidence.

## Citations

- path: `packages/ai-parrot/src/parrot/memory/unified/models.py`
  lines: 13-43
  symbol: `MemoryContext`
  excerpt: |
        """Assembled context from all memory subsystems.

        Holds the text sections retrieved from episodic memory,
        skill registry, and conversation history, along with

- path: `packages/ai-parrot/src/parrot/memory/unified/manager.py`
  lines: 158-175
  symbol: `UnifiedMemoryManager.get_context_for_query`
  excerpt: |
            episodic_task = self._get_episodic_warnings(query)
            skills_task = self._get_relevant_skills(query)
            conversation_task = self._get_conversation(user_id, session_id)
            brain_task = self._get_brain_knowledge(query)

- path: `packages/ai-parrot/src/parrot/memory/unified/context.py`
  lines: 49-129
  symbol: `ContextAssembler.assemble`
  excerpt: |
        def assemble(
            self,
            episodic_warnings: str = "",
            relevant_skills: str = "",

- path: `.claude/agents/sdd-coder.md`
  lines: 115-124
  symbol: `Apply Previous Delivery Feedback`
  excerpt: |
    ### a.1) Apply Previous Delivery Feedback

    Read `coder_feedback` in your brief (or the native dispatch prompt) before writing code. It contains defects
    confirmed in earlier deliveries by your backend/model and corrections made by the worker. For each relevant

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-coder.md`
  lines: 115-124
  symbol: `Apply Previous Delivery Feedback`
  excerpt: |
    ### a.1) Apply Previous Delivery Feedback

    Read `coder_feedback` in your brief (or the native dispatch prompt) before writing code. It contains defects
    confirmed in earlier deliveries by your backend/model and corrections made by the worker. For each relevant

## Notes

Read-only inspection at dev HEAD 9ab95566e5982dbc3fe1cee8b03789ddcf6f161c. Proposed changes are inferences, not existing APIs. Range excerpts are locators; the summary uses the inspected surrounding range.
