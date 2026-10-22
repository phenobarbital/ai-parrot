---
id: F009
query_id: Q009
type: grep
intent: Check whether jinja2 is a declared dependency of ai-parrot / ai-parrot-tools.
executed_at: 2026-10-07T22:57:00Z
duration_ms: 300
parent_id: null
depth: 0
---

# F009 — jinja2>=3.1 is already a hard dependency of both core and ai-parrot-tools

## Summary

`jinja2>=3.1` is declared in `packages/ai-parrot/pyproject.toml` (L466) and `packages/ai-parrot-tools/pyproject.toml` (L52). No new dependency is needed for this feature; the optional extension packages used by JinjaConfig (jinja2_time, jinja2_iso8601, jinja2_humanize_extension) are already resolved wherever TemplateEngine works today.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 466
  excerpt: |
    "jinja2>=3.1",
- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 52
  excerpt: |
    "jinja2>=3.1",
- path: `packages/parrot-formdesigner/pyproject.toml`
  lines: 41
  excerpt: |
    "jinja2>=3.1",
