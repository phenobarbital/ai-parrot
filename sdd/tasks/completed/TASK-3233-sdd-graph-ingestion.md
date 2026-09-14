# TASK-3233: SDD specification and task graph ingestion

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226, TASK-3227, TASK-3230, TASK-3231
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. Specs and per-spec indexes become queryable `spec:` and `task:` nodes, with dependency and declared code-scope edges.

## Scope

- Implement `SDDGraphIngest.ingest_all()` over the shared root's SDD specs and per-spec indexes.
- Parse feature metadata, task status/dependencies, and scoped file references into `implements`, `blocks`, and `touches` edges.
- Make repeated ingestion idempotent through LedgerStore connection-scoped writers.
- Test legacy/missing fields, dependencies, and explicit file scope.

**NOT in scope**: changing SDD artifact formats, rendering CLI output, or scanning undeclared source.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py` | CREATE | SDD parser/projector. |
| `tests/knowledge/wiki/test_ledger_sdd_ingest.py` | CREATE | Idempotent graph-ingest coverage. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`scripts.sdd.sdd_meta.parse` accepts a `Path` and returns `FlowMeta`. `LedgerStore` is created by TASK-3230; `WikiPageRecord` exists in `store.py:362`.

### Existing Signatures to Use
`parse(doc_path: Path) -> FlowMeta` is the metadata parser. Per-spec task indexes live at `sdd/tasks/index/*.json`.

### Does NOT Exist
- ~~a monolithic `sdd/tasks/.index.json` contract~~ — use `sdd/tasks/index/*.json` only.
- ~~automatic ingestion on every file save~~ — explicit ingest only.

## Acceptance Criteria

- [x] Specs/tasks have stable `spec:`/`task:` IDs.
- [x] Dependency/file-scope edges are queryable and repeated ingest is idempotent.
- [x] Linked worktrees read only shared-checkout artifacts.
- [x] `pytest tests/knowledge/wiki/test_ledger_sdd_ingest.py -q` passes.

## Test Specification

Use small temporary SDD fixtures and assert exact pages and edges.

### Completion Note

Dispatched via the `parrot-sdd-coder` pool. The first attempt (codex-spark)
hit the dispatcher's 1800s wall-clock cap with no output; the retry (qwen)
completed and merged cleanly (`merge feat-FEAT-566-sdd-work-ledger--TASK-3233-a2`,
files exactly as declared, no unlisted files).

Post-merge review found the dependency `"blocks"` edge emitted backwards
(`task --blocks--> dependency` instead of `dependency --blocks--> task`) —
the existing tests only assert edge *counts*, not direction, so this
would have slipped through silently and produced wrong results for any
future "what does X block" traversal (e.g. a merge-blocker query). Fixed
directly in `sdd_ingest.py` (still the only file this task owns); all 9
tests remain green, `ruff check` clean.

Seat: qwen (nova) · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct
· Attempts: 2 (codex-spark timeout, qwen success) · Duration: 1801.1s + 325.0s
· Tokens: n/a (codex-spark) + 2,577,696 in / 11,329 out (qwen). Post-merge
edge-direction fix applied by sdd-worker (sonnet).
