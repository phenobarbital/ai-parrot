---
type: Wiki Entity
title: ProductAdvisorMixin
id: class:parrot.advisors.mixin.ProductAdvisorMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin that adds product selection wizard capabilities to any Bot/Agent.
---

# ProductAdvisorMixin

Defined in [`parrot.advisors.mixin`](../summaries/mod:parrot.advisors.mixin.md).

```python
class ProductAdvisorMixin
```

Mixin that adds product selection wizard capabilities to any Bot/Agent.

Features:
- Guided product selection through discriminant questions
- State management with Redis
- Undo/redo support via Memento pattern
- Works with VoiceBot and text chatbots

Usage:
    class MyProductBot(ProductAdvisorMixin, BasicAgent):
        pass

    bot = MyProductBot(
        name="Product Advisor",
        llm="google:gemini-3.1-flash-lite-preview",
        catalog=my_catalog,  # ProductCatalog instance
    )
    await bot.configure()

Or with VoiceBot:
    class VoiceAdvisor(ProductAdvisorMixin, VoiceBot):
        pass

## Methods

- `async def configure_advisor(self, catalog: Optional[ProductCatalog]=None, question_set: Optional[QuestionSet]=None) -> None` — Configure the product advisor components.
- `async def start_product_selection(self, user_id: str, session_id: str, category: Optional[str]=None) -> str` — Start a new product selection session.
- `async def undo_last_answer(self, user_id: str, session_id: str) -> str` — Undo the last answer and restore previous state.
- `def product_catalog(self) -> Optional[ProductCatalog]` — Access the product catalog.
- `def selection_manager(self) -> Optional[SelectionStateManager]` — Access the selection state manager.
