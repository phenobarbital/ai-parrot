# TASK-2431: Documentation - `persistence:` reference, operator setup, data-loss window

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2428, TASK-2425
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 14

---

## Context

The feature is not shippable undocumented, and one item in particular is a
product obligation rather than a nicety: **fail-5xx means a real respondent's answer is
rejected and not queued when the sink is down.** That was a deliberate decision (spec
section 8), and it has to be visible to whoever operates a survey - not buried in an
exception docstring.

Operators also cannot use the feature at all until they configure the alias allowlist, so that
setup is a hard documentation dependency.

Implements spec section 3 Module 14.

---

## Scope

- Document the `persistence:` block: every target type, every field, and worked examples for a Postgres table and a CSV file.
- Document the alias allowlist an operator MUST configure, including the app key and the env vars each alias kind expects.
- Document the capability matrix (which sink supports write / read / list / provision / extend) and what a `501` means for a form's API surface.
- Document the accepted **data-loss window** prominently: on sink outage the submit returns 503 and the answer is NOT stored anywhere. State that an outbox is a known follow-up.
- Document the provisioning rules: auto-create, additive-only extension, columns never dropped or renamed, a renamed field behaving as an added column.
- Document destination-coordinate immutability (one destination per form, forever).
- Document that `.xlsx` is NOT supported in v1 and why (a workbook cannot be appended).
- Document the CSV concurrency limitation (lock-free append; one line per write).
- Add the docs page(s) to the mkdocs nav.

**NOT in scope**: Any production code. The `[gsheet]` extra itself (TASK-2425 adds it). Migration tooling for existing forms - there is nothing to migrate, since `persistence: None` is unchanged behaviour.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/` | CREATE | Autonomous form persistence reference + operator setup |
| `mkdocs.yml` | MODIFY | Add the new page(s) to the nav |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.
>
> Verified against `dev` on 2026-08-24. All paths are relative to the repo root.
> Line numbers shift as soon as anything above them changes — **re-`grep` before editing**.

### Verified Imports

```python
# No imports - documentation task. Verify every code sample in the docs actually runs
# against the implemented API before marking this task done.
```

### Existing Signatures to Use

```yaml
# The documented shape must match what TASK-2417 actually implemented.
# Re-read packages/parrot-formdesigner/src/parrot_formdesigner/core/persistence.py before writing the reference - do NOT copy the
# spec's sketch verbatim if the implementation diverged.
persistence:
  data:
    type: postgres_table
    connection: survey_db        # ALIAS, resolved server-side
    schema_name: surveys         # NOT `schema` (shadows BaseModel.schema)
    table: nps_2026
  definition:
    type: file
    connection: forms_dir
    path: nps_2026.form.yaml
```

### Does NOT Exist

- ~~`.xlsx` support~~ - an explicit Non-Goal of v1 (spec section 1). The docs must say so plainly so users do not file it as a bug.
- ~~an outbox / retry queue~~ - does not exist. Do not imply submissions are queued on failure.
- ~~a fallback to the generic table~~ - explicitly rejected. Do not describe one.
- ~~runtime-mutable aliases~~ - the allowlist is fixed at app construction; do not document an endpoint for it.
- ~~a target field literally named `schema`~~ - `schema` shadows Pydantic's `BaseModel.schema`. The Postgres target field MUST be named `schema_name`.

---

## Implementation Notes

### Pattern to Follow

Lead with the consequence, not the configuration. The data-loss window belongs in a
prominent admonition near the top of the page, not in a footnote:

```markdown
!!! warning "Submissions are not queued"
    A form with its own `persistence:` block writes **only** to that destination.
    If the destination is unreachable when someone submits, the API returns
    **503** and the answer is **not stored anywhere** - not in the destination,
    and not in the shared submissions table. The respondent must retry.

    This is deliberate: it is honest to the submitter and needs no queue
    infrastructure. A durable outbox is a known follow-up, not shipped in v1.
