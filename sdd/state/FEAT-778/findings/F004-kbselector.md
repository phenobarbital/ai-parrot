---
id: F004
query_id: Q023
type: read
intent: "Read bots/kb.py — the KB bot / loader; check for budget, ordering, provenance."
executed_at: 2026-10-30T16:41:41Z
duration_ms: 500
parent_id: null
depth: 0
merged_from: [FC-004-kbselector]
---

# F004 — `bots/kb.py` is only the LLM-based KBSelector (which KBs to activate), not a loader

## Summary

`kb.py` (170 lines) defines `KBSelected`, `KBOutput` (Pydantic) and `KBSelector`, which asks an LLM to pick relevant KBs from `knowledge_bases` descriptions (`select_kbs`, `_fallback_selection`, cache keyed by question). No loading order, budget or provenance logic lives here.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/kb.py`
  lines: 12-60
  symbol: `KBSelected / KBOutput / KBSelector`
  excerpt: |
    class KBSelected(BaseModel): ...
    class KBOutput(BaseModel): ...
    class KBSelector:
        def __init__(self, llm_client, min_confidence, kbs): self.knowledge_bases = kbs or []
        async def select_kbs(self, question, available_kbs) -> KBOutput

## Notes

Wired at `abstract.py:1753` as `KBSelector(llm_client=self._llm, min_confidence=0.6, kbs=self.knowledge_bases)`.
