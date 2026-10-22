# TASK-4612: Document the native-artifact sync for agents

**Feature**: FEAT-722 — Worktree Native Artifact Sync
**Spec**: `sdd/specs/worktree-native-artifact-sync.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. The behaviour this feature adds is invisible unless the
agent-facing rules say so. Today `sdd-worker` sessions repeatedly conclude on
their own that *"the compiled `parrot.utils.types` module is missing, which is
the known worktree limitation"* and then improvise a one-off copy — or, worse,
test the main checkout's code by dropping the `PYTHONPATH` prefix (project
memory: *worktree-tests-run-main-checkout-code*).

That phrase appears **nowhere in the repository** (verified:
`grep -rn "known worktree limitation" .claude/ .agent/` returns nothing) — it is
folklore each session re-derives from the missing file. The fix is therefore to
state the positive fact in the rules the sessions actually read.

This task has **no `depends_on`**: it documents decisions the spec already
fixes (the declaration's location, the two flags, the two env vars, the two
manual build commands), not symbols it must import. It is deliberately
independent so it can land in the same wave as the first implementation task.

---

## Scope

- `.claude/rules/worktree-management.md` §4 and its twin
  `.agent/skills/worktree-management/SKILL.md`: add the native-artifact
  sentence next to the existing `PYTHONPATH` bullet.
- All three `sdd-worker` copies (`.claude/agents/sdd-worker.md`,
  `.agent/agents/sdd-worker/agent.md`, and the dev-loop's
  `_subagent_data/sdd-worker.md`): add one line after the
  `ensure_worktree` block stating that native artifacts arrive with the
  worktree and what to do when a warning says they did not.
- Add `tests/sdd_scripts/test_feat722_doc_contract.py` following the
  `test_feat709_doc_contract.py` pattern, so the three twins cannot drift.

**NOT in scope**: `CLAUDE.md` (the worktree rule is already linked from it);
`docs/` long-form guides; any code change; `/sdd-start` or `/sdd-done`
command docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/rules/worktree-management.md` | MODIFY | Native-artifact sentence in §4 |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | Same sentence (twin) |
| `.claude/agents/sdd-worker.md` | MODIFY | Line after the ensure_worktree block |
| `.agent/agents/sdd-worker/agent.md` | MODIFY | Same line (twin) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md` | MODIFY | Same line (dev-loop copy) |
| `tests/sdd_scripts/test_feat722_doc_contract.py` | CREATE | Twin-parity / content contract |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# tests/sdd_scripts/test_feat722_doc_contract.py — mirror test_feat709_doc_contract.py:1-8
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[2]
SUBAGENT = "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data"
```

### Existing Signatures to Use — verified anchors (HEAD a99dd4fe9)
```
.claude/rules/worktree-management.md:52         (occurrences: 1)
  "- The shared `.venv` is editable-installed against the **main checkout**, so a bare
   `pytest` inside a worktree imports the wrong branch. Prefix with
   `PYTHONPATH=packages/ai-parrot/src` (one entry per changed package). Never `uv sync`
   inside a worktree — …"
.agent/skills/worktree-management/SKILL.md:50   (occurrences: 1) — same bullet, verbatim

.claude/agents/sdd-worker.md:251                               (occurrences: 1)
.agent/agents/sdd-worker/agent.md:200                          (occurrences: 1)
.../_subagent_data/sdd-worker.md:251                           (occurrences: 1)
  anchor line in all three:  WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree \
```

```python
# tests/sdd_scripts/test_feat709_doc_contract.py — the pattern to follow
"""FEAT-709: agent prompts and docs describe run_validation, the gate and the same-seat repair."""
ROOT = Path(__file__).resolve().parents[2]                      # line 8
SUBAGENT = "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data"  # line 9
SELECT_FILES = [".claude/agents/sdd-worker.md", ".agent/agents/sdd-worker/agent.md",
                f"{SUBAGENT}/sdd-worker.md", ...]                # lines 10-18
```

### Facts the documentation must state (all verified)
- The declaration lives in the root `pyproject.toml` under
  `[tool.parrot.worktree]`.
- `ensure_worktree` syncs on **create and reuse**; the `sdd-coder` pool syncs
  every attempt sub-worktree.
- Opt-outs: `--no-native-sync`, `--no-autobuild`,
  `PARROT_WORKTREE_SYNC_NATIVE=0`, `PARROT_WORKTREE_AUTOBUILD=0`.
