# TASK-5177: Script consumers resolve the root; `worktree_status` reports legacy entries

**Feature**: FEAT-802 — Worktree Root Under `.parrot/`
**Spec**: `sdd/specs/worktree-root-under-parrot.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5176
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (runtime half). Five modules still spell `.claude/worktrees` inline:
`worktree_environment` (native sandbox writable allow-list), `remove_worktree` (orphan scan),
`worktree_baseline` (default scratch dir), ledger `integration` (outbox temp worktree) and
`worktree_status` (needs the `legacy` flow type so `/sdd-status` shows what still has to move).
Depends on TASK-5176 because both edit `worktree_status.py` / `test_worktree_status.py`, and on
TASK-5174 transitively for the resolver.

---

## Scope

- `worktree_status.py`: `flow_type` gains `"legacy"`; in `discover_worktree_reports`, a porcelain
  entry whose resolved path is under `repo_root/LEGACY_WORKTREE_ROOT` yields
  `WorktreeReport(flow_type="legacy", ready_for_done=False, tasks=[], index_found=False, health=_check_health(...))`
  regardless of branch name, and is not reported twice.
- `worktree_environment.py`: delete `WORKTREE_ADMIN_DIR`; `worktree_admin_dirs` uses `worktree_root(primary)`;
  refresh docstrings at lines 38, 157, 233.
- `remove_worktree.py`: line 220 → `worktree_root(_root())`; line 374 message and module docstring line 4 name the resolved root.
- `worktree_baseline.py`: `_default_scratch` returns `worktree_root(main_root)`; docstring (54) and `--scratch` help (101).
- `ledger/integration.py:376`: `worktree_root(primary) / f"_ledger-outbox-{uuid.uuid4()}"`.
- Tests: `test_worktree_status.py` (legacy entry), `test_worktree_environment.py` (fixture at :343 models `.parrot/worktrees`).

**NOT in scope**: regex/hook/audit consumers (TASK-5178); installer/doctor (TASK-5179).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py` | MODIFY | `legacy` flow type |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | resolver-based admin dir |
| `packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py` | MODIFY | resolver-based orphan scan |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_baseline.py` | MODIFY | resolver-based default scratch |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` | MODIFY | outbox temp under the resolved root |
| `tests/sdd_scripts/test_worktree_status.py` | MODIFY | legacy-entry test |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | fixture + assertion on the new root |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.config import LEGACY_WORKTREE_ROOT, worktree_root  # created by TASK-5174
from parrot.sdd.config import worktree_root                        # worktree_status.py already imports it after TASK-5176
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py
class WorktreeReport(BaseModel):                                          # line 63
    flow_type: Literal["feature", "hotfix", "non-sdd"]                    # line 70
def _is_under_worktree_root(path: Path, worktree_root: Path) -> bool      # line 236
def _check_health(wt_path: Path, base_branch: str) -> WorktreeHealth  # line 203; used at line 369 for non-sdd rows
def discover_worktree_reports(repo_root: Path) -> list[WorktreeReport]    # line 286 (local renamed worktree_root_path by TASK-5176)

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py — imports are stdlib only (lines 9-18)
WORKTREE_ADMIN_DIR = Path(".claude") / "worktrees"                        # line 139 — DELETE
def worktree_admin_dirs(root: Path, git_dir: Path | None) -> tuple[Path, ...]   # line 154
    admin_dir = (primary / WORKTREE_ADMIN_DIR).resolve()                  # line 177

# packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py
    worktree_dir = _root() / ".claude" / "worktrees"                      # line 220
            print("No orphan directories under .claude/worktrees/.")      # line 374

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_baseline.py
def _default_scratch(worktree: Path, baseline_mod: ModuleType) -> Path    # line 53
    return main_root / ".claude" / "worktrees"                            # line 60

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py
    async def _primary_root(self) -> Path:                                # line 241
        tmp = primary / ".claude" / "worktrees" / f"_ledger-outbox-{uuid.uuid4()}"   # line 376

# packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
def _registered_feature_worktree(tmp_path: Path) -> tuple[Path, Path]:    # line 343 — builds main/.claude/worktrees/feat-x
def test_feature_worktree_binds_primary_worktree_admin_dir(...)           # line 360 — asserts (main/".claude"/"worktrees") in binds
```

### Does NOT Exist
- ~~`worktree_environment.WORKTREE_ADMIN_DIR`~~ after this task (AC2) — no alias.
- ~~`WorktreeReport.legacy`~~ — legacy is a `flow_type` value, not a field.
- ~~a dual-root scan in `remove_worktree`~~ — it scans only the resolved root (AC12).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/remove_worktree.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_baseline.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_worktree_status.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py#WorktreeReport",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py#discover_worktree_reports",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#worktree_admin_dirs",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_baseline.py#_default_scratch"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `worktree_environment` runs as a hook on every Bash call (`python -m parrot.sdd.scripts.worktree_environment --hook`).
  Import `worktree_root` **inside** `worktree_admin_dirs` (lazy) so the module's import cost and its
  "works even when the rest of Parrot is unavailable" promise (module docstring line 4) are preserved;
  `parrot.sdd.config` itself imports only pydantic (spec §6).
- Sandbox safety (spec §7): if the resolved root is outside the primary checkout or does not exist,
  `worktree_admin_dirs` keeps returning `()` exactly as today; an absolute external root that exists
  is still returned (it is where worktrees live), unless it is relative to `root`.
- Legacy rows: classify BEFORE `_parse_branch`, using resolved containment under
  `(repo_root / LEGACY_WORKTREE_ROOT).resolve()`; skip the primary checkout itself.
- Tests clear `WORKTREE_BASE_PATH` first.

---

## Implementation Blueprint

### Steps (in order)
1. `worktree_status.py`: widen the Literal, update the field comment, add the legacy branch — *why*: spec §2 data model and AC8.
2. `worktree_environment.py`: delete the constant, lazy-import the resolver, refresh three docstrings — *why*: AC2 + sandbox must bind the real root.
3. `remove_worktree.py`, `worktree_baseline.py`, `integration.py` one-line swaps + text — *why*: G1, no inline spelling.
4. Update the two test files; run validation.

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    flow_type: Literal\["feature", "hotfix", "non-sdd"\]' ...worktree_status.py)
# REPLACE line 70 (and the two comment lines 68-69 above it) with:
    #: ``"non-sdd"`` marks a worktree under the resolved worktree root whose branch is not an SDD branch;
    #: ``"legacy"`` marks one still registered under ``.claude/worktrees/`` (FEAT-802 — move it). Both are
    #: health only, no tasks, never ready_for_done (FEAT-582 §8).
    flow_type: Literal["feature", "hotfix", "non-sdd", "legacy"]
```
```python
# In discover_worktree_reports, after the pool-sub-worktree `continue` and BEFORE `parsed = _parse_branch(branch)`:
        if _is_under_worktree_root(wt_path, legacy_root):
            # FILL IN: append WorktreeReport(feature_slug=branch, feature_id=None, flow_type="legacy",
            #          worktree_path=str(wt_path), branch=branch, base_branch="dev",
            #          health=_check_health(wt_path, "dev"), tasks=[], index_found=False, ready_for_done=False)
            #          then `continue` — bounded by AC8 / test_worktree_status_legacy_entry
            continue
```
Define `legacy_root = (repo_root / LEGACY_WORKTREE_ROOT).resolve()` next to `worktree_root_path`, and
extend the import to `from parrot.sdd.config import LEGACY_WORKTREE_ROOT, worktree_root`. Legacy
porcelain entries come from git, not from the orphan scan, so they need no extra discovery.

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'WORKTREE_ADMIN_DIR = Path(".claude") / "worktrees"' ...worktree_environment.py)
# DELETE line 139.
# occurrences: 1 (verified: grep -c '    admin_dir = (primary / WORKTREE_ADMIN_DIR).resolve()' ...)
# REPLACE line 177 with:
    from parrot.sdd.config import worktree_root  # lazy: the hook path stays stdlib-only until needed

    admin_dir = worktree_root(primary).resolve()
