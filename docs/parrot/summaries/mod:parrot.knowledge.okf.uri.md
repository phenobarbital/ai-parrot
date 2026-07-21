---
type: Wiki Summary
title: parrot.knowledge.okf.uri
id: mod:parrot.knowledge.okf.uri
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Knowledge URI scheme — unified cross-index addressing (FEAT-239).
relates_to:
- concept: func:parrot.knowledge.okf.uri.build_uri
  rel: defines
- concept: func:parrot.knowledge.okf.uri.parse_uri
  rel: defines
---

# `parrot.knowledge.okf.uri`

Knowledge URI scheme — unified cross-index addressing (FEAT-239).

Provides a shared ``knowledge://`` URI scheme for referencing nodes across
PageIndex and GraphIndex without using ArangoDB-specific keys or PageIndex
tree paths directly.

URI format:
    knowledge://<index_type>/<identifier>

Examples:
    knowledge://graphindex/sym-builder-abc
    knowledge://pageindex/my-tree/concept-id

Legacy ``pageindex://`` URIs are also parsed for backward compatibility.
No migration of existing documents is performed in this FEAT.

Design notes:
- Pure functions, no I/O, no external dependencies.
- ``parse_uri()`` is the inverse of ``build_uri()`` for knowledge:// URIs.
- Legacy pageindex:// URIs keep the full ``tree/node`` as identifier —
  callers are responsible for further parsing.

## Functions

- `def build_uri(index_type: str, identifier: str) -> str` — Build a ``knowledge://`` URI for cross-index addressing.
- `def parse_uri(uri: str) -> tuple[str, str]` — Parse a ``knowledge://`` or legacy ``pageindex://`` URI.
