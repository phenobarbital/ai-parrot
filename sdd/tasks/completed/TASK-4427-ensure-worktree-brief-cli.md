# TASK-4427: `ensure_worktree --brief-key` CLI input

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4425, TASK-4426
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, Integration Points (`/sdd-brief` worktree step →
`ensure()`). `/sdd-brief` must provision its worktree through the shared CLI
(FEAT-552: nobody hand-rolls `git worktree add`). The brief file itself is
written **inside** the worktree after it exists, so the CLI cannot read it —
it takes the identity directly: `--slug <slug> --brief-key <KEY>
[--base-branch main|dev|staging]`, and plans via
`brief_meta.brief_worktree_plan` instead of `plan_worktree`/`FlowMeta`.

---

## Scope

- Add `--brief-key` to `main()` in `scripts/sdd/ensure_worktree.py`. When
  present: default `--base-branch` to `main`, plan with
  `brief_worktree_plan(slug=..., key=..., base_branch=...)`, skip
  `resolve_flow`/`plan_worktree` entirely.
- Refuse `--brief-key` combined with `--feature-id`, `--jira-key`, or
  `--type` (exit 1 with a clear stderr message).
- JSON output shape is unchanged (`name`, `path`, `worktree_path`,
  `base_ref`, `created`).
- Tests in `tests/sdd_scripts/test_ensure_worktree.py`.

**NOT in scope**: the ledger ⇒ dev rule (enforced by `BriefMeta`, TASK-4425,
and by `/sdd-brief` itself, TASK-4429 — the CLI does not know the source);
any change to `ensure()`'s signature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/ensure_worktree.py` | MODIFY | `--brief-key` flag + brief planning branch |
| `tests/sdd_scripts/test_ensure_worktree.py` | MODIFY | CLI tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow  # verified: scripts/sdd/ensure_worktree.py:20
from scripts.sdd.brief_meta import brief_worktree_plan                      # created by TASK-4425
```

### Existing Signatures to Use
```python
# scripts/sdd/ensure_worktree.py — main(argv) -> int                         # line 225
#   parser.add_argument("--jira-key", ...)                                   # lines 236-240
#   parser.add_argument("--spec", help="Path to spec markdown file.")        # line 241 (anchor)
#   parser.add_argument("--type", choices=["feature", "hotfix"], ...)        # line 244
#   flow resolution + `        plan = plan_worktree(`                        # lines 252-278 (anchor at 273)
#   require_paths from --spec / --index                                      # lines 280-285
#   ensure(...) call + JSON print                                            # lines 289-314
#   `except Exception as e: sys.stderr.write(f"Error: {e}\n"); return 1`     # lines 318-320

# scripts/sdd/brief_meta.py (TASK-4425)
def brief_worktree_plan(*, slug: str, key: str, base_branch: str) -> WorktreePlan
#   raises ValueError on an unsafe slug/key
```

### Does NOT Exist
- ~~`--brief <path>`~~ — rejected: the brief does not exist before the worktree does.
- ~~`--type brief`~~ — `--type` keeps `choices=["feature", "hotfix"]`; do not extend it.
- ~~`plan_worktree(..., brief_key=...)`~~ — never; plan via `brief_worktree_plan`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/ensure_worktree.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_ensure_worktree.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/ensure_worktree.py#main",
    "sym:scripts/sdd/ensure_worktree.py#ensure"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The brief branch must run **before** the existing `--jira-key ⇒ hotfix`
  inference (lines 258-263), so a brief never falls into `resolve_flow`.
- Errors surface through the existing `except Exception` → `Error: …` / exit 1
  path; raise `ValueError` for the mutual-exclusion refusal.
- `require_paths` handling (`--spec`/`--index`) stays as is and applies to
  briefs too (normally unused: brief files are born inside the worktree).

---

## Implementation Blueprint

### Steps (in order)
1. Add the import and the `--brief-key` argument — *why*: the CLI is the only provisioning entry point (FEAT-552).
2. Split plan construction into a brief branch and the existing flow branch — *why*: briefs must never reach `resolve_flow`/`FlowMeta`.
3. Add the CLI tests — *why*: AC-1..AC-3.

### `scripts/sdd/ensure_worktree.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow' scripts/sdd/ensure_worktree.py)
# AFTER — insert below `from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow` (verified: scripts/sdd/ensure_worktree.py:20)
from scripts.sdd.brief_meta import brief_worktree_plan
```
```python
# occurrences: 1 (verified: grep -c '    parser.add_argument("--spec", help="Path to spec markdown file.")' scripts/sdd/ensure_worktree.py)
# BEFORE — insert above `    parser.add_argument("--spec", help="Path to spec markdown file.")` (verified: scripts/sdd/ensure_worktree.py:241)
    parser.add_argument(
        "--brief-key",
        help="Brief identity (FEAT-698 /sdd-brief): Jira key, ledger short id, or slug. "
        "Plans hotfix-<KEY>-<slug> on main (default) or fix-<KEY>-<slug> on --base-branch; "
        "mutually exclusive with --feature-id, --jira-key and --type.",
    )
