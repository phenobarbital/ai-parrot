---
id: F003
query_id: Q003
type: wiki_query
intent: Orient on existing Jinja2 / templating usage in the framework.
executed_at: 2026-10-07T22:55:00Z
duration_ms: 1500
parent_id: null
depth: 0
---

# F003 — Jinja2 landscape in the framework

## Summary

The wiki surfaces a first-class core module `parrot/template/engine.py` (TemplateEngine), plus several tool-level ad-hoc Jinja environments (PDFPrintTool, MSWordTool, PowerPointTool, security ReportGenerator) and the formdesigner HTML5Renderer. A prior research finding (FEAT-430 F004) documents async-notify Jinja support being file-based only. So templating is an established, multi-site pattern — but no single shared "toolkit template" helper.

## Citations

- path: `packages/ai-parrot/src/parrot/template/engine.py`
  excerpt: |
    wiki: file:packages/ai-parrot/src/parrot/template/engine.py (score=0.40, ~2374tok)
- path: `packages/ai-parrot-tools/src/parrot_tools/pdfprint.py`
  symbol: `PDFPrintTool`
- path: `packages/ai-parrot-tools/src/parrot_tools/msword.py`
  symbol: `MSWordTool.__init__`
- path: `packages/ai-parrot-tools/src/parrot_tools/powerpoint.py`
  symbol: `PowerPointTool.__init__`
- path: `packages/ai-parrot-tools/src/parrot_tools/security/reports/generator.py`
  symbol: `ReportGenerator`
  excerpt: |
    Multi-format report generator with Jinja2 templates.
- path: `packages/ai-parrot/tests/outputs/formats/test_jinja2.py`
  symbol: `jinja2_env`
