# TASK-4591: Collection identity — delete the 25 test-root packages + 51 nested colliders, add 1, add importlib mode

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

> **Amendment A (spec rev 0.2)** widens this task: `spike-collect.md` REFUTED strategy (a) alone;
> `spike-identity-fixpoint.md` (verdict `STRATEGY (a′) CONFIRMED`) found that unique derived module
> identities also need 51 nested `__init__.py` removed and 1 added. The lists below are its output
> (`sdd/state/FEAT-720/identity-plan.json`, reproducible with `python -I sdd/state/FEAT-720/identity_fixpoint.py`).

- Delete exactly the 25 top-level `packages/*/tests/__init__.py` files.
- Delete exactly the 51 nested `__init__.py` files listed in the table (classes (viii)/(ix)).
- Create exactly one empty file: `packages/ai-parrot/tests/unit/__init__.py` (class (vii)).
- Append `"--import-mode=importlib"` to the root `pyproject.toml` `addopts` array.

**NOT in scope**: deleting or adding any *other* `__init__.py`; repairing any import site
(TASK-4592/4593/4594) — DO NOT fix a broken import here; the regression test (TASK-4595); touching
`ruff.toml` or `.github/workflows/*`; any `parrot-formdesigner` test failure (FEAT-618); test-level
`sys.modules` pollution (class (xi), out of scope).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | Append `--import-mode=importlib` to `addopts` |
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
| `packages/ai-parrot-embeddings/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-integrations/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-loaders/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-pipelines/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-server/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-tools/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-visualizations/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/parrot-formdesigner/tests/__init__.py` | DELETE | Test-root package marker |
| `packages/ai-parrot-client-amazon/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-anthropic/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-gemma4/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-google/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-grok/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-groq/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-hf/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-jev/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-local/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-moonshot/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-nvidia/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-openai/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-openai/tests/unit/openai/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-openrouter/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-vllm/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-client-zai/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-integrations/tests/integrations/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-integrations/tests/integrations/core/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-integrations/tests/integrations/slack/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-integrations/tests/msteams/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-integrations/tests/telegram/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-integrations/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-integrations/tests/voice/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-server/tests/handlers/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-server/tests/integration/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-server/tests/manager/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-server/tests/mcp/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-server/tests/ui/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-server/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-tools/tests/docker/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-tools/tests/google/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-tools/tests/pulumi/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-tools/tests/querysource/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-tools/tests/scraping/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-tools/tests/security/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-tools/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-visualizations/tests/formats/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot-visualizations/tests/outputs/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot/tests/agents/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot/tests/benchmarks/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot/tests/examples/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot/tests/helpers/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot/tests/mcp/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot/tests/outputs/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot/tests/unit/events/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot/tests/unit/outputs/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/parrot-formdesigner/tests/fixtures/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/parrot-formdesigner/tests/integration/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/parrot-formdesigner/tests/unit/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/parrot-formdesigner/tests/unit/core/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/parrot-formdesigner/tests/unit/services/__init__.py` | DELETE | Nested colliding identity (class (viii)/(ix)) |
| `packages/ai-parrot/tests/unit/__init__.py` | CREATE | Empty; closes the in-tree gap (class (vii)) |

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
| ⇒ nested before this task | **242** | `267 - 25` |
| nested after this task | **192** | `242 - 51 + 1` |

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
    {
      "path": "pyproject.toml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/__init__.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

*(The 76 DELETE rows of the table are authoritative and are deliberately NOT repeated here: the contract validator
compares only the CREATE/MODIFY rows of the table.)*

---

## Implementation Notes

### Key Constraints
- **Exactly 25 + 51 = 76 deletions and 1 creation.** Verify with
  `find packages/*/tests -name '__init__.py' | wc -l` → **192** afterwards. A
  different number means a wrong file was caught; restore it.
- **Never `git add -A`.** This repo has ~60 live worktrees and concurrent
  sessions; stage the 78 paths explicitly (76 deletions, 1 creation, `pyproject.toml`).
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
- `sdd/state/FEAT-720/spike-identity-fixpoint.md` — Amendment A evidence; its last line must read
  `STRATEGY (a′) CONFIRMED` before this task starts (`spike-collect.md` says REFUTED and is superseded)
- `sdd/state/FEAT-720/identity-plan.json` — the exact add/remove lists (authoritative if this table drifts)
- `sdd/specs/tests-test-wheel-layout-tech-debt-2.spec.md` §2 — *Landing*

---

## Implementation Blueprint

### Steps (in order)
1. Read `sdd/state/FEAT-720/spike-identity-fixpoint.md` and stop unless its last line is
   `STRATEGY (a′) CONFIRMED` — *why*: this task is gated on measured evidence.
2. `git rm` the 25 top-level files and the 51 nested files from the table — *why*: the top-level ones claim
   the import name `tests`; the nested ones give two modules the same derived identity or shadow an
   importable name.
2b. Create `packages/ai-parrot/tests/unit/__init__.py` (empty) and `git add` it — *why*: closes the one
   in-tree gap that makes `tests/unit/bots/...` collide with `tests/bots/...`.
3. Append `"--import-mode=importlib",` to `addopts` — *why*: without it pytest
   still resolves test modules through `sys.path` prepending and the conftest
   collision returns one layer down.
4. Assert the nested count is **192** — *why*: a different number means a file outside the plan was
   touched. Relative imports the removals break are expected and are TASK-4592–4594's.
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

### The 25 top-level deletions (then the 51 nested ones from the table, and the 1 creation)
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

# the 51 nested ones: git rm every row marked DELETE (nested) in the table above; then
touch packages/ai-parrot/tests/unit/__init__.py && git add packages/ai-parrot/tests/unit/__init__.py

# MUST print 192
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

- [ ] Exactly 76 files deleted (25 top-level + the 51 listed nested), 1 created.
- [ ] `find packages/*/tests -name '__init__.py' | wc -l` → **192** (AC4).
- [ ] `python -I sdd/state/FEAT-720/identity_fixpoint.py` run on the result proposes **no further** change
      (ADDED and REMOVED both 0).
- [ ] `pyproject.toml` `addopts` contains `--strict-config`, `--strict-markers`
      and `--import-mode=importlib`, in that order; nothing else changed in the
      `[tool.pytest.ini_options]` block.
- [ ] `ruff.toml` and `.github/workflows/*` are unmodified (AC9).
- [ ] `git diff --cached --name-only` lists exactly 78 paths — 76 deletions, 1 creation, `pyproject.toml`.
- [ ] The AC1 pair collect result is recorded in the Completion Note, whether it
      is green or still red pending TASK-4592–4594; the strings `Plugin already registered` and
      `ImportPathMismatchError` must be ABSENT from it (identity defects are this task's).

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
   `sdd/tasks/index/tests-test-wheel-layout-tech-debt-2.json`, and
   `sdd/state/FEAT-720/spike-identity-fixpoint.md` must carry `STRATEGY (a′) CONFIRMED`
4. **Verify the Codebase Contract** — re-run the counts (242 nested now) and re-check
   `pyproject.toml:250`; correct the task file first if anything moved
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file
6. **Implement** from the blueprint; there are no `FILL IN` markers
7. **Verify** every acceptance criterion, especially the 192 count
8. **Commit the code** — stage the 78 paths explicitly, never `git add .` / `-A`
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
