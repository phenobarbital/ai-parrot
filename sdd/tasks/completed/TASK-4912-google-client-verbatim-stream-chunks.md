# TASK-4912: Return Gemini stream chunks verbatim in _safe_extract_text

**Feature**: FEAT-781 — google-client-fixes
**Spec**: `sdd/specs/google-client-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4911
**Assigned-to**: unassigned

**Discovered-from**: `issue:d34e3f558f8e`

---

## Context
Spec §1.2 / §2 M2. Stream chunks are `.strip()`ped → glued words, collapsed Markdown tables, corrupted final text/history.

## Scope
- In `_safe_extract_text`, when `is_stream_chunk=True`: return `response.text` verbatim; append each non-thought `part.text` verbatim, keeping whitespace-only parts; return the joined parts verbatim. The non-stream path stays unchanged.
- Unit tests (spec §4, M2 rows) appended to `test_google_client_fixes.py`.

**NOT in scope**: other clients; the non-stream whitespace path.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/client.py` | MODIFY | stream branch of _safe_extract_text |
| `packages/ai-parrot-client-google/tests/unit/test_google_client_fixes.py` | MODIFY | M2 tests |

## Codebase Contract
See spec §6 (anchors :2783, :2821, :2852).

## Complexity Contract
```json
{"schema_version": 1, "targets": [{"path": "packages/ai-parrot-client-google/src/parrot/clients/google/client.py", "action": "MODIFY"}, {"path": "packages/ai-parrot-client-google/tests/unit/test_google_client_fixes.py", "action": "MODIFY"}], "contract_symbols": ["sym:packages/ai-parrot-client-google/src/parrot/clients/google/client.py#GoogleGenAIClient._safe_extract_text"]}
```

## Acceptance Criteria
- [ ] Spec AC-4, AC-5.

## Validation Commands
- `pytest packages/ai-parrot-client-google/tests/unit/test_google_client_fixes.py -q`

---

## Agent Instructions
Work in `.claude/worktrees/feat-FEAT-781-google-client-fixes`; run tests with
`PYTHONPATH=packages/ai-parrot-client-google/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src`;
close with `scripts/sdd/close_task.sh TASK-4912 google-client-fixes verified`.

---

## Completion Note
**Completed by**: agent:sdd-fix (Claude Opus 5.5)
**Date**: 2026-10-30
**Notes**: `_safe_extract_text(..., is_stream_chunk=True)` now returns `response.text`, each non-thought
`part.text`, and the joined parts verbatim. 4 new tests (the issue's 6-chunk sequence joins exactly). Sibling
Google unit tests (48) pass, plus `test_google_client.py`.
**Deviations from spec**: `packages/ai-parrot/tests/test_google_client.py::test_google_ask_stream` asserted the
buggy `"Helloworld"` (chunks `"Hello"`, `" world"`); it is not in the task's file list and was updated to
`"Hello world"`. Resolves `issue:d34e3f558f8e`.
