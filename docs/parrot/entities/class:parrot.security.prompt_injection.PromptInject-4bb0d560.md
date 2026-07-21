---
type: Wiki Entity
title: PromptInjectionDetector
id: class:parrot.security.prompt_injection.PromptInjectionDetector
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Detects and mitigates prompt injection attempts in user questions.
---

# PromptInjectionDetector

Defined in [`parrot.security.prompt_injection`](../summaries/mod:parrot.security.prompt_injection.md).

```python
class PromptInjectionDetector
```

Detects and mitigates prompt injection attempts in user questions.

## Methods

- `def add_framework_allowlist(self, pattern: re.Pattern | str) -> None` — Register an additional framework-added pattern to pre-strip.
- `def strip_framework_patterns(self, text: str) -> str` — Remove framework-injected patterns before scanning.
- `def detect_threats(self, text: str) -> List[Dict[str, Any]]` — Scan text for prompt injection patterns.
- `def sanitize(self, text: str, strict: bool=True, replacement: str='[FILTERED_CONTENT]') -> Tuple[str, List[Dict[str, Any]]]` — Sanitize text by replacing detected patterns.
