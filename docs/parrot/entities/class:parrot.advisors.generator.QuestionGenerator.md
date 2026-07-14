---
type: Wiki Entity
title: QuestionGenerator
id: class:parrot.advisors.generator.QuestionGenerator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generates discriminant questions for a product catalog using LLM analysis.
---

# QuestionGenerator

Defined in [`parrot.advisors.generator`](../summaries/mod:parrot.advisors.generator.md).

```python
class QuestionGenerator
```

Generates discriminant questions for a product catalog using LLM analysis.

Usage:
    generator = QuestionGenerator(llm=my_llm_client)
    question_set = await generator.generate(products, catalog_id="sheds_2024")
    
    # Questions are cached - subsequent calls return cached version
    question_set = await generator.generate(products, catalog_id="sheds_2024")

## Methods

- `async def generate(self, products: List[ProductSpec], catalog_id: str, force_regenerate: bool=False, additional_context: str='') -> QuestionSet` — Generate discriminant questions for a product catalog.
