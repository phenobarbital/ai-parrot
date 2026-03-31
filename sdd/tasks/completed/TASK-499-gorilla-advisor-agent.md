# TASK-499: Gorilla Sheds Advisor Agent (Multi-Mixin Bot)

**Feature**: advisor-ontologic-rag-agent (FEAT-071)
**Spec**: `sdd/specs/advisor-ontologic-rag-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-497, TASK-498
**Assigned-to**: unassigned

---

## Context

> This is the main deliverable of FEAT-071: a complete, standalone product advisor
> agent that combines all major AI-Parrot capabilities into one example.
>
> The agent sells Gorilla Sheds products using:
> - `ProductAdvisorMixin` for guided product selection
> - `OntologyRAGMixin` for ontology-enriched retrieval (vector-only degradation)
> - `EpisodicMemoryMixin` for cross-session conversational memory
> - `IntentRouterMixin` for pre-RAG query routing
> - `WorkingMemoryToolkit` for intermediate analytics
> - `PageIndexRetriever` for tree-structured navigation of company/product info
>
> The bot must work standalone: `python examples/shoply/sample.py`
>
> Implements **Module 3** from the spec.

---

## Scope

- Implement `examples/shoply/sample.py` with:
  - `GorillaAdvisorBot` class composing all mixins + `BaseBot`
  - `create_advisor_bot()` factory function that:
    1. Loads `ProductCatalog` via `get_catalog()` from TASK-498
    2. Loads `page_index.json` (from TASK-497) into `PageIndexRetriever`
    3. Registers `WorkingMemoryToolkit` with the bot's tool manager
    4. Configures `EpisodicMemoryMixin` (pgvector backend)
    5. Configures `OntologyRAGMixin` with vector store (graceful degradation,
       no ArangoDB required)
    6. Configures `IntentRouterMixin` with capability registry
    7. Configures `ProductAdvisorMixin` with catalog
  - System prompt tailored for Gorilla Sheds sales advisor
  - Interactive chat loop (stdin/stdout) with commands: `quit`, `undo`, `status`
  - Standalone: `python examples/shoply/sample.py`

- The MRO (Method Resolution Order) for the bot class must be:
  ```python
  class GorillaAdvisorBot(
      IntentRouterMixin,
      OntologyRAGMixin,
      EpisodicMemoryMixin,
      ProductAdvisorMixin,
      BaseBot,
  ):
      pass
  ```

**NOT in scope**:
- Scraping (TASK-497)
- Catalog loader (TASK-498)
- Web UI or API server
- ArangoDB graph store setup
- Modifying any core parrot library code

---

## Files to Create / Modify

| File | Action | Description |
|------|--------|-------------|
| `examples/shoply/sample.py` | CREATE | Main advisor agent with chat loop |

---

## Implementation Notes

### Pattern to Follow

```python
#!/usr/bin/env python3
"""
Gorilla Sheds Advisor — Multi-mixin product advisor example.

Demonstrates: ProductAdvisorMixin + OntologyRAGMixin + EpisodicMemoryMixin
+ IntentRouterMixin + WorkingMemoryToolkit + PageIndexRetriever + BaseBot

Usage:
    python examples/shoply/sample.py

Requires:
    - PostgreSQL with pgvector (gorillashed.products populated)
    - Redis for state/session management
    - examples/shoply/data/page_index.json (run scraper.py first)
"""
import asyncio
import json
import logging
from pathlib import Path

from parrot.bots.base import BaseBot
from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.advisors import ProductAdvisorMixin, ProductCatalog
from parrot.memory.episodic.mixin import EpisodicMemoryMixin
from parrot.knowledge.ontology.mixin import OntologyRAGMixin
from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot.pageindex.retriever import PageIndexRetriever

from examples.shoply.config import DATA_DIR
from examples.shoply.load_catalog import get_catalog


class GorillaAdvisorBot(
    IntentRouterMixin,
    OntologyRAGMixin,
    EpisodicMemoryMixin,
    ProductAdvisorMixin,
    BaseBot,
):
    """Multi-mixin advisor bot for Gorilla Sheds."""
    pass


SYSTEM_PROMPT = """You are a friendly and knowledgeable sales advisor for Gorilla Sheds.
...
"""


