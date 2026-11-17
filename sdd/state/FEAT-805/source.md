---
kind: inline
jira_key: null
fetched_at: 2026-11-04T22:05:00Z
summary_oneline: "Make the SDD flow (commands, agents, scripts, installer, config) work in non-Python repositories such as TypeScript + SvelteKit"
---

## Request (verbatim, 2026-11-04)

> El actual flujo SDD está muy enfocado a paquetes python (busca cosas en pyproject.toml, etc) pero hemos
> usado el flujo SDD en otras condiciones, ejemplo proyectos con typescript+svelte como este:
> `/home/jesuslara/proyectos/navigator/navigator-frontend-next`, entonces deberíamos homologar los comandos
> y el flujo sdd para funcionar dentro de repositorios no-python

## Clarification (verbatim, same session)

> lo que señalo es que hay cosas (como el modo nativo, etc) son leídas desde pyproject.toml y ese archivo
> no existiría en un repo no-python

## Decisions taken in the Q&A (same session)

1. Where the configuration that today lives only in `pyproject.toml` must live: **`sdd/config.json`**
   (extend `SddConfig`; `pyproject.toml` stays as a fallback).
2. Scope: **everything, in phases** — config and runners; lint/format and worktree dependencies; neutral
   prompts, templates and contract-probe; migrate `navigator-frontend-next` as the acceptance test.
3. How lint / format / type-check are declared in a non-Python repository: **auto-detected profiles**
   (detect `package.json`, `Cargo.toml`, … and pick the tools).
4. How a worktree gets its dependencies: **a declared setup command** that `ensure_worktree` runs on the
   host when it creates the worktree.