- Manual builds, when a warning says a build was refused or failed:
  `cd packages/ai-parrot && python setup.py build_ext --inplace` and
  `make -C packages/navrules build-rust-wheel`.
- `maturin develop` must never be used to repair a worktree — it rewrites the
  shared `.venv` (`.claude/rules/worktree-management.md` §4).
- The synced files are gitignored, so they never appear in `git status`.

### Does NOT Exist
- ~~the string "known worktree limitation" anywhere in the repo~~ — verified
  absent; there is no sentence to delete, only one to add.
- ~~a `.agent/rules/worktree-management.md`~~ — the twin is
  `.agent/skills/worktree-management/SKILL.md`. The two files are NOT
  byte-identical (5711 vs 4130 bytes) — do not try to make them so; only the
  quoted bullet is shared verbatim.
- ~~`tests/sdd_scripts/test_feat722_doc_contract.py`~~ — created here.
- ~~`.agents/skills/worktree-management/`~~ — the Codex skill tree has no
  worktree-management skill; do not invent one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/rules/worktree-management.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/skills/worktree-management/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/agents/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/agents/sdd-worker/agent.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-worker.md",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_feat722_doc_contract.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- The three `sdd-worker` copies must receive the **same** sentence: the
  dev-loop reads `_subagent_data/sdd-worker.md`, so a copy left behind means
  the coder seats keep the old understanding.
- Keep the additions short — these files are loaded into every session's
  context. One bullet in the rule, one bullet in each agent file.
- Do not reword the existing `PYTHONPATH` bullet; it is still true and is the
  verified anchor other docs quote.

---

## Implementation Blueprint

### Steps (in order)
1. Add the bullet to the rule and its twin — *why*: §4 is where an agent looks
   when a worktree import fails.
2. Add the line to all three `sdd-worker` copies — *why*: that is the file the
   session with the recurring warning is actually reading.
3. Add the doc-contract test — *why*: three copies of one sentence drift
   silently; this repo already guards that with `test_feat709_doc_contract.py`.

### `.claude/rules/worktree-management.md` + `.agent/skills/worktree-management/SKILL.md` (MODIFY)
```markdown
# occurrences: 1 in each (verified: grep -cF 'The shared `.venv` is editable-installed' <file>)
# AFTER — insert as the next bullet below the `PYTHONPATH=packages/ai-parrot/src`
#   bullet (verified: worktree-management.md:52, SKILL.md:50)
- Compiled artifacts arrive with the worktree (FEAT-722): every `.so` is gitignored, so
  `ensure_worktree` copies the ones declared in the root `pyproject.toml`
  (`[tool.parrot.worktree]`) from the main checkout on create **and** on reuse, and the
  `sdd-coder` pool does the same for each attempt sub-worktree. A missing artifact is
  built automatically in the main checkout, under a per-group lock. Do NOT hand-copy
  `.so` files and never run `maturin develop` to repair a tree — it rewrites the shared
  `.venv`. If a warning says a build was refused or failed, run it yourself:
  `cd packages/ai-parrot && python setup.py build_ext --inplace` or
  `make -C packages/navrules build-rust-wheel`. Opt out with `--no-native-sync` /
  `--no-autobuild`, or `PARROT_WORKTREE_SYNC_NATIVE=0` / `PARROT_WORKTREE_AUTOBUILD=0`.
```
**Why this shape**: it answers the three questions a stuck session asks — why is
the file missing, who fixes it, and what do I run if nobody did — and it closes
the two wrong turns (hand-copying, `maturin develop`).

