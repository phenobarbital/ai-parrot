# TASK-5119: `launch worker --tmux` session name must not collide across repositories

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.12 — ledger fixes)
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5118, TASK-5101
**Assigned-to**: unassigned
**Discovered-from**: `issue:a94869a0df2b`

---

## Context

`tmux_session_name()` returns `sdd-<FEAT-ID>`. The tmux server is per user and shared by every repository, and
FEAT ids restart at `FEAT-1` in each repository, so `parrot sdd launch worker FEAT-2 --tmux` in repo B finds repo
A's live `sdd-FEAT-2` session and attaches to it — or, without `--tmux`, refuses with "a worker for FEAT-2 already
runs". Found 2026-11-03 running FEAT-1/FEAT-2 in the sandbox project next to other repositories.

Agreed fix: the session name is `sdd-<feature id lower-cased>-<spec slug>` (e.g. `sdd-feat-2-simple-agent`). It
stays deterministic per feature, so reattach and the duplicate-worker guard keep working. No random suffix: every
relaunch would start a second worker on the same worktree.

---

## Scope

- `tmux_session_name(feature_id, slug)` → `sdd-<feature_id>-<slug>`, lower-cased, every run of characters outside
  `[a-z0-9_-]` (tmux rejects `.` and `:`) replaced by `-`, the slug truncated so the name is at most 64 characters.
- `legacy_tmux_session_name(feature_id)` → `sdd-<FEAT-ID>` (the pre-fix name).
- Transition in `launch()`: when no session has the new name but a live legacy session exists whose
  `#{session_path}` lies inside this repository's primary checkout, attach/refuse against the legacy session instead
  of launching a duplicate. A legacy session from another repository is ignored.
- Update `tests/sdd/test_sdd_launch.py` for the new name and add tests for the name rules and the transition.
- Update the session name in `docs/dev_loop/claude-native-sandbox.md`.

**NOT in scope**: renaming or killing existing sessions; `launch brief|fix` (no tmux).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | new name, legacy fallback |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | new name + transition tests |
| `docs/dev_loop/claude-native-sandbox.md` | MODIFY | session name in the command table |

---

## Codebase Contract (Anti-Hallucination)

Verified on `feat-FEAT-633-parrot-installer` at `ca87c1ac4e` (2026-11-03).

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py
@dataclass(frozen=True)
class FeatureRef:  # feature_id: str, slug: str, spec: str, index: str          # line 29
def resolve_primary_checkout(start: Path) -> Path
def resolve_feature(primary: Path, key: str) -> FeatureRef                     # line 103
def tmux_session_name(feature_id: str) -> str                                  # line 199
def tmux_session_exists(name: str) -> bool                                     # line 204
def launch(key, *, tmux, detach, sandbox, allowed_domains, no_upstream, claude_args, base_env=None) -> int  # 313
```

---

## Acceptance Criteria

- [ ] `tmux_session_name("FEAT-2", "simple-agent") == "sdd-feat-2-simple-agent"`; `.`/`:` never appear; length ≤ 64.
- [ ] A new tmux worker is created as `sdd-feat-768-<slug>`; attach/refuse use the same name.
- [ ] A live legacy `sdd-FEAT-768` session whose path is inside this checkout is reattached/refused; one whose path
      is in another repository is ignored and a new worker is launched.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`

## Agent Instructions

Work in `feat-FEAT-633-parrot-installer`; run tests with `PYTHONPATH=packages/ai-parrot/src`; stage only the files
above; close with `parrot sdd task close TASK-5119 parrot-installer verified`.

---

## Completion Note
**Completed by**: Claude Opus 5.5 (/sdd-fix, sequential)
**Date**: 2026-11-03
**Notes**: `tmux_session_name(feature_id, slug)` → `sdd-<feat-id>-<slug>`, lower-cased, runs outside `[a-z0-9_-]` → `-`, slug truncated to keep ≤ 64 chars. `_existing_session()` falls back to a live legacy `sdd-<FEAT-ID>` only when its `#{session_path}` is inside the primary checkout (feature worktrees live under it), so another repo's session is never attached; no `display-message` call when no legacy session exists. 6 new tests (name rules, truncation, legacy refuse/reattach in this repo, other repo ignored); mutation-checked (dropping the path guard or the fallback fails them). test_sdd_launch.py 47 passed; ruff clean. The FEAT-768 spec text (`sdd-<FEAT-ID>`) is historical and left as is; docs table updated.
