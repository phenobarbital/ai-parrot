---
type: Wiki Summary
title: parrot.knowledge.graphindex.extractors.code
id: mod:parrot.knowledge.graphindex.extractors.code
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Code extractor — tree-sitter Python parsing for GraphIndex.
relates_to:
- concept: class:parrot.knowledge.graphindex.extractors.code.CodeExtractor
  rel: defines
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
---

# `parrot.knowledge.graphindex.extractors.code`

Code extractor — tree-sitter Python parsing for GraphIndex.

Parses Python source files and emits ``UniversalNode`` / ``UniversalEdge``
instances representing the structural and semantic content of a codebase.
Rationale nodes are extracted from docstrings and tagged comments.

## Classes

- **`CodeExtractor`** — Extract code structure from Python source files using tree-sitter.
