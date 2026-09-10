# TASK-3078: Documentation: A2UI form cycle, extension keys, dual-wire contract, coverage table; CHANGELOG

**Feature**: FEAT-544 — A2UI v1.0 Form Renderer for parrot-formdesigner (full interaction cycle)
**Spec**: `sdd/specs/a2ui-form-output-renderer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3077
**Assigned-to**: unassigned
**Parallel**: false — Docs only, last.

---

## Context

Spec §3 Module 7. Documents the feature for both audiences: ai-parrot A2UI users (`docs/outputs/a2ui-v1.md`) and parrot-formdesigner users (new `docs/a2ui-renderer.md`), plus the CHANGELOG entry.

---

## Scope

- `docs/outputs/a2ui-v1.md`: add a section "Forms from FormDesigner (FEAT-544)" after "Renderers and degradation": how a `FormSchema` becomes a Basic-primitive surface (no `Form` component, G6), the `parrot_form_*` / `parrot_field_*` / `parrot_role` (`title|status|notice|error`) / `parrot_state` extension keys (add rows to the existing `metadata.extensions` table), the submit `action.event` contract (`form.submit`, `context.submit_url`, `answers` binding), and the dual-wire reply shapes (422 `error` + `updateDataModel`; 200 `updateDataModel` + `updateComponents`).
- `packages/parrot-formdesigner/docs/a2ui-renderer.md` (new): usage (`GET .../render/a2ui`, `A2UIFormRenderer` API incl. `prefilled`/`errors`), the full FieldType coverage table from spec §7 (native / degraded), the request/response examples from spec §2 Data Models, the optional-extra install line (`pip install parrot-formdesigner[a2ui]`), and the v1 non-goals (partials, depends_on, uploads).
- `packages/parrot-formdesigner/CHANGELOG.md`: "Added — A2UI v1.0 renderer (`a2ui` format) and dual-wire `/data` + `/validate` (FEAT-544)".
- Cross-link the spec and proposal.

**NOT in scope**: code changes; README rewrites.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/outputs/a2ui-v1.md` | MODIFY | new section + extension-key rows |
| `packages/parrot-formdesigner/docs/a2ui-renderer.md` | CREATE | renderer + cycle documentation |
| `packages/parrot-formdesigner/CHANGELOG.md` | MODIFY | Added entry |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against `dev` @ `213670ef2` (2026-09-10). Use these exact imports,
> class names and signatures. **DO NOT** invent, guess, or assume any import, attribute, or
> method not listed here. If you need something not listed, VERIFY it exists first with `grep`/`read`.

### Verified Imports
```python
# no code imports — documentation task
```

### Existing Signatures to Use
```python
# docs/outputs/a2ui-v1.md — existing structure: 'The envelope' (15), 'Three catalogs' (73), 'metadata.extensions' table (140-158), 'Validation' (170), 'Renderers and degradation' (206)
# packages/parrot-formdesigner/docs/ — existing: lifecycle-events.md, frontend/
```

### Does NOT Exist
- ~~documenting a `Form` component~~ — there is none
- ~~documenting a `/a2ui` route~~ — submit is `/data`

---

## Implementation Notes

### Pattern to Follow
- Match the tone/structure of `docs/outputs/a2ui-v1.md` (short sections, one JSON example per concept, tables for keys).
- Pull the coverage table verbatim from the spec §7 and keep it in sync with `FIELD_LOWERING` (mention the test that enforces total coverage).

### Key Constraints
- Async-first; Google-style docstrings; strict type hints; Pydantic for any new model; `self.logger = logging.getLogger(__name__)` — never `print`.
- ai-parrot is an OPTIONAL dependency of parrot-formdesigner: every `parrot.*` import in this package must be lazy and guarded (pattern: `renderers/audio.py:151-154`).
- Never hand-write `"version"`; every outbound envelope goes through `serialize()`.
- No `Form` catalog component (spec G6). ai-parrot semantics ride in `metadata.extensions.parrot_*` only.
- Run `pytest` after ANY logic change; run `ruff check` on touched paths; `black` formatting.

---

## Acceptance Criteria

- [ ] `docs/outputs/a2ui-v1.md` has the new section and the extension-key rows; every key named exists in the renderer code.
- [ ] `packages/parrot-formdesigner/docs/a2ui-renderer.md` exists with usage, coverage table, wire examples, install extra, non-goals.
- [ ] CHANGELOG entry added.
- [ ] Markdown renders (no broken tables); links to spec/proposal resolve.

---

## Test Specification

No automated tests — reviewer checks the documents against the shipped code (`FIELD_LOWERING`, extension keys, reply shapes).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/a2ui-form-output-renderer.spec.md` (§2 Overview, §3 Module Breakdown, §6 Codebase Contract, §7 mapping table).
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code confirm every import/signature above still exists (`grep`/`read`); update the contract FIRST if anything drifted.
4. **Update status** in `sdd/tasks/index/a2ui-form-output-renderer.json` → `"in-progress"` with your session ID.
5. **Implement** following the scope, contract and notes. Write the tests first (TDD).
6. **Verify** all acceptance criteria; run the listed pytest commands and `ruff check`.
7. **Move this file** to `sdd/tasks/completed/TASK-3078-a2ui-renderer-docs-changelog.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-11
**Notes**: Added a "Forms from FormDesigner (FEAT-544)" section to
`docs/outputs/a2ui-v1.md` right after "Renderers and degradation" (layout,
the `parrot_*` extension-key additions, the submit contract, the dual-wire
reply shapes), plus two new "See also" cross-links (the new
`a2ui-renderer.md` doc, and the FEAT-544 spec/proposal). Created
`packages/parrot-formdesigner/docs/a2ui-renderer.md` (install extra,
render/submit usage with wire examples, the full 45-entry FieldType
coverage table transcribed from `FIELD_LOWERING`, v1 non-goals, cross-links
back). Added a CHANGELOG "Added" entry under `[Unreleased]`. Cross-checked
every `parrot_*` key named in both docs against a literal `grep` of
`renderers/a2ui.py` — all present, and I caught one my first draft missed
(`parrot_role="description"` on the form's description `Text`, alongside
`"title"`) and added it to both docs.

**Deviations from spec**: the FieldType coverage table lists **45** entries,
not "47" as the spec/task text states — `list(FieldType)` verified at 45
members; this stale count was already flagged and documented in TASK-3072's
Completion Note, and this doc transcribes the actual (verified) table
rather than repeating the spec's stale figure.
