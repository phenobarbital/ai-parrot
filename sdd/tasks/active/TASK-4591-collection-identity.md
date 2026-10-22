# TASK-4591: Collection identity — delete the 25 test-root packages, add importlib mode

**Feature**: FEAT-720 — One Importable Identity per Package Test Tree
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt-2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4590
**Assigned-to**: unassigned
**Discovered-from**: `issue:45cf6a054e06`

---

## Context

Implements spec **Module 2** — the change itself. Small, mechanical, and the
reason every other task in this feature exists.

Each `packages/<dist>/tests/__init__.py` makes that directory the top-level
import name `tests`. Twenty-five directories claim the same name, so collecting
any two in one pytest session raises `ImportPathMismatchError` before a single
assertion runs. `--import-mode=importlib` alone does **not** fix it (verified:
pytest still derives `tests.conftest` from the `__init__.py` chain and fails with
`ValueError: Plugin already registered under a different name`). Both halves are
required.

After this task the branch is **knowingly broken** — ~60 import sites lose the
`tests` package they were resolving against. TASK-4592–4594 repair them. That is
why this feature merges as one PR and never incrementally.

---

## Scope

- Delete exactly the 25 top-level `packages/*/tests/__init__.py` files listed below.
- Append `"--import-mode=importlib"` to the root `pyproject.toml` `addopts` array.

**NOT in scope**: deleting any **nested** `__init__.py` (all 242 stay — they keep
343 relative imports across 231 test files working); repairing any import site
(TASK-4592/4593/4594); the regression test (TASK-4595); touching `ruff.toml` or
`.github/workflows/*` (both key on paths, which this task does not move); any
`parrot-formdesigner` test failure (FEAT-618).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | Append `--import-mode=importlib` to `addopts` |
| `packages/ai-parrot/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-embeddings/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-integrations/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-loaders/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-pipelines/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-server/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-tools/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-visualizations/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/parrot-formdesigner/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-amazon/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-anthropic/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-gemma4/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-google/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-grok/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-groq/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-hf/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-jev/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-local/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-meta/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-moonshot/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-nvidia/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-openai/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-openrouter/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-vllm/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-zai/tests/__init__.py` | DELETE | Test-root package marker |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

None — this task writes no Python.

### Existing Signatures to Use

```toml
# pyproject.toml:247
[tool.pytest.ini_options]           # line 247
addopts = [                         # line 248
    "--strict-config",              # line 249
    "--strict-markers",             # line 250
]                                   # line 251
testpaths = ["tests"]               # line 252
python_files = "test_*.py"          # line 253
python_functions = "test_*"         # line 254
```

### Verified facts (measured on `dev c2fd0ae28`)

| Fact | Value | Command |
|---|---|---|
| top-level `packages/*/tests/__init__.py` | **25**, all 0 bytes | `ls packages/*/tests/__init__.py \| wc -l` |
| all `__init__.py` under `packages/*/tests` | **267** | `find packages/*/tests -name '__init__.py' \| wc -l` |
| ⇒ nested, which must survive | **242** | `267 - 25` |

### Does NOT Exist
- ~~a 26th top-level test-root `__init__.py`~~ — `ai-parrot-advisors`,
  `ai-parrot-openlit-bridge` and `navrules` have none and need no change.
- ~~a per-package `pytest.ini` / `setup.cfg` / `[tool.pytest]` block~~ — pytest
  config lives **only** in the root `pyproject.toml:247`.
- ~~`--import-mode` anywhere in the repo today~~ — this task introduces it.
- ~~`consider_namespace_packages`~~ — not set, and not to be added here. Only
  TASK-4590's evidence could justify it, and it did not ask for it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-embeddings/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-loaders/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-visualizations/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-amazon/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-anthropic/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-gemma4/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-google/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-grok/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-groq/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-hf/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-jev/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-local/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-meta/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-moonshot/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-nvidia/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-openai/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-openrouter/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-vllm/tests/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-client-zai/tests/__init__.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

*(Deletions are declared as `MODIFY` because the Complexity Contract schema has
only `CREATE`/`MODIFY`; the "Files to Create / Modify" table above is
authoritative on the action, and it says DELETE for all 25.)*

---

## Implementation Notes

### Key Constraints
- **Exactly 25 deletions.** Verify with
  `find packages/*/tests -name '__init__.py' | wc -l` → **242** afterwards. A
  different number means a nested file was caught; restore it.
- **Never `git add -A`.** This repo has ~60 live worktrees and concurrent
  sessions; stage the 26 paths explicitly.
- Use `git rm` so the deletions are staged as deletions, not left as untracked
  absences.
- `--import-mode=importlib` is **appended**. Do not reorder, replace or remove
  `--strict-config` / `--strict-markers`.
- Do not touch `testpaths`, `python_files`, `python_functions`,
  `filterwarnings` or `markers`.
