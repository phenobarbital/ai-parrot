---
type: Wiki Entity
title: QuestionSet
id: class:parrot.advisors.questions.QuestionSet
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Complete set of discriminant questions for a catalog.
---

# QuestionSet

Defined in [`parrot.advisors.questions`](../summaries/mod:parrot.advisors.questions.md).

```python
class QuestionSet(BaseModel)
```

Complete set of discriminant questions for a catalog.

Generated once per catalog and cached.

## Methods

- `def get_question(self, question_id: str) -> Optional[DiscriminantQuestion]` — Get a question by ID.
- `def get_next_question(self, asked_ids: List[str], current_criteria: Dict[str, Any], remaining_products: int) -> Optional[DiscriminantQuestion]` — Get the next best question to ask.
- `def get_questions_by_category(self, category: QuestionCategory) -> List[DiscriminantQuestion]` — Get all questions of a specific category.
- `def question_count(self) -> int`
