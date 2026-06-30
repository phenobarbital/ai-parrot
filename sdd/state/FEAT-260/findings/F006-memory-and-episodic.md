---
id: F006
query_id: Q006
type: read
intent: Survey memory system for wiki state tracking
executed_at: 2026-06-26T00:00:00Z
duration_ms: 1200
parent_id: null
depth: 0
---

# F006 — Memory: Episodic + Unified Manager + Working Memory

## Summary

The memory subsystem provides: (1) ConversationMemory (Redis/InMemory/File backends) for chat history, (2) EpisodicMemoryStore for recording and recalling agent episodes with semantic search, (3) UnifiedMemoryManager that orchestrates parallel retrieval from all sources, (4) WorkingMemoryToolkit for agent-managed scratch state. The episodic memory records situations, actions, outcomes, reflections, and lessons — relevant for tracking wiki operations (what was ingested, what was updated, what failed).

## Citations

- path: `packages/ai-parrot/src/parrot/memory/episodic/store.py`
  symbol: `EpisodicMemoryStore`

- path: `packages/ai-parrot/src/parrot/memory/unified/manager.py`
  symbol: `UnifiedMemoryManager`

- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  symbol: `WorkingMemoryToolkit`

## Notes

The wiki log (log.md) could be backed by episodic memory for semantic search over past operations. The UnifiedMemoryManager could integrate wiki page context alongside conversation history and episodic memories for richer agent responses.
