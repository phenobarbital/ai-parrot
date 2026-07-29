---
type: Concept
title: translate()
id: func:parrot.models.bedrock_models.translate
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Translate a public Anthropic model ID to its AWS Bedrock equivalent.
---

# translate

```python
def translate(public_id: str, region_prefix: str | None=None) -> str
```

Translate a public Anthropic model ID to its AWS Bedrock equivalent.

Args:
    public_id: A public model ID (e.g. ``"claude-sonnet-4-6"``) or an
        already-translated Bedrock ID / ARN — in which case it is
        returned verbatim.
    region_prefix: Optional cross-region inference-profile prefix, e.g.
        ``"us"``, ``"eu"``, or ``"apac"``.  When provided, the translated
        base ID is prefixed with ``"<region_prefix>."``.  Ignored when
        *public_id* is already Bedrock-shaped (pass-through branch).

Returns:
    The corresponding Bedrock model ID string.

Examples:
    >>> translate("claude-sonnet-4-6")
    'anthropic.claude-sonnet-4-6-20260115-v1:0'

    >>> translate("claude-sonnet-4-6", region_prefix="us")
    'us.anthropic.claude-sonnet-4-6-20260115-v1:0'

    >>> translate("us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    'us.anthropic.claude-sonnet-4-5-20250929-v1:0'