```
Docstrings: line 38 "the primary checkout's ``.claude/worktrees``" → "the primary checkout's worktree root";
line 157 "under the primary checkout's ``.claude/worktrees``" → "under the primary checkout's resolved worktree root (default ``.parrot/worktrees``)";
line 233 "(``.claude/worktrees``, so ..." → "(the resolved worktree root, so ...".

### `remove_worktree.py` / `worktree_baseline.py` / `integration.py` (MODIFY)
```python
# remove_worktree.py — occurrences: 1 each
#   line 220:  worktree_dir = worktree_root(_root())          (add `from parrot.sdd.config import worktree_root`)
#   line 374:  print(f"No orphan directories under {worktree_root(_root())}/.")
#   line 4:    "Two kinds of leftovers accumulate under the resolved worktree root (default ``.parrot/worktrees/``):"
# worktree_baseline.py — occurrences: 1 each
#   line 60:   return worktree_root(main_root)                 (add the same import)
#   line 54:   """``<main checkout>/<worktree root>`` (default ``.parrot/worktrees``) — writable from inside the SDD sandbox and persistent.
#   line 101:  help="Parent directory for the checkout (default: the resolved worktree root)."
# integration.py — occurrences: 1
#   line 376:  tmp = worktree_root(primary) / f"_ledger-outbox-{uuid.uuid4()}"   (add the import beside line 19-30 imports)
```
**Why**: G1 — one resolver; `tmp.parent.mkdir(parents=True, exist_ok=True)` on the next line already creates the root.

### FILL IN checklist
- [ ] legacy report construction in `discover_worktree_reports`; bounded by AC8.
- [ ] `test_worktree_status.py::test_worktree_status_legacy_entry` — fake porcelain with an entry under `tmp_path/.claude/worktrees/feat-FEAT-9-x` → one report, `flow_type == "legacy"`, `ready_for_done is False`.
- [ ] `test_worktree_status.py::test_worktree_status_scans_resolved_root` — orphan dir under `tmp_path/.parrot/worktrees` found with env cleared.
- [ ] `test_worktree_environment.py` — fixture builds `main/.parrot/worktrees/feat-x`; docstring says the resolved root; assertion uses `main/".parrot"/"worktrees"`; add a case where `WORKTREE_BASE_PATH` points at a custom in-repo root.

---

## Acceptance Criteria

- [ ] Spec AC2 (environment half): `worktree_environment.WORKTREE_ADMIN_DIR` raises `AttributeError`.
- [ ] Spec AC8: a legacy entry is listed as `flow_type: legacy` with `ready_for_done: false`.
- [ ] Spec AC12: none of these modules reads `.claude/worktrees` to find a worktree (only `worktree_status` classifies legacy rows).
- [ ] The sandbox allow-list contains `<primary>/.parrot/worktrees` for a feature worktree.
- [ ] `ruff check` clean on the five source files.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_worktree_status.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_worktree_status.py — append
def test_worktree_status_legacy_entry(tmp_path, monkeypatch): ...
def test_worktree_status_scans_resolved_root(tmp_path, monkeypatch): ...
```

---

## Agent Instructions

1. Work in the feature worktree; TASK-5176 must be `done`.
2. Verify anchors with `grep -c`, mark `in-progress`, implement, run the Validation Commands with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src:<worktree>`.
3. Commit only the listed files; `parrot sdd task close TASK-5177 worktree-root-under-parrot verified`; fill the Completion Note.

---

## Completion Note

Implemented by seat gpt-5.6-terra (codex), 1 attempt, 480s, merged cleanly.

**Completed by**: sdd-worker (orchestrator)
**Date**: 2026-11-05
**Notes**: Merge-tier: 173 passed, 1 pre-existing failure (test_no_command_hand_rolls_a_worktree[sdd-worker.md], also red on origin/dev). Closed via `parrot sdd task close`; finalize unavailable (coder_record_review tool error). feedback NOT recorded.

**Deviations from spec**:
