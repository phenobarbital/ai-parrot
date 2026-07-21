---
type: Concept
title: get_dependency_rule_snippets()
id: func:parrot_formdesigner.tools.field_helpers.get_dependency_rule_snippets
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return skeleton dicts for building ``depends_on`` and ``post_depends`` rules.
---

# get_dependency_rule_snippets

```python
def get_dependency_rule_snippets() -> dict[str, Any]
```

Return skeleton dicts for building ``depends_on`` and ``post_depends`` rules.

The returned skeletons are minimal but *valid* — each one can be passed
directly to the corresponding Pydantic model constructor.  They are
intended for use by LLMs and designer UIs that need a quick-start
template when adding conditional logic to form fields.

Returns:
    A dictionary with two top-level keys:

    - ``"depends_on"`` — a skeleton ``DependencyRule`` dict.
    - ``"post_depends"`` — a list containing one skeleton
      ``PostDependency`` dict for each common effect category.

Example::

    snippets = get_dependency_rule_snippets()
    from parrot_formdesigner.core import DependencyRule
    rule = DependencyRule(**snippets["depends_on"])
