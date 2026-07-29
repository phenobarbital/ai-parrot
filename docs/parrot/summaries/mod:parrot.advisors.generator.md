---
type: Wiki Summary
title: parrot.advisors.generator
id: mod:parrot.advisors.generator
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: LLM-Powered Question Generator for Product Selection.
relates_to:
- concept: class:parrot.advisors.generator.QuestionGenerator
  rel: defines
- concept: func:parrot.advisors.generator.generate_discriminant_questions
  rel: defines
- concept: mod:parrot.advisors.models
  rel: references
- concept: mod:parrot.advisors.questions
  rel: references
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.stores.abstract
  rel: references
---

# `parrot.advisors.generator`

LLM-Powered Question Generator for Product Selection.

Analyzes a product catalog and generates optimal discriminant questions.

## Classes

- **`QuestionGenerator`** — Generates discriminant questions for a product catalog using LLM analysis.

## Functions

- `async def generate_discriminant_questions(products: List[ProductSpec], llm: AbstractClient, catalog_id: str='default', **kwargs) -> QuestionSet` — Convenience function to generate questions for a catalog.
