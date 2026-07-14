---
type: Concept
title: validate_enhanced_html()
id: func:parrot.tools._enhance_html_check.validate_enhanced_html
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raise ENHANCE_OUTPUT_INVALID if the HTML references disallowed resources.
---

# validate_enhanced_html

```python
def validate_enhanced_html(html: str, allowed_bundles: Iterable[Any], error_cls: Optional[Callable[[str, Dict[str, Any]], Exception]]=None) -> None
```

Raise ENHANCE_OUTPUT_INVALID if the HTML references disallowed resources.

``allowed_bundles`` must be an iterable of objects with at least::

    .scope: str            — "cdn" or "inline"
    .url: Optional[str]    — CDN URL (required when scope='cdn')
    .sri_hash: Optional[str] — SRI hash (required when scope='cdn')

Args:
    html: Full HTML document returned by the LLM enhance step.
    allowed_bundles: Iterable of ``JSBundle`` instances from the template.
    error_cls: Factory ``(code, detail) -> Exception`` used to build the
        raised error. Defaults to ``InfographicValidationError`` for
        backward compatibility; the interactive pipeline passes
        ``InteractiveValidationError``.

Raises:
    Exception: Built by ``error_cls`` with code ``ENHANCE_OUTPUT_INVALID``
        on any policy violation.
