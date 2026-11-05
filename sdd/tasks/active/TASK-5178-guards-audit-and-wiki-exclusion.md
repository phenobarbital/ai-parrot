# TASK-5178: Dangerous-action guards, audit regex, wiki exclusion and e2e docstring

**Feature**: FEAT-802 — Worktree Root Under `.parrot/`
**Spec**: `sdd/specs/worktree-root-under-parrot.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5174
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (regex/text half). The `rm -rf` guard (Python + its `.sh` twin), the
merge/pull live-worker warning, the asset audit's `monorepo-path` rule, the wiki build exclusion
list and one e2e docstring still name `.claude/worktrees`. The `rm -rf` guards protect BOTH roots
on purpose: the cut tells people to move the legacy tree, never to delete it (spec §3 M3 note).

---

## Scope

- `dangerous_actions.py`: `_RM_CRITICAL` and `_WIN_CRITICAL` match `.claude/worktrees` OR `.parrot/worktrees`
  (Windows separators too); deny text at line 275 names both; merge/pull guard (line 316) tests
  `worktree_root(root).is_dir()` via a lazy, guarded import (same style as line 83).
- `.claude/hooks/dangerous-actions-blocker.sh`: same two-root `rm` regex (line 172) and message (173);
  merge/pull test (231) checks the resolved root — `[[ -d "${WORKTREE_BASE_PATH:-.parrot/worktrees}" ]]`.
- `audit.py:70`: `MONOREPO_PATH_RE` flags `.parrot/worktrees/` instead of `.claude/worktrees/`.
- `scripts/build_llm_wiki.py:133`: exclusion `".parrot/worktrees"`.
- `e2e/supervisor.py:858`: docstring path → `.parrot/worktrees/...`.
- Tests: `test_audit.py:27` and a new `test_dangerous_rm_both_roots` in `test_dangerous_actions.py`.

**NOT in scope**: the guard's protected branches; any other dangerous-action rule.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` | MODIFY | two-root rm guards; resolver-based merge/pull check |
| `.claude/hooks/dangerous-actions-blocker.sh` | MODIFY | shell twin of the same rules |
| `packages/ai-parrot/src/parrot/sdd/audit.py` | MODIFY | `monorepo-path` regex |
| `scripts/build_llm_wiki.py` | MODIFY | exclusion list |
| `packages/ai-parrot-server/src/parrot/e2e/supervisor.py` | MODIFY | docstring only |
| `packages/ai-parrot/tests/sdd/test_audit.py` | MODIFY | new path flagged, legacy not |
| `packages/ai-parrot/tests/sdd/test_dangerous_actions.py` | MODIFY | both roots denied |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.scripts.dangerous_actions import evaluate, protected_branches   # verified: tests/sdd/test_dangerous_actions.py:14
from parrot.sdd.config import worktree_root                                     # created by TASK-5174 — import lazily inside the function
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py
            from parrot.sdd.config import load_sdd_config  # lazy + guarded   # line 83 (inside try/except Exception, line 87)
_RM_CRITICAL = re.compile(                                                     # lines 125-127
    r"rm\s+(-[a-zA-Z]+\s+)*-?[a-zA-Z]*[rR][a-zA-Z]*\s+[^;&|]*(\.venv|\.git(/|\s|$)|\.claude/worktrees)"
)
_WIN_CRITICAL = re.compile(r"(\.venv|\.git([\\/]|\s|$)|\.claude[\\/]worktrees)", re.IGNORECASE)   # line 128
            "Recursive delete of a repo-critical path (.venv, .git, .claude/worktrees).",       # line 275
    if re.search(r"git\s+(merge|pull)\b", scan) and root is not None and (root / ".claude" / "worktrees").is_dir():  # line 316
def evaluate(payload: dict[str, Any], *, root: Path | None) -> Verdict:       # line 387

