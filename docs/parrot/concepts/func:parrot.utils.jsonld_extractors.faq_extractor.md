---
type: Concept
title: faq_extractor()
id: func:parrot.utils.jsonld_extractors.faq_extractor
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract FAQ Q&A pairs from a FAQPage JSON-LD node.
---

# faq_extractor

```python
def faq_extractor(node: Dict[str, Any]) -> List[JsonLdItem]
```

Extract FAQ Q&A pairs from a FAQPage JSON-LD node.

Yields one ``JsonLdItem`` per Question/Answer pair with:
- ``content_kind="faq"``
- ``source_type="faq-jsonld"``
- ``page_content="Q: <question>\n\nA: <answer>"``

Backward-compatible with the original ``_iter_faqpage_pairs`` /
``_docs_from_faqpage`` pipeline.

Args:
    node: Parsed JSON-LD dict with ``@type="FAQPage"``.

Returns:
    List of ``JsonLdItem`` instances (empty if no valid Q&A pairs found).
