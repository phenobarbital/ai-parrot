# TASK-4874 — Closeout hooks Python hardening

- **Feature**: fixgroup-5a875150e625
- **Feature ID**: FEAT-766
- **Spec**: sdd/specs/fixgroup-5a875150e625.spec.md
- **Status**: pending
- **Priority**: medium
- **Estimated effort**: M
- **Depends-on**: —
- **Assigned-to**: agent
- **Discovered-from**: `issue:1ac97711d2bd`

## Context

FEAT-764 closeout hooks landed with several code-level follow-ups: path
traversal in artifact paths, non-atomic persist, no pre_pr short-circuit,
duplicated helper class, missing docstrings, assert stripped under -O, and
a dead parameter.

## Scope

### In scope

1. Validate `feat_id` in `_outcome_path` — reject `..`, `/`, any character
   outside `[A-Za-z0-9._-]`.
2. Reject `..` and absolute patterns in `_glob_artifacts`.
3. Make `_persist` use tempfile + `os.replace` for atomicity.
4. Short-circuit `run_event` after a blocking `pre_pr` failure.
5. Move `_Defaulting` to `closeout_hooks_config.py`; import in both consumers.
6. Add one-line docstrings to `_result`, `_push_ntfy`, `_push_gotify`.
7. Replace module-level `assert` with a `RuntimeError` check.
8. Remove dead `root` parameter from `run_event`; update the sole caller in `main()`.

### NOT in scope

- Schema/model changes to `HookSpec` or `HookContext`.
- New builtins or events.
- Workflow twin updates (TASK-4875).

## Files to Modify

- `scripts/sdd/closeout_hooks_config.py`
- `scripts/sdd/run_closeout_hooks.py`
- `scripts/sdd/closeout_builtins.py`
- `tests/sdd_scripts/test_run_closeout_hooks.py`

## Codebase Contract

### Verified Imports
- `from scripts.sdd.closeout_builtins import run_builtin` — run_closeout_hooks.py:16
- `from scripts.sdd.closeout_hooks_config import (EVENTS, HookContext, HookKind, HookResult, HookSpec, HooksConfig, HooksConfigError, load_hooks)` — run_closeout_hooks.py:17–26
- `from scripts.sdd.closeout_hooks_config import HookContext, HookKind, HookResult, HookSpec, PUSH_PROVIDERS` — closeout_builtins.py:17

### Existing Signatures
- `def run_event(event: str, ctx: HookContext, cfg: HooksConfig, root: Path, ctx_path: Path) -> EventOutcome` — run_closeout_hooks.py:152
- `def record(event: str, feat_id: str, name: str, status: str, summary: str, root: Path) -> EventOutcome` — run_closeout_hooks.py:208
- `def _persist(outcome: EventOutcome) -> None` — run_closeout_hooks.py:81
- `def _outcome_path(feat_id: str, event: str) -> Path` — run_closeout_hooks.py:56
- `def _glob_artifacts(hook_dir: Path, pattern: str | None) -> list[str]` — run_closeout_hooks.py:74
- `class _Defaulting(dict[str, Any])` — run_closeout_hooks.py:42 and closeout_builtins.py:24
- `_PUSH: dict[str, Callable[..., tuple[str, str]]] = {"ntfy": _push_ntfy, "gotify": _push_gotify}` — closeout_builtins.py:249
- `assert set(_PUSH) == set(PUSH_PROVIDERS)` — closeout_builtins.py:250
- `def main(argv: Sequence[str] | None = None) -> int` — run_closeout_hooks.py:261
- sole call: `outcome = run_event(args.event, context, load_hooks(args.root), args.root, args.context)` — run_closeout_hooks.py:293

### Does NOT Exist
- `_FEAT_ID_RE` in closeout_hooks_config.py
- `_Defaulting` exported from closeout_hooks_config.py

## Acceptance Criteria

- AC-1: `_outcome_path("../../etc", "pre_pr")` raises `ValueError`.
- AC-2: `_glob_artifacts(hook_dir, "../*.py")` returns `[]` (rejected).
- AC-3: `_persist` uses `tempfile.NamedTemporaryFile` + `os.replace`.
- AC-4: After a blocking `pre_pr` failure, later hooks are skipped.
- AC-5: Only one `_Defaulting` definition exists (in `closeout_hooks_config.py`).
- AC-6: `_result`, `_push_ntfy`, `_push_gotify` have docstrings.
- AC-7: `assert set(_PUSH) == ...` replaced with `if set(_PUSH) != ...: raise RuntimeError(...)`.
- AC-8: `run_event` signature has no `root` parameter; `main()` updated.
- AC-9: All existing tests pass; new tests cover AC-1, AC-2, AC-4.

## Validation Commands

```bash
PYTHONPATH=. pytest tests/sdd_scripts/test_run_closeout_hooks.py tests/sdd_scripts/test_closeout_hooks_config.py tests/sdd_scripts/test_closeout_builtins.py -x -q
```

## Completion Note

*(filled on close)*
