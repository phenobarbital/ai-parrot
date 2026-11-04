# TASK-5176: Plan builders use the resolver; `ensure` reuses only the exact target

**Feature**: FEAT-802 — Worktree Root Under `.parrot/`
**Spec**: `sdd/specs/worktree-root-under-parrot.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5174, TASK-5175
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (and the `worktree_status` import swap forced by it). `WorktreePlan.path` is built
from `worktree_root_setting()` instead of the `WORKTREE_ROOT` constant, which is deleted (hard cut,
AC2). `ensure_worktree._find_reusable_worktree` today matches ANY registered worktree by basename,
so a branch left under `.claude/worktrees/` would be silently reused; it must reuse only the exact
resolved target and refuse the expected branch registered anywhere else (AC4).

Because `WORKTREE_ROOT` disappears, every importer of it changes in this same task so the tree never
has a broken import: the shim `scripts/sdd/sdd_meta.py`, `worktree_status.py` (import + root line
only; the legacy row is TASK-5177) and the tests that patch or import the constant.
`test_config.py` is also edited by TASK-5174/5175, hence the dependency on TASK-5175.

---

## Scope

- Delete `WORKTREE_ROOT` from `parrot/knowledge/wiki/ledger/sdd_meta.py`; build `path` as `f"{worktree_root_setting()}/{name}"`.
- Remove `WORKTREE_ROOT` from the re-export lists of `parrot/sdd/scripts/sdd_meta.py` and `scripts/sdd/sdd_meta.py`.
- `brief_meta.py`: import `worktree_root_setting` from `parrot.sdd.config`; build `path` the same way.
- `worktree_status.py`: drop the `WORKTREE_ROOT` import; line 304 becomes `worktree_root(repo_root)`; refresh the comments that name `.claude/worktrees` / `WORKTREE_ROOT` (lines 68, 240, 245, 290, 301-303, 330, 346, 357) to say "the resolved worktree root".
- `ensure_worktree._find_reusable_worktree`: exact-target reuse; expected branch registered at another path → `EnsureWorktreeError` naming both paths and the migration hint, raised before any write.
- Update tests: `test_worktree_plan.py`, `test_brief_meta.py`, `test_ensure_worktree.py`, `test_worktree_status.py` (env instead of patching the constant), `test_scripts_ledger_worktree.py` (`SDD_META_NAMES`), `test_config.py:166`.

**NOT in scope**: the `flow_type="legacy"` report (TASK-5177); installer/doctor (TASK-5179).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` | MODIFY | delete constant; resolver path |
| `packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py` | MODIFY | drop re-export |
| `scripts/sdd/sdd_meta.py` | MODIFY | drop re-export from the repo shim |
| `packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py` | MODIFY | resolver path |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py` | MODIFY | resolver root, comment refresh |
| `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py` | MODIFY | exact-target reuse |
| `tests/sdd_scripts/test_worktree_plan.py` | MODIFY | new default path; absolute env |
| `tests/sdd_scripts/test_brief_meta.py` | MODIFY | `.parrot/worktrees/...` |
| `tests/sdd_scripts/test_ensure_worktree.py` | MODIFY | exact-reuse + legacy-registration tests |
| `tests/sdd_scripts/test_worktree_status.py` | MODIFY | set env instead of patching the constant |
| `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py` | MODIFY | `SDD_META_NAMES` without `WORKTREE_ROOT` |
| `packages/ai-parrot/tests/sdd/test_config.py` | MODIFY | brief CLI expected path |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.config import SddConfig, find_repo_root, load_sdd_config   # verified: knowledge/wiki/ledger/sdd_meta.py:23
from parrot.sdd.config import SddConfig, load_sdd_config                   # verified: sdd/scripts/brief_meta.py:21
from parrot.sdd.scripts.sdd_meta import WORKTREE_ROOT, WorktreePlan        # verified: sdd/scripts/brief_meta.py:22 — WORKTREE_ROOT removed here
from parrot.sdd.scripts.sdd_meta import WorktreePlan, plan_worktree, resolve_flow  # verified: sdd/scripts/ensure_worktree.py:23
from parrot.sdd.config import worktree_root, worktree_root_setting, LEGACY_WORKTREE_ROOT  # created by TASK-5174
from scripts.sdd.ensure_worktree import EnsureWorktreeError, ensure, main  # verified: tests/sdd_scripts/test_ensure_worktree.py:12
from scripts.sdd.sdd_meta import FlowMeta, plan_worktree                   # verified: tests/sdd_scripts/test_ensure_worktree.py:13
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
WORKTREE_ROOT: str = ".claude/worktrees"                                 # line 379 — DELETE (with its comment at 378)
class WorktreePlan(BaseModel): name: str; path: str; base_ref: str       # lines 382-388
def plan_worktree(meta: FlowMeta, *, slug: str, feature_id: str | None = None, jira_key: str | None = None) -> WorktreePlan  # line 393
    path = f"{WORKTREE_ROOT}/{name}"                                     # line 444

# packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py — re-export list lines 15-31, "    WORKTREE_ROOT," at line 20
# scripts/sdd/sdd_meta.py — re-export list lines 10-29, "    WORKTREE_ROOT," at line 17

# packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py
def brief_worktree_plan(*, slug, key, base_branch, config=None) -> WorktreePlan  # path at line 199
def plan_brief_worktree(meta: BriefMeta, *, config: SddConfig | None = None) -> WorktreePlan  # line 204

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py
from parrot.sdd.scripts.sdd_meta import (  # line 20
    WORKTREE_ROOT,                         # line 21
)
    worktree_root = (repo_root / WORKTREE_ROOT).resolve()               # line 304

# packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py
class EnsureWorktreeError(...)                                           # raised for every refusal
    target_path = (repo_root / plan.path).resolve()                      # line 115 — absolute plan.path survives the join
def _worktree_branches(repo_root: Path) -> dict[Path, str]               # line 172 — {resolved worktree path: branch} from porcelain
def _find_reusable_worktree(plan: WorktreePlan, target_path: Path, *, repo_root: Path) -> Path | None:  # line 194
    # today: matches wt_path == target_path OR wt_path.name == plan.name; foreign branch → EnsureWorktreeError("... expected branch ...")

# tests
tests/sdd_scripts/test_worktree_plan.py:7    from scripts.sdd.sdd_meta import WORKTREE_ROOT, FlowMeta, WorktreePlan, plan_worktree
tests/sdd_scripts/test_worktree_plan.py:17   assert plan.path == f"{WORKTREE_ROOT}/feat-FEAT-552-{SLUG}"
tests/sdd_scripts/test_brief_meta.py:112,115 assert ... .path == ".claude/worktrees/..."
tests/sdd_scripts/test_worktree_status.py:121,186  patch("scripts.sdd.worktree_status.WORKTREE_ROOT", str(worktree_root))
tests/sdd_scripts/test_ensure_worktree.py:41  def tmp_git_repo(tmp_path) -> Path   (origin.git + work clone on dev)
tests/sdd_scripts/test_ensure_worktree.py:108 def test_ensure_rejects_path_with_foreign_branch — asserts "expected branch" in message (keep passing)
packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py:21-25 SDD_META_NAMES tuple includes "WORKTREE_ROOT"
packages/ai-parrot/tests/sdd/test_config.py:166  "path": ".claude/worktrees/hotfix-NAV-1-crew-guards",
```

