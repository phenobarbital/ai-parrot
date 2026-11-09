# HOTFIX-review-evidence-producer-3: `parrot sdd task review record` for the manual `/sdd-start` path

**Feature**: review-evidence-producer — produce the review evidence that `parrot sdd task finalize` requires
**Spec**: `sdd/briefs/review-evidence-producer.brief.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: HOTFIX-review-evidence-producer-1
**Assigned-to**: unassigned

---

## Context

The manual `/sdd-start` path closes tasks with `parrot sdd task finalize` too, but it has no MCP server and no
`coder_record_review`, so it cannot produce `review_evidence` either (brief, Decision 2). This task adds a
shell producer next to the existing `prepare` and `validate` review subcommands, using the `ReviewArtifact`
model from task 1 and the same durable root that `finalize` reads.

## Scope

In `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py`:

- New subparser `record` ("Publish a semantic review as durable evidence for finalize."):
  `--feature` (required; the feature slug, stored as `ReviewArtifact.feature_slug`), `--task` (required;
  `TASK-NNN` or `HOTFIX-<KEY>-<n>`), `--worktree` (required), `--summary` (required, 1–4000 characters),
  `--execution-id` (optional; when omitted generate `str(uuid.uuid4())`), `--fix-commit` (repeatable, full
  SHAs).
- `async def _run_record(...)`: read HEAD with `git -C <worktree> rev-parse HEAD`, build
  `ReviewArtifact(source="manual", ..., recorded_at=<UTC now>)`, publish it with `store.put_artifact`, and
  return `{"execution_id": <id>, "review_ref": <EvidenceRef.model_dump()>}`.
- Reuse `_build_store(worktree)` and the existing exit codes and output shape: success prints
  `{"ok": true, ...}` and exits 0; a pydantic `ValidationError` or `ValueError` prints
  `invalid_input` and exits 2; `OSError` or a failed `git` prints `operation_error` and exits 1.
- Update the module and `main()` docstrings to cover `record`.

In `packages/ai-parrot/src/parrot/sdd/cli.py`, the `"review"` entry (L281): help text becomes
`"Review: prepare | validate | record."`.

`/sdd-start` prompts, each pair kept byte-identical:
`.agents/skills/sdd-start/SKILL.md` = `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-start/SKILL.md`,
and `.claude/commands/sdd-start.md` = `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md`.

- `SKILL.md` step 11 "Close task": after the semantic review, run
  `parrot sdd task review record --feature <slug> --task <id> --worktree <path> --summary "<review>"` and use
  the printed `review_ref` as `review_evidence`. Never write into the evidence store by hand.
- `sdd-start.md` § "Deterministic task inspection and closure (FEAT-584)": one line saying the same.

**NOT in scope**: a producer for `validation_refs` on the manual path (brief, Decisions); ledger review
measurements (the manual path has no coder attempt); `finalize` (task 2); the release-smoke `SCENARIOS`
table — it is keyed by module (`review_checkpoint`, `tests/sdd/test_wheel_only_foreign_repo.py:405`), so a
new subcommand needs no entry.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py` | MODIFY | `record` subcommand |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | help text of the `review` entry |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py` | MODIFY | new tests below |
| `.agents/skills/sdd-start/SKILL.md` | MODIFY | close step uses `review record` |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-start/SKILL.md` | MODIFY | byte-identical twin |
| `.claude/commands/sdd-start.md` | MODIFY | close section mentions `review record` |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md` | MODIFY | byte-identical twin |

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ b410d43ac4, 2026-11-09)

- `review_checkpoint.py:59` — `def _build_store(worktree: Path) -> ExecutionEvidenceStore:`
- `review_checkpoint.py:84` — `def main(argv: list[str] | None = None) -> int:`
- `review_checkpoint.py:90` — `sub = parser.add_subparsers(dest="command", required=True)`
- `review_checkpoint.py:97` — `validate_parser = sub.add_parser("validate", ...)`
- `cli.py:281` — `"review": ("review_checkpoint", (), "Review checkpoint: prepare | validate."),`
- `.agents/skills/sdd-start/SKILL.md:134` — `` `implementation_sha`, `validation_refs`, `review_evidence`, `fix_commits`, ``
- `.claude/commands/sdd-start.md:277` — `parrot sdd task finalize, inspect returned staged paths and commit explicitly.`
- `tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py:130` — `def test_settlement_and_unknown_gate(tmp_path: Path) -> None:`
- `tests/sdd/test_wheel_only_foreign_repo.py:405` — `"review_checkpoint": Scenario(prepare=_seed_worktree, expect_exit=(0, 1, 2, 3)),`

### Existing Signatures to Use

- `ReviewArtifact` (created by task 1 in `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/optimization_models.py`)
- `ExecutionEvidenceStore.put_artifact(execution_id, payload) -> EvidenceRef`
- `_build_store(worktree) -> ExecutionEvidenceStore` (same root as `finalize_task.py:511`)

### Does NOT Exist

- a `record` subcommand or `_run_record` in `review_checkpoint.py`

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-start/SKILL.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/sdd-start/SKILL.md", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-start.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py#main",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/review_checkpoint.py#_build_store",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/evidence.py#ExecutionEvidenceStore.put_artifact"
  ]
}
```

## Acceptance Criteria

- [ ] `review record` prints `{"ok": true, "execution_id": ..., "review_ref": {...}}`; the reference resolves
      under the durable root and parses as a `ReviewArtifact` with `source="manual"` and the worktree HEAD.
- [ ] Without `--execution-id` a fresh UUID is generated and printed; with one, it is used.
- [ ] An invalid `--task`, an empty `--summary` or an abbreviated `--fix-commit` exits 2 with `invalid_input`
      and writes nothing.
- [ ] Both prompt pairs are byte-identical.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py -q`

## Test Specification

Add to `test_review_checkpoint.py`, calling `main([...])` with a git worktree in `tmp_path` and
`SDD_CODER_TELEMETRY_DIR` pointed at a temporary durable root:

- `test_record_publishes_manual_review_artifact`
- `test_record_generates_execution_id_when_omitted`
- `test_record_rejects_invalid_input_without_writing`

## Agent Instructions

Read the brief first. Touch only the listed files. Keep each prompt pair byte-identical (copy the edited file
over its twin). Run the validation commands with `PYTHONPATH=packages/ai-parrot/src` from the worktree root.

## Completion Note

Merged by the engine; merge-tier and feature-tier validation green (93 passed, exit 0; supervisor labels the outcome
`timed_out` despite exit 0 well inside its budget). Seat gpt-5.6-sol returned an empty delivery first; attempt 2 on gpt-5.6-terra delivered. The `.agents/skills/sdd-start/SKILL.md` twin was not written by the seat and was synced by the orchestrator (587abc55cb). Orchestrator reviewed the diff against the task contract: no corrections.
HEAD at close: 587abc55cbd24d7630f71d996b8497fd8be59bd0.