### `.claude/agents/sdd-worker.md`, `.agent/agents/sdd-worker/agent.md`, `_subagent_data/sdd-worker.md` (MODIFY)
```markdown
# occurrences: 1 in each (verified: grep -cF 'WORKTREE_PATH=$(python -m scripts.sdd.ensure_worktree' <file>)
# AFTER — insert below the closing ``` of the ensure_worktree code block
#   (verified: .claude/agents/sdd-worker.md:251, .agent/agents/sdd-worker/agent.md:200,
#    _subagent_data/sdd-worker.md:251)
The command also copies the declared native build artifacts into the worktree —
`parrot.utils.types` and the other compiled extensions are gitignored, so without this
step `import parrot.utils` fails inside the tree (FEAT-722). It builds a missing one
automatically and prints a `warning:` line on **stderr** if it could not; only then run
the build yourself (`cd packages/ai-parrot && python setup.py build_ext --inplace`, or
`make -C packages/navrules build-rust-wheel`). Never hand-copy `.so` files, and never
`maturin develop` — it rewrites the shared `.venv`.
```
**Why**: this is the exact place the recurring "the compiled module is missing"
conclusion is reached, immediately after the worktree is provisioned.

### `tests/sdd_scripts/test_feat722_doc_contract.py` (CREATE)
```python
"""FEAT-722: the worktree rules and the sdd-worker twins describe the native-artifact sync."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUBAGENT = "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data"
WORKER_FILES = [
    ".claude/agents/sdd-worker.md",
    ".agent/agents/sdd-worker/agent.md",
    f"{SUBAGENT}/sdd-worker.md",
]
RULE_FILES = [
    ".claude/rules/worktree-management.md",
    ".agent/skills/worktree-management/SKILL.md",
]


@pytest.mark.parametrize("rel", WORKER_FILES + RULE_FILES)
def test_mentions_the_declaration(rel: str) -> None:
    # FILL IN: assert the file names `[tool.parrot.worktree]` (or FEAT-722) and
    # both manual build commands; bounded by the "facts the documentation must
    # state" list in this task's Codebase Contract.
    raise NotImplementedError


@pytest.mark.parametrize("rel", WORKER_FILES + RULE_FILES)
def test_never_recommends_maturin_develop(rel: str) -> None:
    # FILL IN: assert "maturin develop" appears only in a sentence that forbids it
    # (e.g. the line also contains "never" / "Never"); bounded by the shared-venv ban.
    raise NotImplementedError


def test_worker_twins_carry_the_same_sentence() -> None:
    # FILL IN: assert the inserted paragraph is present and identical across the
    # three WORKER_FILES; bounded by "the dev-loop reads _subagent_data".
    raise NotImplementedError
```
**Why this shape**: parametrised over the real file list so a new twin is one
list entry away, and the three assertions map one-to-one onto the three ways
this documentation goes stale (missing fact, wrong advice, drifted copy).

### FILL IN checklist
- [ ] `test_feat722_doc_contract.py::test_mentions_the_declaration` — which
      strings to require; bounded by the Codebase Contract's facts list.
- [ ] `test_feat722_doc_contract.py::test_never_recommends_maturin_develop` —
      the "forbidden unless negated" assertion; bounded by the shared-venv ban.
- [ ] `test_feat722_doc_contract.py::test_worker_twins_carry_the_same_sentence`
      — the extraction + equality check; bounded by the three-copy rule.

---

## Acceptance Criteria

- [ ] `.claude/rules/worktree-management.md` and
      `.agent/skills/worktree-management/SKILL.md` both carry the new bullet,
      directly after the `PYTHONPATH` bullet, with the existing bullet unchanged
- [ ] All three `sdd-worker` copies carry the same new paragraph after the
      `ensure_worktree` block
- [ ] Every one of the five documents names `[tool.parrot.worktree]` and both
      manual build commands
- [ ] No document recommends `maturin develop`; where it appears, it is forbidden
- [ ] `pytest tests/sdd_scripts/test_feat722_doc_contract.py -q` passes
- [ ] `ruff check tests/sdd_scripts/test_feat722_doc_contract.py` clean
- [ ] No code file is touched by this task

---

## Validation Commands

- `pytest tests/sdd_scripts/test_feat722_doc_contract.py -q`

---

## Test Specification

The module skeleton is in the Implementation Blueprint; complete the three
`FILL IN` bodies. No fixtures are needed — the tests read repository files.
Keep the required-string list in one module-level constant so a future wording
change is a one-line edit.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none. Do not wait for the implementation tasks: the
   facts documented here are fixed by the spec
4. **Verify the Codebase Contract** — re-run each `grep -cF` in the blueprint;
   the five anchors were verified at `a99dd4fe9`
5. **Update status** in the per-spec index → `"in-progress"`, commit only it
6. **Implement** — insert the two paragraphs, then write the test
7. **Verify** the acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the six files this task lists
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4612 worktree-native-artifact-sync verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) — seat: gpt-5.6-luna (codex), 1 attempt
**Date**: 2026-10-22
**Notes**: Documented the native artifact sync in sdd-worker agent copies and worktree-management rule/skill. tests/sdd_scripts/test_feat722_doc_contract.py: 11 passed.

**Deviations from spec**: none
