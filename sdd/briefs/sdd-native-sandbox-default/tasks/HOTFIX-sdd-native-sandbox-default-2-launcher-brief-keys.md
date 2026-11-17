# HOTFIX-sdd-native-sandbox-default-2: `parrot sdd launch worker` accepts brief keys

**Feature**: sdd-native-sandbox-default — native sandbox by default, launcher-only guidance
**Spec**: `sdd/briefs/sdd-native-sandbox-default.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`/sdd-brief` hands off with a direct `claude --agent sdd-worker` launch because the launcher only
resolves feature indexes under `sdd/tasks/index/*.json`. A brief's index lives in its own worktree
(`sdd/briefs/<slug>.index.json`, committed on the `fix-*` / `hotfix-*` branch, never on `dev`).
Task 3 can only switch `/sdd-brief` to the launcher once the launcher can launch a brief.

## Scope

In `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py`:

- When `resolve_feature` finds no match among the feature indexes, look for a brief. Walk
  `git worktree list --porcelain` from the primary checkout, and for each worktree check whether
  `sdd/briefs/*.index.json` has a header with `type == "brief"` whose `feature` (slug) or
  `feature_id` (`BRIEF-<slug>`) matches the key, case-insensitively. A brief's KEY equals its slug
  for text sources; also match the brief frontmatter `key:` when it differs (Jira or ledger keys).
  Exactly one match is required; otherwise keep the existing `LaunchError(2, "could not uniquely
  resolve …")`.
- Represent the result so that `launch()` reuses the **existing** brief worktree and never calls
  `ensure_feature_worktree` for it. For example, add an optional `worktree: str | None = None`
  field to `FeatureRef`, or a `kind` field, whichever keeps the dataclass frozen and the feature path
  unchanged.
- The initial prompt for a brief is `run <slug>` (how brief workers are started today, for example
  `run sdd-worker-gh-only-sandbox`). Features keep `run <FEAT-ID>`. Apply the same rule in the tmux
  child path (`--in-session`, `main()` at :497) so both paths send the same prompt.
- tmux session naming (`tmux_session_name`) must accept the brief id and slug without collisions.
- `--no-upstream` / `prepare_upstream` behave the same for a brief worktree.

Tests in `packages/ai-parrot/tests/sdd/test_sdd_launch.py`, following the existing fixtures
(`test_resolve_feature_*`, `test_launch_non_tmux_passes_worktree_and_worker_prompt`):

- A brief key (slug, `BRIEF-<slug>`, frontmatter key) resolves to its worktree.
- An ambiguous or missing key raises `LaunchError` with exit code 2.
- The non-tmux launch passes the brief worktree as `cwd` with the prompt `run <slug>`, and never
  calls `ensure_feature_worktree`.
- Feature resolution behavior is unchanged.

**NOT in scope**: changing what `sdd-worker` does with a brief; hook changes (task 1); command and
doc text (task 3).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | brief resolution, existing-worktree reuse, brief prompt |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | brief-key tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev, 2026-11-04)
```
packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:29   @dataclass(frozen=True)  class FeatureRef: feature_id, slug, spec, index
packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:104  def resolve_feature(primary: Path, key: str) -> FeatureRef:
packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:128  def ensure_feature_worktree(primary: Path, ref: FeatureRef) -> Path:
packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:204  def tmux_session_name(feature_id: str, slug: str) -> str:
packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:366  def launch(
packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:427              initial_prompt=f"run {ref.feature_id}",
packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:497  def main(argv: Sequence[str] | None = None) -> int:
packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py:517          initial_prompt=f"run {args.in_session}",   (tmux child path)
packages/ai-parrot/src/parrot/sdd/launch_cli.py:27                    def worker(  (click command, passes FEATURE to feature_launcher.launch)
packages/ai-parrot/tests/sdd/test_sdd_launch.py:58                    def test_resolve_feature_is_case_insensitive_and_skips_orphans(tmp_path: Path) -> None:
packages/ai-parrot/tests/sdd/test_sdd_launch.py:109                   def test_launch_non_tmux_passes_worktree_and_worker_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
```

### Brief index header shape (from `sdd/briefs/sdd-worker-gh-only-sandbox.index.json`)
```json
{"feature": "<slug>", "feature_id": "BRIEF-<slug>", "spec": "sdd/briefs/<slug>.brief.md",
 "type": "brief", "base_branch": "dev", "tasks": [...]}
```

### Does NOT Exist
- No brief lookup exists anywhere in `feature_launcher.py` today.
- `feature_launcher.py` runs as a script in the tmux child (`python -S`, no site-packages): any new
  helper must stay stdlib-only, like the rest of the module.

---

## Acceptance Criteria

- [ ] `parrot sdd launch worker <brief-slug>` (and `BRIEF-<slug>`, and the frontmatter key) launches
      the sandboxed worker in the existing brief worktree with the prompt `run <slug>`.
- [ ] The tmux and non-tmux paths send the same prompt.
- [ ] Feature launches are unchanged, and existing tests pass.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`

## Agent Instructions

Read the brief first. Touch only the listed files. Never create a worktree for a brief: it must
already exist (`/sdd-brief` provisions it).

## Completion Note

`feature_launcher.py`: `FeatureRef` gained `worktree: str | None = None` plus `is_brief`/`prompt_id`
(slug for a brief, feature id otherwise). `resolve_feature` falls back to `_resolve_briefs`, which walks
`git worktree list --porcelain` and matches `type == "brief"` indexes by slug, `BRIEF-<slug>` or the
frontmatter `key:` (case-insensitive); exactly one match or `LaunchError(2)`. `launch()` reuses the brief
worktree (never `ensure_feature_worktree`) and uses `ref.prompt_id` in both the direct and tmux-child
paths. Validation: test_sdd_launch.py → 57 passed.
