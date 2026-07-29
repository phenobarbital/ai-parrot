---
type: Wiki Entity
title: TokenTextSplitter
id: class:parrot.loaders.splitters.token.TokenTextSplitter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Text splitter that splits based on token count using various tokenizers.
relates_to:
- concept: class:parrot.loaders.splitters.base.BaseTextSplitter
  rel: extends
---

# TokenTextSplitter

Defined in [`parrot.loaders.splitters.token`](../summaries/mod:parrot.loaders.splitters.token.md).

```python
class TokenTextSplitter(BaseTextSplitter)
```

Text splitter that splits based on token count using various tokenizers.

Supports:
- OpenAI tiktoken tokenizers (gpt-3.5-turbo, gpt-4, etc.)
- Hugging Face transformers tokenizers
- Custom tokenization functions

## Methods

- `def split_text(self, text: str) -> List[str]` — Split text based on token count
