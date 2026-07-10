---
id: F007
query: OutputMode enum and renderer registry
type: read
path: packages/ai-parrot/src/parrot/outputs/formats/__init__.py
lines: 19-105
---

OutputMode has 31 members. No A2UI member.
_MODULE_MAP has 23 entries. INFOGRAPHIC loads two modules: ('.infographic', '.infographic_html').
register_renderer(mode, system_prompt=None) decorator at lines 47-59.
get_renderer(mode) with lazy loading at lines 62-74.
get_infographic_html_renderer() convenience function at lines 92-105.
Adding A2UI requires: OutputMode.A2UI enum member + _MODULE_MAP entry + A2UIRenderer module.
