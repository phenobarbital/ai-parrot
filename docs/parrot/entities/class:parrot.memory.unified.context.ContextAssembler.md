---
type: Wiki Entity
title: ContextAssembler
id: class:parrot.memory.unified.context.ContextAssembler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Assembles context from multiple sources within a token budget.
---

# ContextAssembler

Defined in [`parrot.memory.unified.context`](../summaries/mod:parrot.memory.unified.context.md).

```python
class ContextAssembler
```

Assembles context from multiple sources within a token budget.

Priority order (highest first):
1. Episodic failure warnings — critical for avoiding past mistakes
2. Relevant skills — applicable knowledge
3. Conversation history — recent turns (truncated from oldest)

Each section gets a weight-based allocation from the total budget.
Unused budget from empty sections rolls forward to the next priority.

Args:
    config: Optional MemoryConfig; defaults to MemoryConfig() if omitted.

Example:
    assembler = ContextAssembler(MemoryConfig(max_context_tokens=2000))
    ctx = assembler.assemble(
        episodic_warnings="Don't call X without auth",
        relevant_skills="Use get_schema tool",
        conversation="User: hello\nAssistant: hi",
    )
    print(ctx.tokens_used)

## Methods

- `def assemble(self, episodic_warnings: str='', relevant_skills: str='', conversation: str='') -> MemoryContext` — Assemble context respecting token budget.