- The branch is expected to be red after this task. Do **not** repair an import
  site here to make a run go green — that is TASK-4592–4594's scope, and doing it
  here hides the per-distribution accounting those tasks depend on.

### References in Codebase
- `sdd/state/FEAT-720/spike-collect.md` — TASK-4590's evidence; its §7 verdict
  must read `STRATEGY (a) CONFIRMED` before this task starts
- `sdd/specs/tests-test-wheel-layout-tech-debt-2.spec.md` §2 — *Landing*

---

## Implementation Blueprint

### Steps (in order)
1. Read `sdd/state/FEAT-720/spike-collect.md` §7 and stop unless it says
   `STRATEGY (a) CONFIRMED` — *why*: this task is gated on measured evidence, and
   a `REFUTED` verdict means the spec is revised instead.
2. `git rm` the 25 files from the table — *why*: each one claims the import name
   `tests`, which is the defect itself.
3. Append `"--import-mode=importlib",` to `addopts` — *why*: without it pytest
   still resolves test modules through `sys.path` prepending and the conftest
   collision returns one layer down.
4. Assert the nested count is still 242 — *why*: those files keep 343 relative
   imports working, and losing one silently breaks a test tree TASK-4592–4594 are
   not scoped to repair.
5. Run the AC1 pair collect and record the result, red or green — *why*: it is the
   feature's headline invariant and the first point at which it can be observed.

### `pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '    "--strict-markers",' pyproject.toml)
# AFTER — insert below `    "--strict-markers",` (verified: pyproject.toml:250)
    "--import-mode=importlib",
```
**Why**: `importlib` mode stops pytest inserting each rootdir on `sys.path` and
deriving a module's name from its `__init__.py` chain, which is the half of the
fix the deletions cannot provide on their own. Appending keeps `--strict-config`
and `--strict-markers` in force; both are relied on by the `markers` block at
`pyproject.toml:264`.

### The 25 deletions
```bash
git rm packages/ai-parrot/tests/__init__.py \
       packages/ai-parrot-embeddings/tests/__init__.py \
       packages/ai-parrot-integrations/tests/__init__.py \
       packages/ai-parrot-loaders/tests/__init__.py \
       packages/ai-parrot-pipelines/tests/__init__.py \
       packages/ai-parrot-server/tests/__init__.py \
       packages/ai-parrot-tools/tests/__init__.py \
       packages/ai-parrot-visualizations/tests/__init__.py \
       packages/parrot-formdesigner/tests/__init__.py \
       packages/ai-parrot-client-{amazon,anthropic,gemma4,google,grok,groq,hf,jev,local,meta,moonshot,nvidia,openai,openrouter,vllm,zai}/tests/__init__.py

# MUST print 242
find packages/*/tests -name '__init__.py' | wc -l
```
**Why**: the brace expansion covers exactly the 16 client distributions and the
explicit list covers the other 9, totalling the verified 25. The `find` check is
the guard against a glob that reached too deep — the nested files are
load-bearing and are not this feature's to remove.

### FILL IN checklist
- [ ] none — this task is fully specified. If anything here does not apply
      cleanly, stop and report drift rather than improvising.

---

## Acceptance Criteria

- [ ] Exactly 25 files deleted, all matching `packages/*/tests/__init__.py`.
- [ ] `find packages/*/tests -name '__init__.py' | wc -l` → **242** (AC4).
- [ ] `pyproject.toml` `addopts` contains `--strict-config`, `--strict-markers`
      and `--import-mode=importlib`, in that order; nothing else changed in the
      `[tool.pytest.ini_options]` block.
- [ ] `ruff.toml` and `.github/workflows/*` are unmodified (AC9).
- [ ] `git diff --cached --name-only` lists exactly 26 paths — the 25 deletions
      plus `pyproject.toml`.
- [ ] The AC1 pair collect result is recorded in the Completion Note, whether it
      is green or still red pending TASK-4592–4594.

---

## Validation Commands

- `pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q`

---

## Test Specification

No new test code. TASK-4595 adds the regression test that asserts this task's
end state; adding it here would make this task's own validation circular.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** §2 *Landing* — this task leaves the branch red on purpose
3. **Check dependencies** — TASK-4590 must be `"done"` in
   `sdd/tasks/index/tests-test-wheel-layout-tech-debt-2.json`, and its evidence
   file must carry `STRATEGY (a) CONFIRMED`
4. **Verify the Codebase Contract** — re-run the three counts and re-check
   `pyproject.toml:250`; correct the task file first if anything moved
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file
6. **Implement** from the blueprint; there are no `FILL IN` markers
7. **Verify** every acceptance criterion, especially the 242 count
8. **Commit the code** — stage the 26 paths explicitly, never `git add .` / `-A`
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4591 tests-test-wheel-layout-tech-debt-2 verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
