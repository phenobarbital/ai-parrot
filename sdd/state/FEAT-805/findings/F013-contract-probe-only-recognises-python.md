---
id: F013
query_id: Q013
type: read
intent: "Can the Codebase Contract verifier check symbols in a non-Python file?"
executed_at: 2026-11-04T22:34:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F013 — `sdd-contract-probe` matches only `def`/`class` and `*.py`; a JS/TS/Svelte scanner already exists in the wiki

## Summary

The probe's fixed commands are Python-shaped: `symbol` and `outline` grep for
`(async def|def|class)`, `import` resolves `<mod>.py` / `<mod>/__init__.py`, and `absent`
greps with `--include=*.py`. In a TypeScript repository every symbol reads `missing`
and every "does not exist" claim reads `absent`. The wiki knowledge graph already has a
scanner that claims `.js/.jsx/.mjs/.ts/.tsx` and `.svelte`.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/_assets/claude/agents/sdd-contract-probe.md`
  lines: 61-66
  symbol: null
  excerpt: |
    | `symbol` | `path`, `name` | `grep -nE '^[[:space:]]*(async def|def|class) <name>\b' <path>` | ...
    | `import` | `module`, `name` | resolve `module` (dots → `/`) to tracked files with `git ls-files -- '<mod>.py' '*/<mod>.py' '<mod>/__init__.py' ...
    | `absent` | `name`, `scope` (file or dir) | `grep -rnw '<name>' <scope> --include=*.py` | ...
    | `outline` | `path` | `grep -nE '^[[:space:]]*(async def|def|class) ' <path>` | ...

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/languages/javascript.py`
  lines: 3-4
  symbol: null
  excerpt: |
    A single scanner claims every JS/TS suffix (``.js``/``.jsx``/``.mjs``/
    ``.ts``/``.tsx``, FEAT-394) plus ``.svelte`` (FEAT-396): an API outline

## Notes

The probe is consumed by `/sdd-task` (Codebase Contract), `/sdd-spec`,
`/sdd-brainstorm` and `/sdd-proposal` §4d (lane report: `sdd-task.md` L231,
`sdd-brainstorm.md` L148-151, `sdd-proposal.md` L355). `knowledge/wiki/languages/`
also holds `rust.py`, `php.py`, `perl.py`, `luau.py` and `python.py`; whether
`wikitoolkit symbols lookup|outline` can replace the grep commands one-for-one was
not tested.