### Does NOT Exist
- ~~`WorktreePlan.absolute_path`~~ / ~~`plan_worktree(repo_root=...)`~~ — signatures stay; the path string carries the root.
- ~~`sdd_meta.WORKTREE_ROOT`~~ after this task — no shim, no deprecation alias (hard cut).
- ~~a repository-wide legacy gate in `ensure`~~ — only the requested branch registered elsewhere is refused.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py", "action": "MODIFY"},
    {"path": "scripts/sdd/sdd_meta.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_worktree_plan.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_brief_meta.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_ensure_worktree.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_worktree_status.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_config.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#plan_worktree",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#WorktreePlan",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py#brief_worktree_plan",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py#discover_worktree_reports",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py#_find_reusable_worktree"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Tests that touch plan paths call `monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)` first.
- `test_worktree_status.py` used to patch the constant to an absolute temp path; set
  `monkeypatch.setenv("WORKTREE_BASE_PATH", str(worktree_root))` instead (absolute values are honoured verbatim).
- In `ensure`, the refusal for "expected branch registered elsewhere" must fire in Step 1 (reuse),
  i.e. before `dry_run` returns and before any fetch/`worktree add`. Message must contain both paths
  and the phrase `parrot doctor` (where the full recipe lives) — e.g.
  `"branch 'X' is already checked out at <other>, not at the expected <target>; move it (see `parrot doctor` for the migration recipe) or remove it first."`
- Keep the existing "expected branch" wording for a foreign branch AT the target (test line 108).
- `git worktree add` with an existing branch name already checked out elsewhere would fail anyway;
  the new check exists so the error is explicit and nothing is created.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `ledger/sdd_meta.py` (delete constant + comment, import `worktree_root_setting`, rebuild path) — *why*: AC2 hard cut.
2. Remove `WORKTREE_ROOT,` from both re-export lists — *why*: otherwise `import` fails at module load.
3. Edit `brief_meta.py` import + path — *why*: same rule for briefs.
4. Edit `worktree_status.py` import, line 304 and comments — *why*: its import of the constant would break; behaviour must follow the resolver.
5. Rewrite `_find_reusable_worktree` — *why*: AC4 exact-target reuse.
6. Update the six test files; run validation.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.sdd.config import SddConfig, find_repo_root, load_sdd_config' ...ledger/sdd_meta.py)
# REPLACE line 23 with:
from parrot.sdd.config import SddConfig, find_repo_root, load_sdd_config, worktree_root_setting
```
```python
# occurrences: 1 (verified: grep -c 'WORKTREE_ROOT: str = ".claude/worktrees"' ...ledger/sdd_meta.py)
# DELETE line 379 and its comment line 378 ("#: Every SDD worktree lives directly under this repo-relative directory.")
```
```python
# occurrences: 1 (verified: grep -c '    path = f"{WORKTREE_ROOT}/{name}"' ...ledger/sdd_meta.py)
# REPLACE line 444 with:
    path = f"{worktree_root_setting()}/{name}"  # FEAT-802: repo-relative unless WORKTREE_BASE_PATH is absolute
```
Also update the `plan_worktree` docstring sentence describing `path` (verify around lines 395-410) to say it is built from `worktree_root_setting()`.

### `packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -c on each anchor)
# REPLACE lines 21-22:
from parrot.sdd.config import SddConfig, load_sdd_config, worktree_root_setting
from parrot.sdd.scripts.sdd_meta import WorktreePlan
# REPLACE line 199 `        path=f"{WORKTREE_ROOT}/{name}",` with:
        path=f"{worktree_root_setting()}/{name}",
