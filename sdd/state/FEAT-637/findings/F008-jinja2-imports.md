---
id: F008
query_id: Q008
type: grep
intent: Find concrete Jinja2 imports across packages — which dists already depend on jinja2 and how they build environments.
executed_at: 2026-10-07T22:57:00Z
duration_ms: 800
parent_id: null
depth: 0
---

# F008 — Jinja2 is imported at 11 source sites; core has a shared async TemplateEngine

## Summary

11 non-test source sites import jinja2 (excluding build/ copies). The shared abstraction is `parrot.template.engine.TemplateEngine` (core) — async-only, multi-dir FileSystemLoader + in-memory DictLoader, `StrictUndefined` by default, `select_autoescape` on .html/.xml/.j2/.jinja/.jinja2 names, extensions incl. jinja2_time/iso8601/humanize. Consumers: thales rendering, outputs/formatter, infographic_toolkit (forces `JinjaConfig(autoescape=True)`), template_report. Tool-level sites (pdfprint/msword/powerpoint/security reports/cloudsploit) build their own sync `Environment(FileSystemLoader(...))`. CommCenter render uses `DebugUndefined` (lenient: leaves missing placeholders visible). formdesigner uses `jinja2.sandbox.SandboxedEnvironment` for untrusted REST resolver templates. ontology tool_dispatcher uses `StrictUndefined`.

## Citations

- path: `packages/ai-parrot/src/parrot/template/engine.py`
  lines: 9-20
  excerpt: |
    from jinja2 import (BaseLoader, ChoiceLoader, DictLoader, Environment, FileSystemBytecodeCache,
        FileSystemLoader, TemplateError, TemplateNotFound, StrictUndefined, select_autoescape)
- path: `packages/ai-parrot/src/parrot/template/engine.py`
  lines: 26-44
  symbol: `JinjaConfig`
  excerpt: |
    @dataclass
    class JinjaConfig:
        template_dirs: list[Path] = field(default_factory=list)
        extensions: list[str] = [... "jinja2_time.TimeExtension", "jinja2_iso8601.ISO8601Extension", "jinja2.ext.do", "jinja2_humanize_extension.HumanizeExtension"]
        autoescape: Any = select_autoescape(["html", "xml", "j2", "jinja", "jinja2"])
        undefined: Any = StrictUndefined  # raise on missing variables
        keep_trailing_newline: bool = True; trim_blocks: bool = True; lstrip_blocks: bool = True
- path: `packages/ai-parrot/src/parrot/template/engine.py`
  lines: 56-66
  symbol: `TemplateEngine.__init__`
  excerpt: |
    def __init__(self, template_dirs=None, *, extensions=None, bytecode_cache_dir=None,
                 filters=None, globals_=None, config: Optional[JinjaConfig] = None, debug=False)
- path: `packages/ai-parrot/src/parrot/template/engine.py`
  lines: 78-84
  excerpt: |
    for d in cfg.template_dirs:
        if not d.exists(): raise ValueError(f"Template directory not found: {d}")
- path: `packages/ai-parrot/src/parrot/template/engine.py`
  lines: 102-118
  excerpt: |
    self._dict_loader = DictLoader({})
    fs_loader = FileSystemLoader([str(p) for p in self._fs_dirs]) if self._fs_dirs else None
    loader = ChoiceLoader([self._dict_loader, fs_loader]) if fs_loader else self._dict_loader
    self.env = Environment(loader=loader, enable_async=True, ..., undefined=cfg.undefined, ...)
- path: `packages/ai-parrot/src/parrot/template/engine.py`
  lines: 164-170
  symbol: `TemplateEngine.add_templates`
- path: `packages/ai-parrot/src/parrot/template/engine.py`
  lines: 181-194
  symbol: `TemplateEngine.render`
  excerpt: |
    async def render(self, name: str, params: Optional[Mapping[str, Any]] = None) -> str:
        tmpl = self.get_template(name)
        return await tmpl.render_async(**params)
      except TemplateError as ex: raise ValueError(f"Template error while rendering '{name}': {ex}")
- path: `packages/ai-parrot/src/parrot/template/engine.py`
  lines: 196-208
  symbol: `TemplateEngine.render_string`
  excerpt: |
    async def render_string(self, source: str, params=None) -> str:
        tmpl = self.env.from_string(source); return await tmpl.render_async(**params)
- path: `packages/ai-parrot/src/parrot/template/__init__.py`
  lines: 1-3
  excerpt: |
    from .engine import TemplateEngine, JinjaConfig
- path: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
  lines: 319
  excerpt: |
    self._template_engine = TemplateEngine(template_dirs=template_dirs, config=JinjaConfig(autoescape=True))
- path: `packages/ai-parrot-server/src/parrot/services/comm_center/render.py`
  lines: 30
  excerpt: |
    from jinja2 import DebugUndefined, Environment, TemplateSyntaxError
- path: `packages/parrot-formdesigner/src/parrot_formdesigner/services/rest_field_resolver.py`
  lines: 24
  excerpt: |
    from jinja2.sandbox import SandboxedEnvironment
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/tool_dispatcher.py`
  lines: 39
  excerpt: |
    from jinja2 import Environment, StrictUndefined, UndefinedError

## Notes

Key design tension surfaced: TemplateEngine defaults to `select_autoescape` keyed on file extension — a Jira template named `bug.j2` would be HTML-escaped (breaking Jira wiki markup like `{code}`, `*bold*`, `<`). A Jira engine must pass `JinjaConfig(autoescape=False)`. Also, TemplateEngine's `__init__` raises on a missing template dir — config must validate lazily or tolerate absence.