# .claude/hooks/dangerous-actions-blocker.sh
    if echo "$SCAN" | grep -qE 'rm\s+(-[a-zA-Z]+\s+)*-?[a-zA-Z]*[rR][a-zA-Z]*\s+[^;&|]*(\.venv|packages/?\s*$|\.git(/|\s|$)|\.claude/worktrees)'; then   # line 172
        block "Recursive delete of a repo-critical path (.venv, packages/, .git, .claude/worktrees)." \   # line 173
    if echo "$SCAN" | grep -qE 'git\s+(merge|pull)\b' && [[ -d .claude/worktrees ]]; then   # line 231

# packages/ai-parrot/src/parrot/sdd/audit.py
MONOREPO_PATH_RE = re.compile(r"\bpackages/ai-parrot\w*|\.claude/worktrees/")   # line 70

# scripts/build_llm_wiki.py
    ".claude/worktrees",                                                         # line 133 (exclusion tuple)

# packages/ai-parrot-server/src/parrot/e2e/supervisor.py
        (``.claude/worktrees/<feature>--TASK-<id>-<uuid>/``) routinely           # line 858

# packages/ai-parrot/tests/sdd/test_dangerous_actions.py
def _bash(cmd: str) -> dict:                                                     # line 17
DENIED = [...]                                                                   # line 26 — parametrized at line 91; assert verdict.decision == "deny"
# packages/ai-parrot/tests/sdd/test_audit.py
        ("cd .claude/worktrees/feat-FEAT-1-x", "monorepo-path"),                 # line 27
```

### Does NOT Exist
- ~~`manifest.json` entries for `.claude/hooks/dangerous-actions-blocker.sh`~~ — the shell hook is repo-local; nothing to regenerate for it.
- ~~`Verdict.kind`~~ — the field is `decision` ("allow" | "warn" | "deny").

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py", "action": "MODIFY"},
    {"path": ".claude/hooks/dangerous-actions-blocker.sh", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/audit.py", "action": "MODIFY"},
    {"path": "scripts/build_llm_wiki.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/e2e/supervisor.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_audit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_dangerous_actions.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py#evaluate"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Edit the Python guard and its `.sh` twin together (they must agree; the twin keeps its extra `packages/` alternative).
- `.claude/` files may be ignored by a global rule here — stage the hook with `git add -f .claude/hooks/dangerous-actions-blocker.sh` if a plain `git add` refuses.
- The merge/pull check must never raise from the hook: wrap the lazy import + `worktree_root(root).is_dir()` in `try/except Exception` and fall back to `(root / ".parrot" / "worktrees").is_dir()`.
- The audit rule now flags `.parrot/worktrees/` as a monorepo-specific path in shipped assets; TASK-5180..5183 must therefore keep literal `.parrot/worktrees/` out of executable snippets in shipped assets (they call the root CLI instead) — check `parrot.sdd.audit` findings in TASK-5183.

---

## Implementation Blueprint

### Steps (in order)
1. Update both Python regexes and the deny text — *why*: protect both roots (spec §3 M3).
2. Replace the merge/pull directory test with the guarded resolver call — *why*: G1; a custom root must still trigger the warning.
3. Mirror both changes in the `.sh` hook — *why*: twins must agree.
4. One-line updates in `audit.py`, `build_llm_wiki.py`, `supervisor.py`.
5. Update `test_audit.py`, add `test_dangerous_rm_both_roots`; run validation.

### `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_WIN_CRITICAL = re.compile' ...dangerous_actions.py)
# REPLACE lines 125-128 with:
_RM_CRITICAL = re.compile(
    r"rm\s+(-[a-zA-Z]+\s+)*-?[a-zA-Z]*[rR][a-zA-Z]*\s+[^;&|]*(\.venv|\.git(/|\s|$)|\.(claude|parrot)/worktrees)"
)
_WIN_CRITICAL = re.compile(r"(\.venv|\.git([\\/]|\s|$)|\.(claude|parrot)[\\/]worktrees)", re.IGNORECASE)
```
```python
# line 275 → "Recursive delete of a repo-critical path (.venv, .git, .parrot/worktrees, .claude/worktrees).",
# occurrences: 1 (verified: grep -c '(root / ".claude" / "worktrees").is_dir()' ...dangerous_actions.py)
# REPLACE line 316 with:
    if re.search(r"git\s+(merge|pull)\b", scan) and root is not None and _worktrees_dir_exists(root):
