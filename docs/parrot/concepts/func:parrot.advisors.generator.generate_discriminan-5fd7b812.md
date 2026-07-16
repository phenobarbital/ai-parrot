---
type: Concept
title: generate_discriminant_questions()
id: func:parrot.advisors.generator.generate_discriminant_questions
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Convenience function to generate questions for a catalog.
---

# generate_discriminant_questions

```python
async def generate_discriminant_questions(products: List[ProductSpec], llm: AbstractClient, catalog_id: str='default', **kwargs) -> QuestionSet
```

Convenience function to generate questions for a catalog.

Usage:
    questions = await generate_discriminant_questions(
        products=my_products,
        llm=my_llm_client,
        catalog_id="sheds_2024"
    )
