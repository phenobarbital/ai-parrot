---
type: Concept
title: build_contextual_text()
id: func:parrot.stores.utils.contextual.build_contextual_text
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Build the text that will be embedded plus the header used.
---

# build_contextual_text

```python
def build_contextual_text(document: Document, template: ContextualTemplate=DEFAULT_TEMPLATE, max_header_tokens: int=DEFAULT_MAX_HEADER_TOKENS) -> tuple[str, str]
```

Build the text that will be embedded plus the header used.

Reads ``document.metadata['document_meta']`` (canonical, from
metadata-standardisation).  Renders the template, dropping empty fields
and collapsing the resulting separators.  Caps the header at
``max_header_tokens`` (whitespace-tokenised approximation — no real
tokeniser dependency; the cap is a safety belt, not an exact limit).

This function is a pure function: no I/O, no logging, no side-effects.

Args:
    document: The ``Document`` whose ``page_content`` will be embedded.
    template: A format-map style string (placeholders: title, section,
        category, page, language, source, content) *or* a callable that
        receives the raw ``document_meta`` dict and returns the **header
        string**.  ``document.page_content`` is always appended
        automatically after a ``"\n\n"`` separator, so the callable
        must NOT include the chunk text itself.  If the callable
        accidentally returns ``"header\n\ncontent"`` form, the content
        portion is discarded and the document's original
        ``page_content`` is used instead.
    max_header_tokens: Approximate upper bound on header length measured
        in whitespace-tokenised words.  Prevents header blow-up for
        documents with extremely long titles.

Returns:
    A ``(text_to_embed, header)`` tuple where:

    - ``text_to_embed`` is the string to pass to the embedding model.
    - ``header`` is the rendered + cleaned header that was prepended
      (empty string if no usable metadata was found).

Note:
    ``document.page_content`` is **never mutated**.  Setting
    ``metadata['contextual_header']`` is the caller's responsibility
    (done by ``AbstractStore._apply_contextual_augmentation``).