```
```python
# ADD near the other module-level helpers (above `def evaluate`):
def _worktrees_dir_exists(root: Path) -> bool:
    """True when the repository's resolved worktree root exists (FEAT-802); never raises."""
    try:
        from parrot.sdd.config import worktree_root  # lazy + guarded, like load_sdd_config above

        return worktree_root(root).is_dir()
    except Exception:  # noqa: BLE001 — a hook must not fail on an optional capability
        return (root / ".parrot" / "worktrees").is_dir()
```

### `.claude/hooks/dangerous-actions-blocker.sh` (MODIFY)
```bash
# line 172: replace `|\.claude/worktrees)'` with `|\.(claude|parrot)/worktrees)'`
# line 173: block "Recursive delete of a repo-critical path (.venv, packages/, .git, .parrot/worktrees, .claude/worktrees)." \
# line 231:
    if echo "$SCAN" | grep -qE 'git\s+(merge|pull)\b' && [[ -d "${WORKTREE_BASE_PATH:-.parrot/worktrees}" ]]; then
```

### `audit.py` / `build_llm_wiki.py` / `supervisor.py` (MODIFY)
```python
# audit.py:70      MONOREPO_PATH_RE = re.compile(r"\bpackages/ai-parrot\w*|\.parrot/worktrees/")
# build_llm_wiki.py:133      ".parrot/worktrees",
# supervisor.py:858          (``.parrot/worktrees/<feature>--TASK-<id>-<uuid>/``) routinely
```

### FILL IN checklist
- [ ] `test_audit.py:27` → `("cd .parrot/worktrees/feat-FEAT-1-x", "monorepo-path")`; add a negative case asserting `cd .claude/worktrees/x` yields no `monorepo-path` finding (use the module's existing negative-case pattern).
- [ ] `test_dangerous_actions.py::test_dangerous_rm_both_roots` — `rm -rf .claude/worktrees/x` and `rm -rf .parrot/worktrees/x` both `deny`; `Remove-Item -Recurse .parrot\\worktrees\\x` denied.
- [ ] Confirm by running the `.sh` hook manually on both `rm` commands (it reads JSON on stdin like the Python hook) and record the result in the Completion Note.

---

## Acceptance Criteria

- [ ] `rm -rf .claude/worktrees/x` and `rm -rf .parrot/worktrees/x` are denied by the Python guard and the shell hook.
- [ ] The merge/pull live-worker check follows the resolved root and never raises.
- [ ] `audit` flags `.parrot/worktrees/` as `monorepo-path`; `.claude/worktrees/` is no longer flagged.
- [ ] Only the regexes listed in spec AC1 still name `.claude/worktrees` in these files.
- [ ] `ruff check` clean on the Python files; `bash -n .claude/hooks/dangerous-actions-blocker.sh` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_audit.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_dangerous_actions.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_dangerous_actions.py — append
@pytest.mark.parametrize("cmd", ["rm -rf .claude/worktrees/x", "rm -rf .parrot/worktrees/x"])
def test_dangerous_rm_both_roots(cmd: str, tmp_path: Path) -> None:
    assert evaluate(_bash(cmd), root=tmp_path).decision == "deny", cmd
```

---

## Agent Instructions

1. Work in the feature worktree; TASK-5174 must be `done`.
2. Verify anchors, mark `in-progress`, implement, run the Validation Commands with an absolute `PYTHONPATH=<worktree>/packages/ai-parrot/src`.
3. Commit only the listed files (`git add -f` for the `.claude/` hook if needed); `parrot sdd task close TASK-5178 worktree-root-under-parrot verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
