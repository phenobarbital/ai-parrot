---
id: FW-015
query_id: Q015
type: wiki_page
intent: "Long-term memory spec: org/team/project memory scopes"
executed_at: 2026-10-30T16:47:12Z
duration_ms: 400
parent_id: null
depth: 0
---

# FW-015 — No org/team/project rules-file layout exists; the memory layer is `UnifiedMemoryManager` + `ContextAssembler` (priority-weighted token budget) over episodic / skills / conversation, namespaced by `MemoryNamespace(org_id, agent_id, user_id)`

## Summary

FEAT-055 (approved) specifies `parrot/memory/unified/` — `UnifiedMemoryManager` (`get_context_for_query`, `record_interaction`), `ContextAssembler` with weights failures 30% / skills 30% / conversation 40% over `max_context_tokens` (chars/4 approximation), `LongTermMemoryMixin` (opt-in flag + `_configure_long_term_memory()`), and reuse of `MemoryNamespace(org_id, agent_id, user_id)` from `parrot/memory/episodic/models.py`. Open question in the spec: cross-agent skill sharing "via `org_id/shared` scope". Nothing in this spec (or the wiki hits) describes `.parrot/memory/org.md|team.md|project.md` files or an additive ALWAYS/NEVER rules chain.

## Citations

- path: `sdd/specs/long-term-memory.spec.md`
  symbol: `UnifiedMemoryManager / ContextAssembler / LongTermMemoryMixin`
  wiki_page_id: file:sdd/specs/long-term-memory.spec.md
  score: 0.63
  excerpt: |
    class MemoryConfig(BaseModel):
        max_context_tokens: int = 2000
        episodic_weight: float = 0.3; skill_weight: float = 0.3; conversation_weight: float = 0.4
    class ContextAssembler: def assemble(self, episodic_warnings, relevant_skills, conversation) -> MemoryContext
    # fixture: MemoryNamespace(org_id="test", agent_id="test-agent", user_id="user1")

- path: `packages/ai-parrot/src/parrot/memory/unified/manager.py`
  symbol: `UnifiedMemoryManager.__init__`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/memory/unified/manager.py#UnifiedMemoryManager.__init__
  score: 1.00
  excerpt: |
    (module exists — implemented per FEAT-055)

## Notes

Evidence of absence: the governance-rules chain (org → team → project → expert → stage) is NEW surface. The nearest primitives are `ContextAssembler`'s weighted budget (a precedent for per-layer quotas, but it truncates rather than "never trims rules") and `MemoryNamespace.org_id`. Per-turn compaction (FEAT-525 `ContextBudget`) is the other budget precedent — see codebase lane Q046.
