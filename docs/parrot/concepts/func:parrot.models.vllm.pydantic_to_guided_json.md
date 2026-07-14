---
type: Concept
title: pydantic_to_guided_json()
id: func:parrot.models.vllm.pydantic_to_guided_json
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Convert a Pydantic model class to vLLM guided_json schema.
---

# pydantic_to_guided_json

```python
def pydantic_to_guided_json(model: Type[BaseModel]) -> Dict[str, Any]
```

Convert a Pydantic model class to vLLM guided_json schema.

This helper enables structured output by converting Pydantic models
to JSON schemas that vLLM can use for constrained generation.

Args:
    model: A Pydantic BaseModel class (not an instance)

Returns:
    JSON schema dict compatible with vLLM's guided_json parameter

Example:
    >>> from pydantic import BaseModel
    >>> class Person(BaseModel):
    ...     name: str
    ...     age: int
    >>> schema = pydantic_to_guided_json(Person)
    >>> # Use with vLLMClient:
    >>> # await client.ask("Extract person info", guided_json=schema)
