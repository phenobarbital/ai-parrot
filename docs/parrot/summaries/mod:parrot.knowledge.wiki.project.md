---
type: Wiki Summary
title: parrot.knowledge.wiki.project
id: mod:parrot.knowledge.wiki.project
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-repository wiki configuration for the ``wikitoolkit`` CLI.
relates_to:
- concept: class:parrot.knowledge.wiki.project.ClaudeIntegrationConfig
  rel: defines
- concept: class:parrot.knowledge.wiki.project.WikiConfigError
  rel: defines
- concept: class:parrot.knowledge.wiki.project.WikiProjectConfig
  rel: defines
- concept: func:parrot.knowledge.wiki.project.config_path
  rel: defines
- concept: func:parrot.knowledge.wiki.project.find_project_root
  rel: defines
- concept: func:parrot.knowledge.wiki.project.load_project_config
  rel: defines
- concept: func:parrot.knowledge.wiki.project.save_project_config
  rel: defines
---

# `parrot.knowledge.wiki.project`

Per-repository wiki configuration for the ``wikitoolkit`` CLI.

A repository that uses the LLM Wiki as its codebase knowledge plane
carries a small JSON config at ``.parrot/wiki.json`` (relative to the
repo root).  The config records where the retrieval plane lives and
how the repo is scanned, and is what the Claude Code integration
(``parrot claude install``) reads to find the wiki from hooks.

All helpers here are dependency-light (stdlib + pydantic) so the
PreToolUse hook can import them with minimal startup cost.

## Classes

- **`ClaudeIntegrationConfig(BaseModel)`** — Settings for the Claude Code integration.
- **`WikiProjectConfig(BaseModel)`** — Repository-level wiki configuration (``.parrot/wiki.json``).
- **`WikiConfigError(ValueError)`** — Raised when an existing ``.parrot/wiki.json`` cannot be used.

## Functions

- `def config_path(root: Path) -> Path` — Return the config file path for a repo root.
- `def find_project_root(start: Optional[Path]=None) -> Optional[Path]` — Walk upwards from ``start`` to the nearest configured repo root.
- `def load_project_config(root: Path) -> WikiProjectConfig` — Load the repo's wiki config.
- `def save_project_config(root: Path, config: WikiProjectConfig) -> Path` — Persist the wiki config to ``.parrot/wiki.json``.