async def create_advisor_bot() -> GorillaAdvisorBot:
    # 1. Load catalog (already populated in PgVector)
    catalog = await get_catalog()

    # 2. Load PageIndex tree
    tree_data = json.loads((DATA_DIR / "page_index.json").read_text())
    retriever = PageIndexRetriever.from_json(tree_data, ...)

    # 3. Create bot
    bot = GorillaAdvisorBot(
        name="Gorilla Sheds Advisor",
        llm="google:gemini-2.0-flash",
        system_prompt=SYSTEM_PROMPT,
        catalog=catalog,
        auto_register_tools=True,
    )

    # 4. Configure all components
    await bot.configure()
    await bot.configure_advisor(catalog=catalog)
    # Configure episodic memory, ontology RAG, intent router, working memory...

    return bot


async def chat_session(bot: GorillaAdvisorBot) -> None:
    """Interactive chat loop."""
    ...


async def main():
    bot = await create_advisor_bot()
    await chat_session(bot)


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Constraints

- **Mixin order matters**: `IntentRouterMixin` first (intercepts `conversation()`),
  then `OntologyRAGMixin`, `EpisodicMemoryMixin`, `ProductAdvisorMixin`, `BaseBot` last
- `OntologyRAGMixin` must degrade gracefully without ArangoDB — configure with
  vector store only, no graph store required
- `EpisodicMemoryMixin` uses pgvector backend (`episodic_backend="pgvector"`)
- `PageIndexRetriever` tree loaded from `data/page_index.json`
- `WorkingMemoryToolkit` registered via bot's tool manager
- System prompt should reference available capabilities:
  product search, FAQ, installation info, product comparison
- Chat loop mirrors `product_advisor_basebot.py` structure
- All async, no blocking I/O

### References in Codebase

- `examples/advisors/product_advisor_basebot.py` — base pattern to extend
- `parrot/bots/mixins/intent_router.py` — IntentRouterMixin API
- `parrot/knowledge/ontology/mixin.py` — OntologyRAGMixin API
- `parrot/memory/episodic/mixin.py` — EpisodicMemoryMixin config attributes
- `parrot/tools/working_memory/tool.py` — WorkingMemoryToolkit registration
- `parrot/pageindex/retriever.py` — PageIndexRetriever.from_json()

---

## Acceptance Criteria

- [ ] `python examples/shoply/sample.py` starts interactive chat without errors
- [ ] Bot answers product questions using `ProductCatalog` search
- [ ] Bot answers company/FAQ/installation questions using `PageIndexRetriever`
- [ ] Bot uses `OntologyRAGMixin` (vector-only mode) for enriched retrieval
- [ ] Bot records episodes via `EpisodicMemoryMixin`
- [ ] Bot routes queries via `IntentRouterMixin`
- [ ] `WorkingMemoryToolkit` is available as a registered tool
- [ ] Chat commands work: `quit`, `undo`, `status`
- [ ] Graceful degradation: works without ArangoDB
- [ ] No modifications to core parrot library

---

## Test Specification

```python
# tests/examples/test_gorilla_advisor.py
import pytest
from examples.shoply.sample import GorillaAdvisorBot


class TestGorillaAdvisorBot:
    def test_mro_includes_all_mixins(self):
        """Bot class includes all required mixins in MRO."""
        mro_names = [cls.__name__ for cls in GorillaAdvisorBot.__mro__]
        assert "IntentRouterMixin" in mro_names
        assert "OntologyRAGMixin" in mro_names
        assert "EpisodicMemoryMixin" in mro_names
        assert "ProductAdvisorMixin" in mro_names
        assert "BaseBot" in mro_names

    def test_intent_router_is_first_mixin(self):
        """IntentRouterMixin must be first to intercept conversation()."""
        mro = GorillaAdvisorBot.__mro__
        mixin_classes = [c for c in mro if c.__name__.endswith("Mixin")]
        assert mixin_classes[0].__name__ == "IntentRouterMixin"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Read the reference files** listed above to understand each mixin's API
5. **Implement** following the scope and notes above
6. **Test manually**: run `python examples/shoply/sample.py` and verify chat works
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-499-gorilla-advisor-agent.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
