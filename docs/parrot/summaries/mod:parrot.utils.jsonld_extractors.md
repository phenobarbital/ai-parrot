---
type: Wiki Summary
title: parrot.utils.jsonld_extractors
id: mod:parrot.utils.jsonld_extractors
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: JSON-LD extractor functions and data model for WebScrapingLoader.
relates_to:
- concept: class:parrot.utils.jsonld_extractors.JsonLdItem
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.article_extractor
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.breadcrumb_extractor
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.event_extractor
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.faq_extractor
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.howto_extractor
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.organization_extractor
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.person_extractor
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.place_extractor
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.product_extractor
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.question_extractor
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.recipe_extractor
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.strip_html_text
  rel: defines
- concept: func:parrot.utils.jsonld_extractors.walk_jsonld
  rel: defines
---

# `parrot.utils.jsonld_extractors`

JSON-LD extractor functions and data model for WebScrapingLoader.

This module provides:
- ``JsonLdItem`` — dataclass representing a single extracted JSON-LD item
- ``strip_html_text`` — utility to decode HTML entities and strip tags
- One extractor function per supported schema.org ``@type``
- ``EXTRACTOR_REGISTRY`` — dict mapping ``@type`` strings to extractor callables

Extractor functions are pure data transformations: they receive a parsed
JSON-LD node (a ``dict``) and return ``List[JsonLdItem]``.  They have no
dependency on WebScrapingLoader or BeautifulSoup beyond tag-stripping.

Dispatch into the loader's pipeline happens in ``webscraping.py`` via
``_extract_jsonld`` and ``_walk_jsonld_node``.

## Classes

- **`JsonLdItem`** — A single structured item extracted from a JSON-LD block.

## Functions

- `def strip_html_text(text: Any) -> str` — Render arbitrary text as clean plain text.
- `def faq_extractor(node: Dict[str, Any]) -> List[JsonLdItem]` — Extract FAQ Q&A pairs from a FAQPage JSON-LD node.
- `def product_extractor(node: Dict[str, Any]) -> List[JsonLdItem]` — Extract Product data from a JSON-LD node.
- `def event_extractor(node: Dict[str, Any]) -> List[JsonLdItem]` — Extract Event data from a JSON-LD node.
- `def person_extractor(node: Dict[str, Any]) -> List[JsonLdItem]` — Extract Person data from a JSON-LD node.
- `def place_extractor(node: Dict[str, Any]) -> List[JsonLdItem]` — Extract Place / LocalBusiness data from a JSON-LD node.
- `def recipe_extractor(node: Dict[str, Any]) -> List[JsonLdItem]` — Extract Recipe data from a JSON-LD node.
- `def article_extractor(node: Dict[str, Any]) -> List[JsonLdItem]` — Extract Article / NewsArticle / BlogPosting data from a JSON-LD node.
- `def organization_extractor(node: Dict[str, Any]) -> List[JsonLdItem]` — Extract Organization data from a JSON-LD node.
- `def howto_extractor(node: Dict[str, Any]) -> List[JsonLdItem]` — Extract HowTo data from a JSON-LD node.
- `def breadcrumb_extractor(node: Dict[str, Any]) -> List[JsonLdItem]` — Extract BreadcrumbList data from a JSON-LD node.
- `def question_extractor(node: Dict[str, Any]) -> List[JsonLdItem]` — Extract a bare top-level ``Question`` node.
- `def walk_jsonld(data: Any, items: List[JsonLdItem], allowed_types: Optional[set]=None) -> None` — Recursively walk a JSON-LD structure dispatching typed nodes to extractors.
