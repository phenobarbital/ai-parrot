---
id: F011
query_id: Q025
type: grep
intent: Find prior SDD decisions on packaging / namespace strategy.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 90
parent_id: null
depth: 0
---

# F011 — Two prior specs diverge on namespace strategy; FEAT-201 aligns with the newer one

## Summary

Two prior specs explicitly addressed the namespace-vs-proxy decision and
landed on opposite answers. **FEAT-057 (monorepo-migration, 2026-03-23)**
chose proxy modules + separate `parrot_<name>.*` top-levels and explicitly
rejected PEP 420. **FEAT-079 (formdesigner-package, 2026-04-03, 11 days
later)** chose PEP 420 implicit namespace packages — though the actual
implementation reverted to `parrot_formdesigner.*` (top-level), the spec
language is unambiguous. FEAT-201 aligns with FEAT-079's stated intent.
A third active proposal (`ai-parrot-visualizations`) already references
"ai-parrot-embeddings (ver propuesta de modularización general)" as a
known future package.

## Citations

- path: `sdd/specs/monorepo-migration.spec.md`
  lines: 34
  symbol: explicit rejection of namespace packages
  excerpt: |
    - Namespace packages — we use proxy modules (`__getattr__`), not PEP 420 namespace packages.

- path: `sdd/specs/monorepo-migration.spec.md`
  lines: 116-120
  symbol: rationale for proxy modules
  excerpt: |
    3. **Import proxy via `__getattr__`** (not namespace packages): Module-level `__getattr__` (PEP 562) lets us intercept `from parrot.tools.X import Y` and resolve X from `parrot_tools.X`. Cached after first access — zero overhead on subsequent imports.
    ...
    5. **`parrot_tools` / `parrot_loaders`** package names (underscore, not dot): These are separate top-level packages, not sub-packages of `parrot`. The proxy in `parrot.tools` bridges the gap.

- path: `sdd/specs/formdesigner-package.spec.md`
  lines: 371-384
  symbol: explicit PEP 420 choice
  excerpt: |
    - Use `src/` layout matching `packages/ai-parrot/` structure
    - Namespace package: `parrot` namespace shared between `ai-parrot` and `parrot-formdesigner`
      via implicit namespace packages (no `__init__.py` in `parrot/` directory)
    ...
    - **Namespace package collision**: Both packages define modules under `parrot.*`.
      Must use implicit namespace packages (PEP 420) — no `__init__.py` at the `parrot/`
      level in either package.

- path: `sdd/proposals/ai-parrot-visualizations.proposal.md`
  lines: 213
  symbol: future-reference to ai-parrot-embeddings
  excerpt: |
    `ai-parrot-embeddings` (ver propuesta de modularización general).

- path: `sdd/tasks/completed/TASK-548-formdesigner-package-scaffold.md`
  lines: 29-104
  symbol: PEP 420 task that planned but did not ship pure namespace mode
  excerpt: |
    - Create namespace package layout (NO `__init__.py` at `parrot/` level — implicit namespace)
    ...
    - NO `__init__.py` at `packages/parrot-formdesigner/src/parrot/` — implicit namespace package

## Notes

- The FEAT-079 task TASK-548 planned PEP 420 but the actual layout that
  shipped is `packages/parrot-formdesigner/src/parrot_formdesigner/`
  (separate top-level). So the codebase has NEVER actually exercised
  PEP 420 namespace-extension. FEAT-201 would be the **first** real
  test of the pattern in this repo — a small risk worth calling out.
- A "propuesta de modularización general" is mentioned by
  ai-parrot-visualizations.proposal.md. The synthesis should treat
  FEAT-201 as that proposal's first instantiation.
