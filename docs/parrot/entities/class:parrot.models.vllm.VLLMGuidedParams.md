---
type: Wiki Entity
title: VLLMGuidedParams
id: class:parrot.models.vllm.VLLMGuidedParams
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Guided decoding parameters for constrained generation.
---

# VLLMGuidedParams

Defined in [`parrot.models.vllm`](../summaries/mod:parrot.models.vllm.md).

```python
class VLLMGuidedParams(BaseModel)
```

Guided decoding parameters for constrained generation.

vLLM supports constraining output to specific patterns using
JSON schemas, regular expressions, or predefined choices.
Only one constraint type can be active at a time.

Attributes:
    guided_json: JSON schema for constrained output
    guided_regex: Regular expression pattern to match
    guided_choice: List of valid output choices
    guided_grammar: BNF grammar for constrained output

## Methods

- `def check_mutually_exclusive(self) -> 'VLLMGuidedParams'` — Ensure only one guided constraint is specified.
- `def to_extra_body(self) -> Dict[str, Any]` — Convert to vLLM extra_body format.
