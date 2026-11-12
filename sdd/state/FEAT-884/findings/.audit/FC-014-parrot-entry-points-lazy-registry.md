---
id: FC-014
query_id: Q015
type: grep
intent: "Check parrot console-script entry points and the top-level CLI that mounts self."
executed_at: 2026-11-12T20:42:33Z
duration_ms: 400
parent_id: null
depth: 0
---

# FC-014 — Entry points: `parrot` → launcher; root click LazyGroup with module-path registry + install hints

## Summary

Core `ai-parrot` exposes `parrot = "parrot.launcher:main_parrot"` (launcher resolves the venv, then runs the click
root). The root `cli` is a `LazyGroup` whose `_lazy_commands` maps command → module path, including commands that
ship in *other* distributions (`e2e` → ai-parrot-server, `manuals` → ai-parrot-tools, `formdesigner`), with
`_lazy_extras` giving an install hint when the module is missing. `ai-parrot-server` separately exposes
`parrot-studio-migrate`. navigator-auth exposes `navauth = navigator_auth.migrations.cli:console_entry`.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 213-220
  excerpt: |
    [project.scripts]
    parrot = "parrot.launcher:main_parrot"
    parrot-graphindex = "parrot.knowledge.graphindex.cli:main"
    wikitoolkit = "parrot.launcher:main_wikitoolkit"
    bookstore = "parrot.launcher:main_bookstore"

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 164-182
  symbol: `cli`
  excerpt: |
    @click.group(cls=LazyGroup)
    def cli():
        """Parrot command-line interface."""
    cli._lazy_commands = {
        "setup": "parrot.setup.cli",
        "install": "parrot.install.cli",
        ...
        "self": "parrot.self_.cli",

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 199-226
  excerpt: |
    # FEAT-581 — Deterministic E2E gate, ships in ai-parrot-server.
    "e2e": "parrot.e2e.cli",
    _E2E_INSTALL_HINT = "ai-parrot-server: pip install ai-parrot-server"
    cli._lazy_extras = { ..., "e2e": _E2E_INSTALL_HINT, ... }

- path: `packages/ai-parrot-server/pyproject.toml`
  lines: 107-109
  excerpt: |
    parrot-studio-migrate = "parrot.handlers.studio.storage.migrate:main"

## Notes

Precedent for a core command whose implementation lives in a satellite: register the module path and an install hint.
`parrot setup` / `parrot install` also exist (not inspected) — confirm neither already provisions DB tables.
[cross-lane: type=wiki_query, intent=what parrot setup / parrot install do (DB provisioning?)]