```
```python
# occurrences: 1 (verified: grep -c '        plan = plan_worktree(' scripts/sdd/ensure_worktree.py)
# FILL IN: wrap lines 252-278 (the type_override/base_branch_override inference, resolve_flow and
#          plan_worktree) in an `else:` of a new
#              if args.brief_key:
#                  <refuse when args.feature_id or args.jira_key or args.type -> raise ValueError(...)>
#                  plan = brief_worktree_plan(slug=args.slug, key=args.brief_key,
#                                             base_branch=args.base_branch or "main")
#              else:
#                  <existing lines 252-278, unchanged>
#          — bounded by AC-1/AC-2; do not alter the existing branch's behavior (AC-4)
```
**Why**: keeping the legacy branch byte-identical inside `else:` is what makes
AC-4 (no regression for feature/hotfix callers) cheap to verify.

### `tests/sdd_scripts/test_ensure_worktree.py` (MODIFY)
```python
# APPEND at end of file
def test_main_brief_key_dev_plans_fix_worktree(tmp_git_repo: Path, capsys, monkeypatch) -> None:
    """--brief-key with --base-branch dev plans fix-<KEY>-<slug> from origin/dev."""
    monkeypatch.chdir(tmp_git_repo)
    rc = main(["--slug", "fix-x", "--brief-key", "abc123", "--base-branch", "dev", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["name"] == "fix-abc123-fix-x"
    assert out["base_ref"] == "origin/dev"

# FILL IN: test_main_brief_key_defaults_to_main_hotfix_name — use --dry-run so no origin/main is
#          needed; assert name hotfix-<KEY>-<slug> and base_ref origin/main (AC-1)
# FILL IN: test_main_brief_key_rejects_feature_id_jira_and_type — parametrize, assert rc == 1 (AC-2)
```

### FILL IN checklist
- [ ] brief/legacy branch split in `main()` — AC-1/AC-2/AC-4
- [ ] default-to-main dry-run test — AC-1
- [ ] mutual-exclusion tests — AC-2

---

## Acceptance Criteria

- [ ] AC-1: `--slug s --brief-key K` (no base) plans `hotfix-K-s` / `origin/main`; with `--base-branch dev` plans `fix-K-s` / `origin/dev`.
- [ ] AC-2: `--brief-key` combined with `--feature-id`, `--jira-key`, or `--type` exits 1 with an `Error:` message and creates nothing.
- [ ] AC-3: the created brief worktree has no upstream (inherited from TASK-4426 — assert it in the dev test).
- [ ] AC-4: every pre-existing test in `test_ensure_worktree.py` passes unchanged.
- [ ] `ruff check scripts/sdd/ensure_worktree.py tests/sdd_scripts/test_ensure_worktree.py` clean.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_ensure_worktree.py -q`

---

## Test Specification

See the MODIFY block above. Reuse the file's `tmp_git_repo` fixture
(origin + pushed `dev`); use `--dry-run` for main-based cases, since the
fixture has no `origin/main`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-brief-hotfix-flow --feature-id FEAT-698`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-brief-hotfix-flow.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands from the worktree root
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4427 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