```

### Key Constraints

- Every code and YAML sample must be verified against the implemented API, not the spec sketch.
- The data-loss window must appear as a prominent admonition, not a footnote.
- State the `.xlsx` Non-Goal explicitly, with the reason.
- Document what an operator must do BEFORE an author can use the feature (the allowlist).
- Follow the repo's existing docs structure and mkdocs nav conventions.

### References in Codebase

- `docs/` - existing structure and admonition style
- `mkdocs.yml` - nav conventions
- `packages/parrot-formdesigner/src/parrot_formdesigner/core/persistence.py` - the authoritative field reference (TASK-2417)
- spec section 7 Known Risks - the source list of caveats to document

---

## Acceptance Criteria

- [ ] The `persistence:` reference documents every target type and every field
- [ ] A worked Postgres example and a worked CSV example are both present and verified to run
- [ ] The alias-allowlist setup is documented, including the app key and expected env vars
- [ ] The capability matrix is documented, with what `501` means for a form
- [ ] The data-loss window appears as a prominent admonition
- [ ] Provisioning rules documented: auto-create, additive-only, never drop/rename, rename==add
- [ ] Coordinate immutability documented
- [ ] `.xlsx` documented as unsupported in v1, with the reason
- [ ] CSV lock-free-append limitation documented
- [ ] New pages present in the mkdocs nav and the site builds
- [ ] No sample references a field or behaviour that does not exist in the implementation

---

## Test Specification

```text
Documentation task - no pytest. Verification instead:

1. Build the site and confirm the new pages render and are reachable from the nav.
2. Execute every YAML/Python sample against the implemented API (construct the
   FormSchema, hit the endpoint) and confirm each works as written.
3. Grep the finished docs for the required topics - each must appear:
     "503", "Retry-After", ".xlsx", "additive", "alias", "501",
     "coordinates", "outbox"
4. Confirm no sample uses `schema:` where the implementation expects `schema_name:`.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** - verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** - before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
4. **Update status** in `sdd/tasks/index/formbuilder-formschema-persistency.json` ->
   `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** -> `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-24
**Notes**: Created `docs/formdesigner-autonomous-persistence.md` covering:
the `persistence:` block reference for all four `data` target types plus
`definition`, with the actual field names re-verified against
`core/persistence.py` (not the spec's design sketch — e.g. the `asyncdb`
`collection` field's no-dots constraint documented, matching TASK-2423's
own resolved deviation); the alias-allowlist operator setup including the
`app["form_sink_aliases"]` app key and the exact registration kwarg ->
env-var-purpose table; the full capability matrix with what `501` means;
the data-loss-window warning as a prominent `!!! warning` admonition
directly under the H1 (not a footnote); every provisioning/evolution rule
(auto-create, additive-only, remove-leaves-column, rename-is-add,
CSV-header-never-rewritten, CSV lock-free-append); destination-coordinate
immutability; the `.xlsx` non-goal with its reason; the `[gsheet]` extra
install command; two worked examples (Postgres table, CSV); and the
reserved-column list. Added the page to `mkdocs.yml`'s nav alongside the
other FormDesigner pages (indentation verified byte-for-byte against its
siblings). Verified every code/YAML sample actually runs against the
implemented API (not copied from the spec sketch): constructed both
worked-example `FormSchema` objects, the top-of-doc `definition` example,
and the full `SinkAliasRegistry` + `setup_form_api(..., alias_registry=)`
snippet from §3, all executed successfully against the real,
already-implemented code. Grepped the finished doc for all eight required
terms (`503`, `Retry-After`, `.xlsx`, `additive`, `alias`, `501`,
`coordinates`, `outbox`) — all present — and confirmed no sample uses
`schema:` where the implementation expects `schema_name:`. Parsed the
markdown through the `markdown` library (tables + fenced_code +
admonition extensions) to confirm it renders without error. Full package
test suite re-run: still exactly the same 40 pre-existing failures,
zero regressions (expected — documentation-only change).

**Deviations from spec**: `mkdocs` itself is not installed in this
environment (`pip show mkdocs` — not found), so "confirm the site builds"
could not be executed literally. Verified nav-entry correctness
structurally instead (exact indentation match against sibling nav
entries) and rendered the page's markdown independently via the
`markdown` library to confirm no syntax errors. A real `mkdocs build`
should still be run in CI/by a maintainer with the docs toolchain
installed before merge, to be safe.
