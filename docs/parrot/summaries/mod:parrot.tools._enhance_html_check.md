---
type: Wiki Summary
title: parrot.tools._enhance_html_check
id: mod:parrot.tools._enhance_html_check
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: HTML validator for LLM-enhanced output (FEAT-197, TASK-1325).
relates_to:
- concept: func:parrot.tools._enhance_html_check.validate_enhanced_html
  rel: defines
- concept: mod:parrot.tools.infographic_toolkit
  rel: references
---

# `parrot.tools._enhance_html_check`

HTML validator for LLM-enhanced output (FEAT-197, TASK-1325).

Shared by the infographic enhance pass and the interactive-artifact render
pipeline. Uses stdlib ``html.parser`` — no new dependencies.

Checks:
- Every ``<script src="...">`` URL must be in the ``allowed_bundles`` whitelist
  (matching both URL and SRI hash).
- Every ``<link rel="stylesheet" href="...">`` URL must likewise be whitelisted.
- Inline ``<script>`` blocks (no ``src``) are allowed.
- Inline ``<style>`` blocks are allowed.
- Inline event handlers (``on*`` attributes), ``javascript:`` URIs, ``<base href>``,
  and ``<meta http-equiv="refresh">`` are always rejected regardless of whitelist.

Raises ``code='ENHANCE_OUTPUT_INVALID'`` on any policy violation. The concrete
exception type is pluggable via ``error_cls`` so callers can keep their own
structured error class (``InfographicValidationError`` by default, or e.g.
``InteractiveValidationError``).

## Functions

- `def validate_enhanced_html(html: str, allowed_bundles: Iterable[Any], error_cls: Optional[Callable[[str, Dict[str, Any]], Exception]]=None) -> None` — Raise ENHANCE_OUTPUT_INVALID if the HTML references disallowed resources.
