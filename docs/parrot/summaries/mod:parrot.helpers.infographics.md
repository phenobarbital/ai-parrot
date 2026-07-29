---
type: Wiki Summary
title: parrot.helpers.infographics
id: mod:parrot.helpers.infographics
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Helper façade for the infographic template and theme registries.
relates_to:
- concept: func:parrot.helpers.infographics.get_template
  rel: defines
- concept: func:parrot.helpers.infographics.get_theme
  rel: defines
- concept: func:parrot.helpers.infographics.list_templates
  rel: defines
- concept: func:parrot.helpers.infographics.list_themes
  rel: defines
- concept: func:parrot.helpers.infographics.register_template
  rel: defines
- concept: func:parrot.helpers.infographics.register_theme
  rel: defines
- concept: mod:parrot.models.infographic
  rel: references
- concept: mod:parrot.models.infographic_templates
  rel: references
---

# `parrot.helpers.infographics`

Helper façade for the infographic template and theme registries.

Wraps parrot.models.infographic_templates.infographic_registry and
parrot.models.infographic.theme_registry so SDK consumers don't need
to import registry singletons directly.

## Functions

- `def list_templates(detailed: bool=False) -> Union[List[str], List[Dict[str, str]]]` — List available infographic template names.
- `def get_template(name: str) -> InfographicTemplate` — Retrieve a template by name.
- `def register_template(template: Union[InfographicTemplate, dict]) -> InfographicTemplate` — Register a custom infographic template.
- `def list_themes(detailed: bool=False) -> Union[List[str], List[Dict[str, str]]]` — List available infographic theme names.
- `def get_theme(name: str) -> ThemeConfig` — Retrieve a theme by name.
- `def register_theme(theme: Union[ThemeConfig, dict]) -> ThemeConfig` — Register a custom infographic theme.
