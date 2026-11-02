---
id: F003
query_id: Q022
type: grep
intent: "Locate the current KB loader entrypoints the source says it would replace."
executed_at: 2026-10-30T16:41:41Z
duration_ms: 700
parent_id: null
depth: 0
merged_from: [FC-003-kb-loading-path]
---

# F003 — Current KB path: `AbstractBot.knowledge_bases` list sorted by `priority`, activated per question by KBSelector/should_activate; no token budget or revision tracking

## Summary

30 matches, all in `bots/`. `AbstractBot.register_kb()` appends an `AbstractKnowledgeBase` (from `parrot/stores/kb/abstract.py`) and sorts by `priority` desc; `configure_kb()` only seeds a `kb_store` with facts. At ask-time (abstract.py ~3898-3945) each KB is activated either by the LLM `KBSelector` or by `kb.should_activate()`, with `always_active` KBs forced on, then searched with `k=5, score_threshold=0.5`. `bots/stores/local.py` adds a local KB from `AGENTS_DIR/<agent_name>/kb/`. There is no ordered-layer resolver, no per-layer token quota, no source revision in the context — matching the source's "funcional, sin optimizar".

## Citations

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 1189-1198
  symbol: `AbstractBot.register_kb`
  excerpt: |
    def register_kb(self, kb: AbstractKnowledgeBase):
        self.knowledge_bases.append(kb)
        self.knowledge_bases.sort(key=lambda x: x.priority, reverse=True)

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 1577-1585
  symbol: `AbstractBot.configure_kb`
  excerpt: |
    async def configure_kb(self):
        if not self.kb_store: return
        await self.kb_store.add_facts(self._kb)

- path: `packages/ai-parrot/src/parrot/bots/abstract.py`
  lines: 3898-3945
  symbol: `AbstractBot (KB activation block)`
  excerpt: |
    if self.use_kb_selector and self.knowledge_bases:
        for kb in self.knowledge_bases:
            if kb.always_active: activations.append((True, 1.0))
        kbs = await self.kb_selector.select_kbs(question, available_kbs=self.knowledge_bases)
    ...
    if should_activate and confidence > 0.5:
        search_tasks.append(kb.search(query=question, ..., k=5, score_threshold=0.5))

- path: `packages/ai-parrot/src/parrot/bots/stores/local.py`
  lines: 5-125
  symbol: `local KB registration`
  excerpt: |
    the agent's local directory structure (AGENTS_DIR/<agent_name>/kb/).
    ... 5. Add to agent's knowledge_bases list

- path: `packages/ai-parrot/src/parrot/stores/kb/abstract.py`
  lines: 7
  symbol: `AbstractKnowledgeBase`
  excerpt: |
    class AbstractKnowledgeBase(ABC):

## Notes

The KB interface is retrieval-shaped (search per question). An "inline" layer (persona, rules, ADRs always present) has no equivalent here; it lives in prompt layers (FC-001).
