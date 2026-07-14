---
type: Wiki Entity
title: GetNextQuestionTool
id: class:parrot.advisors.tools.question.GetNextQuestionTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Returns the next optimal question to ask the user.
relates_to:
- concept: class:parrot.advisors.tools.base.BaseAdvisorTool
  rel: extends
---

# GetNextQuestionTool

Defined in [`parrot.advisors.tools.question`](../summaries/mod:parrot.advisors.tools.question.md).

```python
class GetNextQuestionTool(BaseAdvisorTool)
```

Returns the next optimal question to ask the user.

This tool considers:
- Questions already asked
- Criteria already collected
- Number of remaining products
- Question dependencies and conditions

Use this when you need to continue the selection process
after processing the user's previous answer.
