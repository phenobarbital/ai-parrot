# TASK-5694: Anchor the hook's experience plane to trusted Git metadata

**Feature**: FEAT-887 — SDD Experience Memory (`experience.pitfall`)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5693, TASK-5588, TASK-5596
**Assigned-to**: unassigned
**Discovered-from**: `issue:33ab30fb1190`

---

## Context

Deferred review finding on FEAT-887. `fastpath.resolve_plane_dir` walks up from the hook payload's
`cwd` to the nearest `.git` marker and trusts whatever `gitdir:` it names, and `experience_hook.main`
never consults the roots the launcher froze in `PARROT_SDD_SANDBOX_ROOTS`. A sandboxed worker can
create `sub/.git` containing `gitdir: /some/dir/.git`; the host-side hook (which runs outside the
sandbox) then `mkdir`s and appends events, session and lock files under
`/some/dir/.parrot/experience/` — a write primitive outside the sandbox's writable set.
`native_claude_sandbox._frozen_roots` already guards the other hooks against exactly this forged
marker (its docstring: "re-deriving the policy roots from it on every hook call would let a forged
marker steer the hook").

---

## Scope

- In `experience_hook.main`: when `PARROT_SDD_SANDBOX_ROOTS` holds three non-empty roots and the
  payload `cwd` lies inside the frozen worktree root, the plane is `<frozen common git dir>.parent /
  .parrot/experience` — never re-derived from the writable marker. (Parsed with stdlib only; the hook
  must not import `native_claude_sandbox`.)
- In `fastpath.resolve_plane_dir` (no frozen roots): a `.git` **file** marker is accepted only when
  it names a linked-worktree admin directory that git itself would accept — the admin dir has a
  `commondir`, lives at `<common>/worktrees/<name>`, `<common>` contains a regular `HEAD`, and the
  admin dir's `gitdir` back-link names this marker file. Anything else (a marker naming a bare
  common dir, a missing back-link, a submodule-style marker) resolves to `None` (the hook fails open).
- Tests: a forged marker never yields a plane outside its repository; a real linked worktree created
  with `git worktree add` (outside `.parrot/worktrees/`) resolves to the primary plane
  (`test_worktree_uses_primary_plane`); frozen roots win over a forged marker inside the frozen root.

**NOT in scope**: the service/CLI plane resolution (`find_shared_root`), any change to
`native_claude_sandbox.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py` | MODIFY | validated linked-worktree resolution; frozen-roots helper |
| `packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py` | MODIFY | use frozen roots when the launcher pinned them |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py` | MODIFY | forged-marker and linked-worktree tests |
| `packages/ai-parrot/tests/sdd/test_experience_hook.py` | MODIFY | frozen-roots test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.experience.fastpath import resolve_plane_dir, EXPERIENCE_DIR  # fastpath.py:253, 19
```

### Existing Signatures to Use
```python
# fastpath.py:253
def resolve_plane_dir(cwd: Path) -> Path | None
# fastpath.py:630 / 656
def _git_dir_from_file(marker: Path, root: Path) -> Path | None
def _common_git_dir(git_dir: Path) -> Path | None
# experience_hook.py:39 — resolves the plane at line 56
def main(argv: Sequence[str] | None = None) -> int
# sdd/scripts/native_claude_sandbox.py:45, 180 — the pattern (do not import it from the hook)
ROOTS_ENV = "PARROT_SDD_SANDBOX_ROOTS"  # "root:common_git_dir:primary", os.pathsep-joined
def _frozen_roots(cwd: Path) -> tuple[Path, Path, Path] | None
```

### Does NOT Exist
- `fastpath` has no frozen-roots reader today; add one (stdlib only).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_experience_hook.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py#resolve_plane_dir",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py#_git_dir_from_file",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py#_common_git_dir",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/experience_hook.py#main"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `fastpath.py` and `experience_hook.py` are protected control files for sandboxed workers — this
  task is implemented from the host.
- Stdlib only; never raise; unresolvable → `None`.
- The primary checkout (`.git` directory) keeps resolving exactly as today.

---

## Implementation Blueprint

### Steps (in order)
1. `fastpath.frozen_plane_dir(cwd, env)` → plane from `PARROT_SDD_SANDBOX_ROOTS` when `cwd` is inside the frozen root.
2. `resolve_plane_dir`: for a `.git` file, validate admin dir ↔ common dir ↔ back-link before trusting it.
3. `experience_hook.main`: try the frozen plane first, then `resolve_plane_dir`.

### FILL IN checklist
- [ ] back-link compares canonical paths
- [ ] `HEAD` must be a regular file in the common dir

---

## Acceptance Criteria

- [ ] A forged `.git` file naming another repository's common dir resolves to `None`.
- [ ] A genuine linked worktree resolves to the primary checkout's plane.
- [ ] With frozen roots set, a forged marker inside the frozen root cannot change the plane.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_fastpath.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_experience_hook.py -q`

---

## Test Specification

```python
def test_resolve_plane_dir_rejects_forged_gitdir_marker(tmp_path): ...
def test_worktree_uses_primary_plane(tmp_path): ...
def test_hook_prefers_frozen_roots_over_forged_marker(tmp_path, monkeypatch): ...
```

---

## Agent Instructions

Follow `docs/sdd/WORKFLOW.md` § "Implementing a task by hand" inside
`.parrot/worktrees/feat-FEAT-887-sdd-experience-memory`.

---

## Completion Note


- Task: TASK-5694
- Feature: sdd-experience-memory
- Implementation SHA: b89c139d078e33cd8dc2e879e6d7cb554bb2a941
- Closed at (UTC): 2026-11-16T01:04:57+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 2 |
| fix_commits | 0 |
| closed_from | host finalize; the sandboxed worker could not run finalize (navconfig log directory not writable) |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 478s · Tokens: n/a |
| task_commits | 0c58902024 deliverable, merged by b89c139d07 |
| validation | task tier passed; merge tier passed (0 failures) |
