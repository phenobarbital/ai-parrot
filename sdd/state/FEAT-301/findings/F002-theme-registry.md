---
id: F002
query: ThemeRegistry built-in themes
type: read
path: packages/ai-parrot/src/parrot/models/infographic.py
lines: 1098-1228
---

ThemeRegistry class at lines 1098-1158, singleton `theme_registry` at line 1162.
**4 built-in themes** (not 3): light, dark, corporate, midnight.
Spec claims 3 (light/dark/corporate) — midnight is missing from spec's awareness.
All registered via `theme_registry.register(ThemeConfig(...))` at module level.
