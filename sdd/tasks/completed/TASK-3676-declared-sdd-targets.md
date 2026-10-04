# TASK-3676: Declared `sdd/` targets pass fidelity; `sdd/tasks/` and `sdd/ledger/` stay protected

**Feature**: FEAT-597 — dev-loop sdd-coder fixes (empty-delivery gate + declared `sdd/` targets)
**Spec**: `sdd/specs/dev-loop-sdd-coder-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3675
**Assigned-to**: unassigned
**discovered_from**: issue:c748e42f2777

---

## Context

Spec §1-B / §2 M2 / §3 Module 2. `check_fidelity` (fidelity.py:56) flags every changed path under
`sdd/`, and `_commit_declared_changes` (engine.py:2218) never stages a declared `sdd/` path, so a
task whose own deliverable is `sdd/WORKFLOW.md` or `sdd/templates/*.md` (FEAT-576 TASK-3460 /
TASK-3468) is rejected as `unexpected_files` even when the coder's diff is exactly right. The
gate's real job is protecting orchestrator-owned SDD **state** — `sdd/tasks/**` and
`sdd/ledger/**` — not forbidding every deliverable under `sdd/`. The issue's "gitignored-but-
tracked" hypothesis is not the cause (git reports tracked files regardless of ignore rules); the
test with a tracked file under an ignored `templates/` pattern proves it. Ledger issue
`issue:c748e42f2777` (major).

Depends on TASK-3675 only because both edit `engine.py`, `test_engine_plan_merge.py` and the two
docs files (same-file serialization); this task must also narrow the `not p.startswith("sdd/")`
filter TASK-3675 adds in `_delivered_paths`.

---

## Scope

- `fidelity.py`: add `PROTECTED_SDD_PREFIXES` + `is_protected_sdd_path`; narrow `check_fidelity`'s `sdd_touched` to undeclared-or-protected `sdd/` paths.
- `engine.py`: `_commit_declared_changes` and `_delivered_paths` filter declared paths with `is_protected_sdd_path` instead of `startswith("sdd/")`; `_consolidate` de-duplicates `unexpected_files`.
- Tests (§4) in `test_fidelity.py` and `test_engine_plan_merge.py`.
- Docs: narrow the `sdd/` wording in `docs/dev_loop/sdd-coder-orchestrator.md`, `.claude/agents/sdd-worker.md`, `.claude/agents/sdd-coder.md`.

**NOT in scope**: the empty-delivery gate itself (TASK-3675); `parse_task_files`; the task template; `roster.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py` | MODIFY | `PROTECTED_SDD_PREFIXES`, `is_protected_sdd_path`, `check_fidelity` rule |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | import predicate; `_commit_declared_changes` + `_delivered_paths` filters; dedupe `unexpected_files` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_fidelity.py` | MODIFY | `test_fidelity_allows_declared_sdd_docs_never_protected_state` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` | MODIFY | declared-sdd merge test; protected-even-if-declared test |
| `docs/dev_loop/sdd-coder-orchestrator.md` | MODIFY | `fidelity_violation` row wording |
| `.claude/agents/sdd-worker.md` | MODIFY | `fidelity_violation` bullet wording |
| `.claude/agents/sdd-coder.md` | MODIFY | rule 6, checklist, commit comment, Forbidden list |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.fidelity import FidelityReport, check_fidelity, parse_task_files  # verified: fidelity.py:19,56,29
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine   # verified: test_engine_plan_merge.py imports it
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
# engine.py:56 today: from parrot.flows.dev_loop.sdd_coder.fidelity import check_banned_imports, check_fidelity, parse_task_files
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py
_SEPARATOR_ROW = re.compile(r"^\|?[\s|:-]+\|?$")                  # :16 (last module constant before FidelityReport)
class FidelityReport(BaseModel): ok, expected, changed, unexpected, sdd_touched   # :19-26
def check_fidelity(expected: List[str], changed: List[str]) -> FidelityReport   # :56-67
    # :57 docstring "ok ⇔ changed ⊆ expected and no changed path starts with 'sdd/'."
    # :60 sdd_touched = [p for p in changed if p.startswith("sdd/")]

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
# :2218  declared = {p for p in expected if not p.startswith("sdd/")}          (in _commit_declared_changes; occurrences 1)
# :2189-2192 docstring paragraph "…`sdd/` paths are never staged at all, so a coder cannot reach SDD state through this path either."
# :2335  unexpected_files=report.unexpected + report.sdd_touched,               (in _consolidate; occurrences 1)
# TASK-3675 adds `_delivered_paths` with `declared = sorted(p for p in parse_task_files(task_md) if not p.startswith("sdd/"))` — narrow it here too.

# tests
# test_fidelity.py:26 test_fidelity_rejects_unexpected_and_sdd — asserts check_fidelity(["a.py"], ["a.py","b.py","sdd/x.json"]): not ok, unexpected == ["b.py","sdd/x.json"], sdd_touched == ["sdd/x.json"]  (must keep passing)
# test_engine_plan_merge.py:878 test_engine_commits_gitignored_declared_work — pattern: rewrite TASK-0002's task md declared path, `git commit -am`, then manager.create + write + merge()
# conftest.py: sandbox .gitignore is "artifacts/\n"; `_write_and_commit(repo, filename, content, message)`
```

### Does NOT Exist
- ~~`fidelity.is_protected_sdd_path` / `PROTECTED_SDD_PREFIXES`~~ — created by this task.
- ~~a `sdd/` directory in the sandbox other than `sdd/tasks/active/*.md` + `sdd/tasks/index/demo.json`~~ — tests create `sdd/WORKFLOW.md` / `sdd/templates/task.md` themselves.
- ~~`.agent/agents/sdd-worker/agent.md` as a twin~~ — do not edit.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_fidelity.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py", "action": "MODIFY"},
    {"path": "docs/dev_loop/sdd-coder-orchestrator.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-worker.md", "action": "MODIFY"},
    {"path": ".claude/agents/sdd-coder.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py#check_fidelity",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py#FidelityReport",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- A declared **protected** path is never staged: it stays dirty and surfaces through today's `undeclared_files_left_uncommitted` violation (AC5) — do not add a second error path.
- `FidelityReport` shape is unchanged; only `sdd_touched`'s membership narrows.
- Run tests from the worktree with `PYTHONPATH=packages/ai-parrot/src`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the constant + predicate to `fidelity.py` and rewrite `check_fidelity`'s `sdd_touched` — *why*: one definition of "protected" for the gate and the extractor.
2. Import the predicate in `engine.py`; swap the two `startswith("sdd/")` declared filters; dedupe `unexpected_files` — *why*: the extractor must stage exactly what the gate will accept.
3. Tests, then docs/agent wording.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/fidelity.py` (MODIFY — constants)
```python
# occurrences: 1 (verified: grep -c '_SEPARATOR_ROW = re.compile' fidelity.py, :16)
# AFTER — insert below the `_SEPARATOR_ROW = …` line
PROTECTED_SDD_PREFIXES: tuple[str, ...] = ("sdd/tasks/", "sdd/ledger/")
"""Orchestrator-owned SDD state a coder branch may never change, declared or not (FEAT-597 AC5)."""


def is_protected_sdd_path(path: str) -> bool:
    """True when `path` lives under a `PROTECTED_SDD_PREFIXES` prefix (task files, per-spec index, id ledger, issue snapshots)."""
    return path.startswith(PROTECTED_SDD_PREFIXES)
```

### `fidelity.py` (MODIFY — `check_fidelity`)
```python
# occurrences: 1 (verified: grep -c 'def check_fidelity' fidelity.py, :56) — replace the function body :56-67
def check_fidelity(expected: List[str], changed: List[str]) -> FidelityReport:
    """ok ⇔ changed ⊆ expected, and no changed `sdd/` path is undeclared or protected.

    A path under `sdd/` that the task itself declares (e.g. `sdd/WORKFLOW.md`,
    `sdd/templates/*.md`) is a normal deliverable (FEAT-597 AC4). Paths under
    `PROTECTED_SDD_PREFIXES` are orchestrator-owned state and fail even when
    declared (AC5).
    """
    exp = set(expected)
    unexpected = [p for p in changed if p not in exp]
    sdd_touched = [p for p in changed if p.startswith("sdd/") and (p not in exp or is_protected_sdd_path(p))]
    return FidelityReport(
        ok=not unexpected and not sdd_touched,
        expected=list(expected),
        changed=list(changed),
        unexpected=unexpected,
        sdd_touched=sdd_touched,
    )
```
**Why**: keeps `test_fidelity_rejects_unexpected_and_sdd` green (undeclared `sdd/x.json` is still in both lists) while admitting declared docs.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.flows.dev_loop.sdd_coder.fidelity import check_banned_imports, check_fidelity, parse_task_files' engine.py, :56)
# REPLACE that import line with:
from parrot.flows.dev_loop.sdd_coder.fidelity import (
    check_banned_imports,
    check_fidelity,
    is_protected_sdd_path,
    parse_task_files,
)

# occurrences: 1 (verified: grep -c 'declared = {p for p in expected if not p.startswith("sdd/")}' engine.py, :2218)
# REPLACE with:
        declared = {p for p in expected if not is_protected_sdd_path(p)}
# and rewrite the docstring sentence at :2191-2192 to: "Paths under `sdd/tasks/` and `sdd/ledger/` (`fidelity.PROTECTED_SDD_PREFIXES`)
# are never staged even when declared, so a coder cannot reach orchestrator-owned SDD state through this path; other declared `sdd/` paths are ordinary deliverables (FEAT-597)."

# TASK-3675's helper: replace `if not p.startswith("sdd/")` inside `_delivered_paths` with `if not is_protected_sdd_path(p)`
# (occurrences after TASK-3675: verify with grep -c 'if not p.startswith("sdd/")' engine.py → expect 1, then 0)

# occurrences: 1 (verified: grep -c 'unexpected_files=report.unexpected + report.sdd_touched,' engine.py, :2335)
# REPLACE with:
                unexpected_files=list(dict.fromkeys(report.unexpected + report.sdd_touched)),
```
**Why**: the extractor stages exactly the set the gate accepts; a declared protected path is left dirty and reported by the existing leftover check (AC5). Dedupe: an undeclared `sdd/` path appears in both report lists.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_fidelity.py` (MODIFY)
```python
# APPEND after test_fidelity_rejects_unexpected_and_sdd (:26-29)
def test_fidelity_allows_declared_sdd_docs_never_protected_state():
    """Declared `sdd/` docs pass; `sdd/tasks/`/`sdd/ledger/` fail even when declared (FEAT-597 AC4/AC5)."""
    docs = ["sdd/WORKFLOW.md", "sdd/templates/spec.md"]
    assert check_fidelity(docs, docs).ok
    r = check_fidelity(["sdd/tasks/index/x.json"], ["sdd/tasks/index/x.json"])
    assert not r.ok and r.sdd_touched == ["sdd/tasks/index/x.json"] and r.unexpected == []
    # FILL IN: same for a declared "sdd/ledger/issues.jsonl"; and an undeclared "sdd/x.json" in BOTH lists — bounded by AC5
```

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py` (MODIFY)
```python
# APPEND at end of file (pattern :878 test_engine_commits_gitignored_declared_work)
async def test_engine_commits_declared_sdd_doc_targets(git_sandbox_feature, noop_probe):
    """FEAT-576 TASK-3460/3468 shape: declared `sdd/WORKFLOW.md` + tracked `sdd/templates/task.md` under an ignored
    `templates/` pattern are staged and merged (FEAT-597 AC4)."""
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    await _write_and_commit(worktree, "sdd/WORKFLOW.md", "# workflow\n", "add workflow doc")
    await _write_and_commit(worktree, "sdd/templates/task.md", "# template\n", "add tracked template")
    (worktree / ".gitignore").write_text("artifacts/\ntemplates/\n")
    task_md = worktree / "sdd/tasks/active/TASK-0002-demo.md"
    task_md.write_text(task_md.read_text().replace("| `pkg/t2.py` | CREATE | demo file for TASK-0002 |",
        "| `sdd/WORKFLOW.md` | MODIFY | doc |\n| `sdd/templates/task.md` | MODIFY | template |"))
    rc, _out, err = await _git("commit", "-am", "TASK-0002 targets sdd docs", cwd=worktree)
    assert rc == 0, err
    engine = SddCoderEngine(roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]),
                            probe=noop_probe, worktree_base_path=str(base_path))
    ctx = await engine._resolve_feature("demo", str(worktree))
    manager = engine._manager_for(ctx, "TASK-0002", 1)
    path = Path(await manager.create("TASK-0002.a1"))
    (path / "sdd" / "WORKFLOW.md").write_text("# workflow\n\n## New section\n")
    (path / "sdd" / "templates" / "task.md").write_text("# template\ntaxonomy: []\n")
    result = await engine.merge("demo", str(worktree), "TASK-0002")
    assert result.outcome == "merged", result.diagnostics
    # FILL IN: assert both files' new content is on `worktree` and `git status --porcelain` is empty — bounded by AC4


async def test_engine_never_stages_protected_sdd_state_even_if_declared(git_sandbox_feature, noop_probe):
    # FILL IN: declare `sdd/tasks/index/demo.json` as TASK-0002's MODIFY target (same rewrite+commit pattern), edit it in the
    #          sub-worktree, merge() → outcome == "fidelity_violation", unexpected_files == ["sdd/tasks/index/demo.json"],
    #          "undeclared_files_left_uncommitted" in diagnostics, no "engine-committed" commit on branch TASK-0002.a1 — bounded by AC5
```

### `docs/dev_loop/sdd-coder-orchestrator.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '^| `fidelity_violation` |' docs/dev_loop/sdd-coder-orchestrator.md, :217)
# REPLACE the row's "Meaning" cell text "The coder touched `sdd/` or a file not on its task's list" with:
The coder touched orchestrator-owned SDD state (`sdd/tasks/`, `sdd/ledger/` — even if the task declares it) or a file not on its task's list
```

### `.claude/agents/sdd-worker.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c -- '- `fidelity_violation` → treat as `failed`' .claude/agents/sdd-worker.md, :377)
# REPLACE "(a coder touched `sdd/` or unlisted files, OR" with "(a coder touched `sdd/tasks/`/`sdd/ledger/` or unlisted files — a declared `sdd/` doc such as `sdd/WORKFLOW.md` is fine —, OR"
```

### `.claude/agents/sdd-coder.md` (MODIFY)
```markdown
# occurrences: 1 each (verified :78 "6. **YOU NEVER TOUCH `sdd/`.**", :165 "□ Nothing under sdd/ was touched?", :183 "# ONLY the files this task lists — NEVER sdd/ files", :198 "- Editing, moving, or creating anything under `sdd/` (index, task files,")
# :78-84 → "6. **YOU NEVER TOUCH `sdd/tasks/` OR `sdd/ledger/`.**" + keep the paragraph, adding one sentence:
#          "A path under `sdd/` that YOUR task lists under *Files to Create / Modify* (e.g. `sdd/WORKFLOW.md`, `sdd/templates/*.md`) is a normal deliverable."
# :165 → "□ Nothing under sdd/tasks/ or sdd/ledger/ was touched (declared sdd/ docs excepted)?"
# :183 → "# ONLY the files this task lists — NEVER sdd/tasks/ or sdd/ledger/ files"
# :198-199 → "- Editing, moving, or creating anything under `sdd/tasks/` or `sdd/ledger/` (index, task files, completion write-ups) — declared `sdd/` docs excepted."
```

### FILL IN checklist
- [ ] `test_fidelity.py` — remaining assertions; bounded by AC5.
- [ ] `test_engine_plan_merge.py` — two test bodies; bounded by AC4/AC5.
- [ ] `engine.py::_delivered_paths` — narrow the filter TASK-3675 introduced; bounded by AC4 (a declared `sdd/WORKFLOW.md`-only delivery must count as delivered).

---

## Acceptance Criteria

- [ ] AC4: declared non-protected `sdd/` paths are staged by the extraction commit and pass `check_fidelity`.
- [ ] AC5: any changed `sdd/tasks/**` or `sdd/ledger/**` path is a `fidelity_violation`, declared or not, and is never staged.
- [ ] AC6: the three docs/agent files carry the narrowed rule.
- [ ] `test_fidelity_rejects_unexpected_and_sdd` and `test_engine_reports_undeclared_leftovers_as_fidelity_violation` still pass.
- [ ] `ruff check` clean on `fidelity.py` and `engine.py`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_fidelity.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py -q`

---

## Test Specification

See the Blueprint's test blocks: `test_fidelity_allows_declared_sdd_docs_never_protected_state`,
`test_engine_commits_declared_sdd_doc_targets`, `test_engine_never_stages_protected_sdd_state_even_if_declared`.

---

## Agent Instructions

1. Read the spec (§1-B, §2 M2, §6). 2. Verify every anchor's occurrence count (`grep -c`) — TASK-3675 has landed first, so re-check `engine.py` line numbers. 3. Implement from the Blueprint, complete the FILL IN checklist. 4. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`. 5. Commit only the seven listed files.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Fable 5.1 (via `/sdd-fix`, single-agent)
**Date**: 2026-09-24
**Notes**: `fidelity.PROTECTED_SDD_PREFIXES` + `is_protected_sdd_path`; `check_fidelity` only flags undeclared or
protected `sdd/` paths; `_commit_declared_changes` and `_delivered_paths` filter with the predicate; `_consolidate`
de-duplicates `unexpected_files`. Tests: `test_fidelity_allows_declared_sdd_docs_never_protected_state`,
`test_engine_commits_declared_sdd_doc_targets` (tracked `sdd/templates/task.md` under an ignored `templates/` rule
plus `sdd/WORKFLOW.md` → merged), `test_engine_never_stages_protected_sdd_state_even_if_declared`. Full
`tests/flows/dev_loop/sdd_coder/` + `test_subagent_parity.py`: 505 passed, 1 skipped.

**Deviations from spec**: (1) Two extra files: the packaged prompt twins
`packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/{sdd-coder,sdd-worker}.md` must stay byte-identical to
`.claude/agents/*` (`test_review_handoff_contract.py::test_coder_retains_delivery_scope`, `test_subagent_parity.py`);
both were synced here (the worker twin also carries TASK-3675's `empty_delivery:` bullet, which that task had missed).
(2) `test_complexity_routing.py::FakeComplexityDispatcher` returned an output claiming `test.py` while writing
nothing — it was asserting the vacuous merge TASK-3675 now refuses; the fake now writes and commits the task's
declared file like `test_engine_dispatch.FakeDispatcher`. (3) Two pre-existing ruff findings on untouched lines of
`fidelity.py` (PIE810, ASYNC240 on pure `os.path.relpath`) were cleaned so the touched file lints clean.
