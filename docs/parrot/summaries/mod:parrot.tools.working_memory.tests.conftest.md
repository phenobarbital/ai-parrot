---
type: Wiki Summary
title: parrot.tools.working_memory.tests.conftest
id: mod:parrot.tools.working_memory.tests.conftest
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Shared fixtures for WorkingMemoryToolkit tests.
relates_to:
- concept: func:parrot.tools.working_memory.tests.conftest.answer_memory
  rel: defines
- concept: func:parrot.tools.working_memory.tests.conftest.census_df
  rel: defines
- concept: func:parrot.tools.working_memory.tests.conftest.sales_df
  rel: defines
- concept: func:parrot.tools.working_memory.tests.conftest.sample_dict
  rel: defines
- concept: func:parrot.tools.working_memory.tests.conftest.sample_message
  rel: defines
- concept: func:parrot.tools.working_memory.tests.conftest.sample_text
  rel: defines
- concept: func:parrot.tools.working_memory.tests.conftest.toolkit
  rel: defines
- concept: func:parrot.tools.working_memory.tests.conftest.toolkit_with_memory
  rel: defines
- concept: mod:parrot.memory
  rel: references
- concept: mod:parrot.tools.working_memory
  rel: references
---

# `parrot.tools.working_memory.tests.conftest`

Shared fixtures for WorkingMemoryToolkit tests.

## Functions

- `def census_df() -> pd.DataFrame` — Generate a synthetic US Census-style DataFrame.
- `def sales_df() -> pd.DataFrame` — Generate a synthetic sales DataFrame.
- `def toolkit(census_df: pd.DataFrame, sales_df: pd.DataFrame) -> WorkingMemoryToolkit` — Create a WorkingMemoryToolkit with pre-loaded census and sales DataFrames.
- `def answer_memory() -> AnswerMemory` — Create an in-memory AnswerMemory for testing.
- `def toolkit_with_memory(answer_memory: AnswerMemory) -> WorkingMemoryToolkit` — Create a WorkingMemoryToolkit wired to an AnswerMemory instance.
- `def sample_text() -> str` — A plain-text research finding.
- `def sample_dict() -> dict` — A simple nested dict fixture.
- `def sample_message()` — AIMessage-like object with .content and .role attributes.
