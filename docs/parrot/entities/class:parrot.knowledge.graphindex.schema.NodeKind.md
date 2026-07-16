---
type: Wiki Entity
title: NodeKind
id: class:parrot.knowledge.graphindex.schema.NodeKind
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Semantic category of a graph node.
---

# NodeKind

Defined in [`parrot.knowledge.graphindex.schema`](../summaries/mod:parrot.knowledge.graphindex.schema.md).

```python
class NodeKind(str, Enum)
```

Semantic category of a graph node.

Attributes:
    DOCUMENT: Top-level document (PDF, DOCX, web page, transcript, etc.)
    SECTION: Hierarchical section within a document (PageIndex path).
    SYMBOL: Code element (module, class, function, variable).
    CONCEPT: Abstract concept extracted from content.
    RATIONALE: Design rationale from docstring or tagged comment.
    SKILL: Skill definition parsed from a SKILL.md file.
    WIKI_PAGE: LLM-generated wiki page (FEAT-260 LLM Wiki).
