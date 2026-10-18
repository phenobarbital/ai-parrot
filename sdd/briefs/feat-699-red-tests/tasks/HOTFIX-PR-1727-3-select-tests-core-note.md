# HOTFIX-PR-1727-3: Root select_tests — a core change is a note, never an escalation

**Feature**: PR-1727 — FEAT-699 red tests
**Spec**: `sdd/briefs/feat-699-red-tests.brief.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:1e684c2b1d72`

---

## Context

`tests/sdd_scripts/test_select_tests.py::test_run_records_green_core_escalation`
(`:225-242`) is the single CI failure of PR #1727 ("Test ai-parrot" jobs, run
39171782303). It runs `scripts/sdd/select_tests.py --tier merge --run` on the fixture
monorepo with `core_fanin_threshold=1` (so `packages/a/src/pa/x.py`, imported by
`packages/b/src/pb/y.py`, is a core hit) and then asserts the next `--json` plan has
`"a" in payload["skipped_escalations"]`. FEAT-699 turned core hits into a plan note
(`test_scope/select.py:198-201`: `"core change (<paths>) — covered by nightly"`) and
never populates `escalated` / `skipped_escalations`, so the assertion fails with
`assert 'a' in []`. Brief decision 4: rewrite the test to assert the new contract.

---

## Scope

- Rename the test to `test_core_change_is_a_note_not_an_escalation` and keep its setup
  (kernel load, `ScopePolicy` patch to `core_fanin_threshold=1`, edit `x.py`).
- Keep the `--run` step (`rc == 0`) so the run path with a core hit is still exercised,
  then call `main([... "--tier", "merge", "--base", "HEAD", "--worktree", ..., "--json"])`
  and assert on the JSON payload:
  - `payload["escalated"] == []` and `payload["skipped_escalations"] == []`;
  - `any(note.startswith("core change (packages/a/src/pa/x.py)") and "covered by nightly" in note for note in payload["notes"])`;
  - `[hit["path"] for hit in payload["core_hits"]] == ["packages/a/src/pa/x.py"]`;
  - every invocation operand is a file (`.py`), never `packages/a/tests` or `packages/b/tests`
    (use the `invocations[*].argv` entries that start with `packages/`).
- Update the docstring to say what FEAT-699 guarantees.

**NOT in scope**: `scripts/sdd/select_tests.py` (its legacy ledger writes on core hits
are issue:9b27d46a6bb2 — do NOT assert `read_ledger(...)` either way), the other tests
in this file (`test_run_rearms_escalation_on_a_later_red_run`,
`test_run_records_green_cap_escalation`, `test_run_rearms_red_cap_escalation` pass on the
branch and stay untouched), `test_scope/*`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_select_tests.py` | MODIFY | rewrite `test_run_records_green_core_escalation` as `test_core_change_is_a_note_not_an_escalation` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.select_tests import main  # verified: tests/sdd_scripts/test_select_tests.py:12
from scripts.sdd.select_tests import _load_kernel  # verified: test_select_tests.py:226 (local import inside the test)
import test_scope.select as select_mod  # verified: test_select_tests.py:229 (after _load_kernel())
from test_scope.policy import ScopePolicy as RealScopePolicy  # verified: test_select_tests.py:230
```

### Existing Signatures to Use
```python
# scripts/sdd/select_tests.py — `main(argv) -> int`; with --json prints
# ScopePlanModel.from_plan(plan).model_dump_json(indent=2)  (select_tests.py:170)
# test_scope/models.py:39 — ScopePlanModel fields:
#   tier, invocations[{distribution, argv, targets[{path, distribution, reason}]}], escalated: list[str],
#   notes: list[str], core_hits: list[{path, module, fanin, forced, distributions}],
#   skipped_escalations: list[str], cap_hits, cap_impacted, mode: str, cached: list[str]
# test_scope/select.py:198-201
#   hits = detect_core(index, list(changed_files), policy=policy)
#   notes.append(f"core change ({hit_paths}) — covered by nightly")   # hit_paths = ", ".join(hit.path ...)
# test_scope/select.py:206 — fallback mode also appends
#   "no test contract declared — bounded fallback (own tests + direct importers)"
# test_scope/impact.py:264
def detect_core(index: ImportIndex, changed: Sequence[str], *, policy: ScopePolicy) -> list[CoreHit]
# fixture_monorepo (test_select_tests.py:22-39): packages/a/src/pa/x.py, packages/a/tests/test_x.py,
#   packages/b/src/pb/y.py (imports pa.x), packages/b/tests/test_y.py, tests/test_root.py, pytest.ini; git-initialised
```

