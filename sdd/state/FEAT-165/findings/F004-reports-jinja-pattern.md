---
finding_id: F004
query_id: Q004,Q007,Q017
type: pattern
confidence: high
citations:
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py:11
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py:26-33
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py:63-98
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/templates/scan_report.html
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/templates/comparison_report.html
---

# Report-generator pattern is Jinja2 + xhtml2pdf, easy to extend

`ReportGenerator` (`reports.py:19`) holds a `jinja2.Environment` rooted at
`cloudsploit/templates/` (`reports.py:28-32`). Each public render method
loads a template by name, renders it with a Pydantic model dump, optionally
writes to disk, and (for PDF) pipes through `xhtml2pdf.pisa.CreatePDF`.

Existing templates: `scan_report.html`, `comparison_report.html`. Both are
print-friendly (target PDF), using inline `<style>` blocks with Helvetica
fonts and simple bar-chart placeholders.

**Implication:** Adding the user's interactive HTML report is a near-mechanical
template addition:
- New template: `cloudsploit/templates/ecr_scan_report.html` (transliterate
  the JS generator's HTML/CSS/JS, replacing template-literal interpolation
  with Jinja2 `{{ ... }}`).
- New method `async def generate_ecr_html(...)` on `ReportGenerator`, mirroring
  `generate_html` but typed on `EcrCollectionResult`.
- `xhtml2pdf` is unlikely to render the user's report well (it relies on
  `display:grid`, gradients, client-side JS) — so the ECR HTML report should
  be **browser-targeted, not PDF-targeted**. We can either skip PDF for ECR
  or generate a simpler print-oriented HTML for PDF runs.

Severity-color and badge logic from `generate_ecr_report.js` is data and can
be embedded as Jinja2 macros or kept inline in the template.
