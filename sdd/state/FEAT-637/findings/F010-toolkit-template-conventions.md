---
id: F010
query_id: Q010
type: grep
intent: Find other toolkits with template/placeholder support to mirror the convention.
executed_at: 2026-10-07T22:57:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# F010 — Existing toolkit convention: a `templates_dir: Optional[Path]` constructor kwarg

## Summary

Three document toolkits in ai-parrot-tools take a `templates_dir: Optional[Path] = None` constructor kwarg and build a sync `Environment(loader=FileSystemLoader(str(self.templates_dir)))` when set (msword.py L91-110, powerpoint.py L142-169, pdfprint.py L107-133; pdfprint falls back to `static_dir/templates` and writes a default template). The core infographic_toolkit instead takes `template_dirs` + in-memory `templates` and uses the shared TemplateEngine. So two conventions coexist; `templates_dir` (singular Path kwarg) is the ai-parrot-tools house style, TemplateEngine is the core one.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/msword.py`
  lines: 91-110
  symbol: `MSWordTool.__init__`
  excerpt: |
    templates_dir: Optional[Path] = None,
    ...
    if self.templates_dir:
        self.html_env = Environment(loader=FileSystemLoader(str(self.templates_dir)),
- path: `packages/ai-parrot-tools/src/parrot_tools/powerpoint.py`
  lines: 142-169
  symbol: `PowerPointTool.__init__`
  excerpt: |
    templates_dir: Optional[Path] = None,
    pptx_template_path: Optional[Path] = None,
- path: `packages/ai-parrot-tools/src/parrot_tools/pdfprint.py`
  lines: 107-133
  symbol: `PDFPrintTool.__init__`
  excerpt: |
    if templates_dir is None:
        templates_dir = self.static_dir / "templates" if self.static_dir else Path("templates")
        templates_dir.mkdir(parents=True, exist_ok=True)
        self._create_default_template(templates_dir)
- path: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
  lines: 307-321
  excerpt: |
    self._template_engine: Optional[TemplateEngine] = None
    if template_dirs is not None or templates:
        self._template_engine = TemplateEngine(template_dirs=template_dirs, config=JinjaConfig(autoescape=True))
        if templates: self._template_engine.add_templates(templates)
