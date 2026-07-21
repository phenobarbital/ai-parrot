---
type: Concept
title: lint_knowledge_base()
id: func:parrot.knowledge.pageindex.okf.lint.lint_knowledge_base
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Run lint checks on a knowledge base and return a structured report.
---

# lint_knowledge_base

```python
def lint_knowledge_base(graph: KnowledgeGraph, tree: dict, content_store: NodeContentStore, stale_days: int=90) -> LintReport
```

Run lint checks on a knowledge base and return a structured report.

Executes four checks (orphans, broken links, missing pages, stale claims)
and aggregates the results into a :class:`LintReport`.

Args:
    graph: Pre-built :class:`KnowledgeGraph` for the tree.
    tree: PageIndex tree dict (``{"structure": [...]}``) used to resolve
        node metadata (``timestamp``, ``relates_to``).
    content_store: :class:`NodeContentStore` used for missing-page checks.
    stale_days: Number of days after which a node is considered stale.
        Default is 90.

Returns:
    :class:`LintReport` with all findings categorised.
