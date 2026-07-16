---
type: Wiki Entity
title: TextMatcher
id: class:parrot.models.compliance.TextMatcher
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: N-gram + fuzzy text matcher for planogram text compliance.
---

# TextMatcher

Defined in [`parrot.models.compliance`](../summaries/mod:parrot.models.compliance.md).

```python
class TextMatcher
```

N-gram + fuzzy text matcher for planogram text compliance.

Public API:
    TextMatcher.check_text_match(
        required_text: str,
        visual_features: List[str],
        match_type: str = "contains",      # "contains" | "regex" | "ngram" | "auto"
        case_sensitive: bool = False,
        confidence_threshold: float = 0.6, # used for "ngram"/"auto"
        ngram_range: Tuple[int, int] = (1, 3),
        min_token_len: int = 2,
    ) -> TextComplianceResult

## Methods

- `def check_text_match(cls, required_text: str, visual_features: List[str], match_type: str='contains', case_sensitive: bool=False, confidence_threshold: float=0.6, ngram_range: Tuple[int, int]=(1, 3), min_token_len: int=2)`