```

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    WORKTREE_ROOT,' packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py)
# REPLACE lines 20-22 (the 3-line `from parrot.sdd.scripts.sdd_meta import (` block) with:
from parrot.sdd.config import worktree_root
# REPLACE line 304 `    worktree_root = (repo_root / WORKTREE_ROOT).resolve()` with:
    worktree_root_path = worktree_root(repo_root).resolve()
```
Rename the local to `worktree_root_path` everywhere inside `discover_worktree_reports` (it would
shadow the imported function); `_is_under_worktree_root(wt_path, worktree_root_path)` keeps its signature.

### `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _find_reusable_worktree(plan: WorktreePlan, target_path: Path, *, repo_root: Path) -> Path | None:' ...ensure_worktree.py)
# REPLACE the whole function (lines 194-209) with:
def _find_reusable_worktree(plan: WorktreePlan, target_path: Path, *, repo_root: Path) -> Path | None:
    """Return the existing worktree at exactly ``target_path`` on ``plan.name``, ``None`` when there is none.

    Only the resolved target path is reusable (FEAT-802). A worktree at the target on a DIFFERENT branch
    is an error; so is the expected branch checked out at any other path (for example under the legacy
    ``.claude/worktrees/``) — it is never returned, and nothing is created next to it.
    """
    branches = _worktree_branches(repo_root)
    at_target = branches.get(target_path)
    if at_target is not None and at_target != plan.name:
        raise EnsureWorktreeError(
            f"Worktree at {target_path} is checked out on branch {at_target!r}, "
            f"but expected branch {plan.name!r}."
        )
    if at_target == plan.name:
        return target_path
    # FILL IN: find any other path whose branch == plan.name; if found raise EnsureWorktreeError naming
    #          that path, target_path and `parrot doctor` (migration recipe) — bounded by AC4.
    return None
```

### FILL IN checklist
- [ ] `_find_reusable_worktree` — branch-elsewhere refusal message; bounded by AC4.
- [ ] `test_ensure_worktree.py::test_ensure_reuse_exact_target_only` — exact reuse; foreign branch at target; expected branch at a legacy path and at a custom other path raise before writes (dry_run too); an unrelated branch under `.claude/worktrees/` does not block creation.
- [ ] `test_ensure_worktree.py::test_ensure_rejects_legacy_registration` + `test_ensure_worktree_creates_under_parrot` (spec §4 integration).
- [ ] `test_worktree_plan.py` — `".parrot/worktrees/feat-FEAT-552-<slug>"`; absolute env → absolute path; drop the `WORKTREE_ROOT` import.
- [ ] `test_brief_meta.py:112,115`, `test_config.py:166` — `.parrot/worktrees/...` (delenv first).
- [ ] `test_worktree_status.py:121,186` — env instead of patch.
- [ ] `test_scripts_ledger_worktree.py` — remove `"WORKTREE_ROOT"` from `SDD_META_NAMES`; add `test_sdd_meta_worktree_root_removed` asserting `AttributeError` on both `parrot.sdd.scripts.sdd_meta.WORKTREE_ROOT` and `parrot.knowledge.wiki.ledger.sdd_meta.WORKTREE_ROOT`.

---

## Acceptance Criteria

- [ ] Spec AC2 (sdd_meta half): `WORKTREE_ROOT` is gone from both `sdd_meta` modules and the repo shim (`AttributeError`).
- [ ] Spec AC4: `parrot sdd worktree ensure` creates/reuses only the exact target beneath the default, relative or absolute root; the requested branch registered elsewhere fails before writes with migration guidance; unrelated legacy branches do not block creation.
- [ ] `grep -rn 'WORKTREE_ROOT\b' packages/ai-parrot/src scripts/sdd` returns nothing.
- [ ] `ruff check` clean on the six source files.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_plan.py -q`
- `pytest tests/sdd_scripts/test_brief_meta.py -q`
- `pytest tests/sdd_scripts/test_ensure_worktree.py -q`
- `pytest tests/sdd_scripts/test_worktree_status.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_config.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_ensure_worktree.py — append
def test_ensure_reuse_exact_target_only(tmp_git_repo: Path, monkeypatch) -> None: ...
def test_ensure_rejects_legacy_registration(tmp_git_repo: Path, monkeypatch) -> None: ...
    # git worktree add .claude/worktrees/<plan.name> -b <plan.name> origin/dev → ensure raises, dry_run raises,
    # no .parrot/worktrees/<name> created; after `mv` + `git worktree repair <new>` ensure reuses the new target
def test_ensure_worktree_creates_under_parrot(tmp_git_repo: Path, monkeypatch) -> None: ...
```

---

## Agent Instructions

1. Work in the feature worktree; TASK-5174 and TASK-5175 must be `done`.
2. Verify the contract (`grep -c` every anchor), mark `in-progress`, implement, run every Validation Command with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src:<worktree>` (the `scripts.sdd.*` shims need the worktree root on the path).
3. Commit only the listed files; `parrot sdd task close TASK-5176 worktree-root-under-parrot verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
