---
id: F021
query_id: Q008, Q015
type: grep + glob
intent: "Parent follow-up for cross-lane notes: confirm sdd/migrations file count and whether parrot setup / parrot install already provision DB tables."
executed_at: 2026-11-12T20:46:15Z
duration_ms: 400
parent_id: F013
depth: 1
---

# F021 — parrot setup / install do not touch the database; sdd/migrations has 15 tracked files

## Summary

`git ls-files sdd/migrations` lists **15** files (F004's "17" over-counted; F017/F020 are correct). The root
LazyGroup registers `setup` → `parrot.setup.cli`, `conf` → `parrot.install.conf`, `install` → `parrot.install.cli`
(cli/__init__.py:171-173). A recursive grep of `packages/ai-parrot/src/parrot/setup` and `packages/ai-parrot/src/parrot/install`
for `CREATE TABLE|creation.sql|ai_bots|asyncpg|default_dsn` returns no hits — neither command provisions or
migrates database tables today, so `parrot self migration` would not overlap an existing DB command in core.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 171-173
  symbol: null
  excerpt: |
    "setup": "parrot.setup.cli",
    "conf": "parrot.install.conf",
    "install": "parrot.install.cli",

- path: `sdd/migrations/`
  lines: n/a
  symbol: null
  excerpt: |
    15 tracked files (git ls-files): 3× FEAT-096 planogram, 2× FEAT-159 ontology (+rollback), FEAT-593, FEAT-638,
    FEAT-752, FEAT-add-prompt-config, FEAT-fix-stale-bot-tool-names, 2× FEAT-fold-*, NAV-7762, ai-bots-homologate-botmodel,
    botmodel-recreate-table

## Notes

Absence claim scoped to the two packages `parrot/setup` and `parrot/install` (core); satellite packages were not grepped.
