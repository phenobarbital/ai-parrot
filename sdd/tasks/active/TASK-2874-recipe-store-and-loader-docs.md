# TASK-2874: Docs — `PgRecipeStore` as the third store, `load_transformer_module` as the host contract

**Feature**: FEAT-528 — Postgres recipe store + agent-package importability
**Spec**: `sdd/specs/pg-recipe-store-and-agent-package-importability.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2873
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. Two facts a host developer needs are undocumented today: that a relational recipe store exists and when to prefer it, and that a recipe's transformers can be registered without importing the agent that ships them. FieldSync (FEAT-559 TASK-2831/2832) is the first consumer and cites this doc.

---

## Scope

- `docs/outputs/infographic-recipes.md` §1 "Stores" (`:64-80`): add `PgRecipeStore` as the third store — constructor, `schema=` keyword, lazy `ensure_schema()`, the `(name, owner)` upsert, when to choose it over `FileRecipeStore` (recipes as data, not deploy artifacts) and `DBRecipeStore` (durable, SQL-visible, no Redis). State plainly that `DBRecipeStore` is Redis.
- `docs/outputs/infographic-recipes.md` §3 "Replay" (`:195-268`): add a "Replaying in another service" subsection: `load_transformer_module(path)` → register datasets → `RecipeRunner(PgRecipeStore(dsn), dataset_manager)`; note that params reach querysource ONLY through `DataSourceSpec.conditions`/`sql` (runner `:467-469`) and that flex's published recipe declares none.
- `docs/outputs/infographic-recipes.md` §8 "Testing" (`:560+`): point at the three integration tests from TASK-2873 and the `NAVIGATOR_PG_DSN` requirement.
- `agents/flex_dashboard.py` docstring: confirm TASK-2872's rewrite reads correctly in context; link this doc section.
- One paragraph on the still-open item: the agents' move to `navigator-plugins` (spec §8, Jesús), and what `finance_reporter.py:73`'s `SKILLS_DIR` anchoring needs when it happens.

**NOT in scope**: FieldSync's own runbook (FEAT-559 TASK-2833); any code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/outputs/infographic-recipes.md` | MODIFY | §1 Stores, §3 Replay, §8 Testing |
| `agents/flex_dashboard.py` | MODIFY (docstring only, if needed) | cross-link |

---

## Codebase Contract (Anti-Hallucination)

### Verified facts to record
```
docs/outputs/infographic-recipes.md headings: ## 1. Concepts (:14) · ### Stores (:64) · ### Triggers (:81) · ## 3. Replay (:195)
  · ### REST (:215) · ## 4. Permissions (:269) · ## 8. Testing (:560)
DBRecipeStore docstring (store.py:305-312): "Redis-backed recipe store ... There is no relational table here"
PgRecipeStore: parrot.handlers.models.recipes (ai-parrot-server) — TASK-2870
load_transformer_module: parrot.tools.infographic_recipes — TASK-2871
RecipeRunner conditions/sql only: runner.py:467-469 ; publish builds DataSourceSpec(dataset, alias, sql): infographic_authoring.py:400-406
Consumer: FieldSync FEAT-559 (fieldsync/sdd/specs/fieldsync-a2ui-surfaces-plane.spec.md §3 Modules 4-5)
```

### Does NOT Exist
- ~~A `docs/outputs/recipe-stores.md`~~ — everything goes into the existing `infographic-recipes.md`; do not create a parallel page.

---

## Acceptance Criteria

- [ ] A reader can choose between the three stores from §1 alone
- [ ] A reader can replay a recipe in a service with no `agents` package from §3 alone (loader → datasets → runner)
- [ ] The params-vs-conditions rule is stated where a reader would otherwise assume filtering
- [ ] The flex docstring no longer contradicts the doc
- [ ] Markdown renders; no dead intra-doc links

---

## Agent Instructions

1. Confirm TASK-2873 is in `sdd/tasks/completed/` (the tests you cite must exist).
2. Write for the host developer who has never opened this repo.
3. Move this file to `sdd/tasks/completed/`, set the index entry to `done`, fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