### Does NOT Exist
- ~~`payload["skipped_escalations"]` containing a distribution~~ — FEAT-699 never fills it.
- ~~`payload["escalated"]` containing a distribution~~ — same.
- ~~a `CoreHitModel.path` other than `packages/a/src/pa/x.py` for this fixture~~ — only `x.py` changed.
- ~~`kernel.context.read_ledger` as an assertion target in this test~~ — legacy ledger state is out of scope.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "tests/sdd_scripts/test_select_tests.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/select_tests.py#main",
    "sym:scripts/sdd/select_tests.py#_load_kernel",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#plan_tests",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#detect_core"
  ]
}
```

---

## Implementation Notes

```python
def test_core_change_is_a_note_not_an_escalation(fixture_monorepo, capsys, monkeypatch):
    """FEAT-699: a core change (fan-in >= threshold) is reported as a plan note and never
    escalates a distribution suite — `escalated` / `skipped_escalations` stay empty and every
    operand is a file. Nightly (`nightly-tests.yml`) is the safety net."""
    from scripts.sdd.select_tests import _load_kernel

    _load_kernel()
    import test_scope.select as select_mod
    from test_scope.policy import ScopePolicy as RealScopePolicy

    monkeypatch.setattr(select_mod, "ScopePolicy", lambda: RealScopePolicy(core_fanin_threshold=1))
    (fixture_monorepo / "packages/a/src/pa/x.py").write_text("X = 2\n")

    rc = main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--run"])
    assert rc == 0
    capsys.readouterr()

    main(["--tier", "merge", "--base", "HEAD", "--worktree", str(fixture_monorepo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    # FILL IN: the four assertions listed under Scope
```
`json` is already imported at the top of the file (`:5`).

### Key Constraints
- Do not touch `scripts/sdd/select_tests.py`.
- The `--json` call prints only JSON to stdout (the kernel's navconfig banner goes to
  stderr/logging in this test context — the existing `test_cli_json_and_exit_codes` relies
  on the same `json.loads(capsys.readouterr().out)`).

---

## Acceptance Criteria

- [ ] The renamed test asserts the note, empty `escalated` / `skipped_escalations`, the single core hit, and file-only operands.
- [ ] `pytest tests/sdd_scripts/test_select_tests.py -q` is fully green on the branch.
- [ ] `ruff check tests/sdd_scripts/test_select_tests.py` clean.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_select_tests.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in this worktree** — `.claude/worktrees/fix-PR-1727-feat-699-red-tests`
   (branch `fix-PR-1727-feat-699-red-tests`, based on the tip of
   `origin/feat-FEAT-699-tests-optimization-sdd-flow`).
2. **Run the root suite from the worktree root**: `pytest tests/sdd_scripts/test_select_tests.py -q`
   (it imports `scripts.sdd.select_tests` relative to the cwd and loads the `test_scope`
   kernel by path, so no `PYTHONPATH` is needed).
3. **Verify the Codebase Contract** before writing code.
4. **Implement**, run `ruff check --fix` on the file, run the Validation Command.
5. **Commit the code** — stage only this file: `test(sdd): HOTFIX-PR-1727-3 — core change is a note, not an escalation`.
6. **Update** `sdd/briefs/feat-699-red-tests.index.json` (`status: "done"`, `completed_at`), fill in the
   Completion Note below, commit `sdd: complete HOTFIX-PR-1727-3`.

---

## Completion Note

**Completed by**: sdd-worker (sequential fallback: engine cannot assess brief task ids)
**Date**: 2026-10-19
**Notes**: Test renamed test_core_change_is_a_note_not_an_escalation with the four assertions; tests/sdd_scripts/test_select_tests.py: 20 green.

**Deviations from spec**: none
