# TASK-3804: Correct FEAT-601 AC19's declared multi-distribution pytest command

**Feature**: FEAT-607 — Correct FEAT-601 AC19's declared multi-distribution pytest command
**Spec**: `sdd/specs/fixgroup-73ca3aa6613f.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`sdd/specs/training-agent.spec.md` (FEAT-601, merged to `dev` via PR #1500)
declares AC19 as a single composite `pytest` invocation across four
distributions. It cannot collect (`ImportPathMismatchError` — same-named
top-level `tests` packages across `packages/*/tests/` collide under
pytest's default import mode) and, independently, over-scopes the
`ai-parrot-integrations` slice to the whole `tests/` directory (which
includes unrelated, pre-existing red suites such as
`tests/voice/test_voice_demo_multibrowser.py`). Filed as ledger
`issue:59c2804dc17a` during FEAT-601's adversarial code review.

This task fixes AC19's text only. See spec §1 Non-Goals: fixing the
underlying repo-wide conftest collision itself is explicitly out of scope.

---

## Scope

- Replace the single AC19 line in `sdd/specs/training-agent.spec.md` with
  the exact three-invocation text given in the spec's §3 Module 1.
- Run all three invocations fresh against current `dev` and confirm the
  exact pass counts in spec §4.

**NOT in scope**: any repo-wide pytest configuration change (`--import-mode`,
`tests/__init__.py`, rootdir splitting); fixing any pre-existing unrelated
failing test.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/specs/training-agent.spec.md` | MODIFY | Replace AC19's single-line composite command with three separately-scoped, verified invocations |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Not applicable — no source code touched.

### Existing Signatures to Use

Not applicable — no source code touched.

### Does NOT Exist

- ~~`--import-mode=importlib` fixing the composite AC19 command on its own~~
  — verified NOT sufficient. `pytest --import-mode=importlib
  packages/ai-parrot/tests/knowledge/manuals
  packages/ai-parrot/tests/knowledge/common
  packages/ai-parrot-tools/tests/procedures
  packages/ai-parrot-integrations/tests` still raises `ValueError: Plugin
  already registered under a different name` — a root-level `conftest.py`
  and per-package `packages/<dist>/conftest.py` also participate in the
  collision. Do not re-propose this flag as the fix.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "sdd/specs/training-agent.spec.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Text-only change to one Markdown file. Do not touch any other line in
  the spec.
- Before running the validation commands, copy the compiled
  `parrot.utils.types` extension (and `parrot/utils/parsers/toml.*.so`) into
  the working tree from the main checkout if `ModuleNotFoundError: No
  module named 'parrot.utils.types'` occurs — this is a gitignored build
  artifact, not something to add to git or to the spec text (worktree
  environment gotcha, not a code fix).

### References in Codebase
- `sdd/specs/training-agent.spec.md:913` — the line being replaced.

---

## Acceptance Criteria

- [ ] `sdd/specs/training-agent.spec.md`'s AC19 line is replaced with the
  exact three-invocation text from the FEAT-607 spec §3 Module 1; no other
  line in the file changes.
- [ ] Each of the three invocations passes with the counts below, run fresh:
  - manuals + common: `128 passed, 3 skipped`
  - procedures: `44 passed`
  - integrations (6 named files): `23 passed`

---

## Validation Commands

> Run each of these three separately (never composed into one command —
> that is exactly the bug being fixed).

- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src pytest packages/ai-parrot/tests/knowledge/manuals packages/ai-parrot/tests/knowledge/common -q`
- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest packages/ai-parrot-tools/tests/procedures -q`
- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src pytest packages/ai-parrot-integrations/tests/test_channel_delivery_matrix.py packages/ai-parrot-integrations/tests/test_media_download.py packages/ai-parrot-integrations/tests/test_media_urls.py packages/ai-parrot-integrations/tests/test_media_urls_teams_slack.py packages/ai-parrot-integrations/tests/test_media_urls_telegram.py packages/ai-parrot-integrations/tests/test_media_urls_whatsapp.py -q`

---

## Test Specification

Not applicable — documentation-only fix, no new test code.

---

## Agent Instructions

When you pick up this task:

1. Read `sdd/specs/fixgroup-73ca3aa6613f.spec.md` for full context.
2. Verify the anchor line at `sdd/specs/training-agent.spec.md:913` still
   reads exactly as declared in the Edit Sites table before editing.
3. Replace it with the three-invocation text.
4. Run all three validation commands and confirm the exact pass counts.
5. Move this file to `tasks/completed/`, update the index, fill in the
   Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
