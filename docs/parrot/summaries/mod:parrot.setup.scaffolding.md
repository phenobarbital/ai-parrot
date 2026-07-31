---
type: Wiki Summary
title: parrot.setup.scaffolding
id: mod:parrot.setup.scaffolding
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Scaffolding utilities for the parrot setup wizard.
relates_to:
- concept: func:parrot.setup.scaffolding.bootstrap_app
  rel: defines
- concept: func:parrot.setup.scaffolding.class_name_from_slug
  rel: defines
- concept: func:parrot.setup.scaffolding.module_name_from_slug
  rel: defines
- concept: func:parrot.setup.scaffolding.render_template
  rel: defines
- concept: func:parrot.setup.scaffolding.scaffold_agent
  rel: defines
- concept: func:parrot.setup.scaffolding.slugify
  rel: defines
- concept: func:parrot.setup.scaffolding.write_env_vars
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.setup.wizard
  rel: references
---

# `parrot.setup.scaffolding`

Scaffolding utilities for the parrot setup wizard.

Provides all file I/O operations used by the wizard pipeline:

- ``slugify`` / ``class_name_from_slug`` — name transformations
- ``render_template`` — ``string.Template``-based rendering from
  ``parrot/templates/``
- ``write_env_vars`` — safe append to ``.env`` files
- ``scaffold_agent`` — generate an Agent Python file in ``AGENTS_DIR``
- ``bootstrap_app`` — generate ``app.py`` and ``run.py`` in the
  project root

## Functions

- `def slugify(name: str) -> str` — Convert a human-readable name to a URL-safe hyphenated slug.
- `def class_name_from_slug(slug: str) -> str` — Convert a hyphenated slug to a PascalCase class name.
- `def module_name_from_slug(slug: str) -> str` — Convert a hyphenated slug to a valid Python module name.
- `def render_template(template_name: str, context: Dict[str, str]) -> str` — Render a ``string.Template`` file from ``parrot/templates/``.
- `def write_env_vars(env_vars: Dict[str, str], env_path: Path, environment: str='default') -> None` — Write environment variables to a ``.env`` file.
- `def scaffold_agent(agent_config: object, cwd: Path) -> Path` — Scaffold a new Agent Python file from the ``agent.py.tpl`` template.
- `def bootstrap_app(agent_config: object, cwd: Path, force: bool=False) -> bool` — Generate ``app.py`` and ``run.py`` in the project root.
