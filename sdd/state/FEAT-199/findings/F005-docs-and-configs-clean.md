---
id: F005
query_id: Q005
type: grep
intent: Audit docs/examples/configs for residual parrot.forms references
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F005 — Only one non-code reference: package-data entry in pyproject.toml

## Summary

`grep -rn "parrot\.forms" --include="*.md" --include="*.txt" --include="*.toml"
docs/ examples/ packages/ai-parrot/pyproject.toml pyproject.toml` returns a
single match: `packages/ai-parrot/pyproject.toml:542` which registers the
Jinja2 templates as package-data for `parrot.forms.renderers`. No README,
docs, or example references `parrot.forms`.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 540-545
  excerpt: |
    "parrot.openapi" = ["*.yaml"]
    "parrot.knowledge.ontology.defaults" = ["*.yaml", "domains/*.yaml"]
    "parrot.forms.renderers" = ["templates/*.j2"]
    "parrot.flows.dev_loop" = ["_subagent_data/*.md"]
    "parrot.storage.security_reports" = ["*.sql"]

## Notes

Cleanup is simple — drop that single line from setuptools `package-data`
when the directory is removed.
