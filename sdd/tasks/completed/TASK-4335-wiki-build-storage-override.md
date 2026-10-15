# TASK-4335: Add run-scoped wiki build storage override

**Feature**: FEAT-672 - GitHubReviewer local clone + wikitoolkit graph
**Spec**: `sdd/specs/github-reviewer-local-repo-wiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement spec §3 M1 within the approved external-plane design. Add run-scoped wiki build storage override.
This task changes only the files below. No provider SDK calls or new dependencies.

## Scope

- Add the Click option and validate an absolute path before acquiring the writer lock — the lock must guard the external store, not the repository default.
- Set only the effective config storage_dir; guard both save_project_config and overlay generation with storage_dir is None — a run-scoped override must leave the scanned repository untouched.
- Keep all unflagged build behavior and existing callback callers compatible; test both fresh and preconfigured repositories with local fixtures.

**NOT in scope**: PR-head checkout, programmatic build API extraction, shared sidecars,
and changes belonging to other tasks. This task does not alter the spec.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Add run-scoped wiki build storage override |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli_build_storage_dir.py` | CREATE | Focused behavioral tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import click
from pathlib import Path
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import load_project_config, save_project_config
```

Third-party dependencies click, pydantic and pytest are declared in packages/ai-parrot/pyproject.toml. Standard-library imports need no dependency additions. Imports of feature-created symbols are provided by the explicitly listed prerequisites, not claimed to exist at planning time. Verify any additional implementation imports before use.


### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1560
def build(
    path_: str | None,
    name: str | None,
    backend: str | None,
    force: bool,
    no_git: bool,
    quiet: bool,
    no_export: bool,
    no_graph: bool,
    graph_kinds: str,
    vault_mode: bool | None,
    no_push: bool,
) -> None:
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:748
    def storage_path(self, root: Path) -> Path:
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:982
def load_project_config(root: Path) -> WikiProjectConfig:
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1007
def save_project_config(root: Path, config: WikiProjectConfig) -> Path:
```

### Does NOT Exist

- `build_wiki()` or `run_build()` repository-scan API: use the CLI subprocess.
- `GitToolkit.checkout_ref()` and clone `sha=`/`ref=`: PR heads are out of scope.
- `WIKI_ROOT` or `PARROT_WIKI_ROOT`: pass explicit paths/config/store.
- `CodeStructuralToolkit(repository=...)`: constructor takes root/store/config.
- New repo_cache/repo_build symbols and seven GITHUB_REVIEW wiki settings are absent at planning time; rely on prerequisites before importing them.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_cli_build_storage_dir.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#build",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig.storage_path",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_project_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#save_project_config"
  ]
}
```

## Implementation Notes

Set the override before the first config.storage_path(root), including the lock path. Use ClickException with a clear absolute-path message. Do not change remote dispatch or refactor the build pipeline. Test the absence of wiki.json and env overlays as well as byte-for-byte preservation of existing config.

**Parallelism**: Independent CLI writer: only cli.py and its new focused test file; consumes no feature-created symbols.

## Implementation Blueprint

### Steps (in order)

1. Add the Click option and validate an absolute path before acquiring the writer lock — the lock must guard the external store, not the repository default.
2. Set only the effective config storage_dir; guard both save_project_config and overlay generation with storage_dir is None — a run-scoped override must leave the scanned repository untouched.
3. Keep all unflagged build behavior and existing callback callers compatible; test both fresh and preconfigured repositories with local fixtures.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

```python
# Anchor: def build(
# occurrences: 1 (verified with grep -Fxc; packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1560)
# Anchor:         save_project_config(root, base_config)
# occurrences: 1 (verified with grep -Fxc; packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:1724)
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py  (modifies cli.py:1554 option block,
#   cli.py:1560 callback, cli.py:1724 persistence)
@click.option(
    "--storage-dir",
    "storage_dir",
    default=None,
    help="Absolute directory for the wiki plane. Overrides the repo's "
         "storage_dir for THIS RUN ONLY and is never persisted.",
)
def build(
    path_: str | None,
    name: str | None,
    backend: str | None,
    force: bool,
    no_git: bool,
    quiet: bool,
    no_export: bool,
    no_graph: bool,
    graph_kinds: str,
    vault_mode: bool | None,
    no_push: bool,
    storage_dir: str | None,          # NEW
) -> None:
    """...

    When ``storage_dir`` is given it MUST be absolute (ClickException
    otherwise). The run then:
      * sets ``config.storage_dir`` to it before ``config.storage_path(root)``
        is read — storage_path() already returns an absolute value as-is
        (verified: project.py:748);
      * SKIPS ``save_project_config(root, base_config)`` (verified: cli.py:1724)
        and the env-overlay auto-generation that follows it, so the scanned
        repository's ``.parrot/`` is never written to;
      * is otherwise byte-identical to a run without the flag.
    """
# FILL IN: complete method bodies and wiring using the ordered steps and acceptance criteria.
```

**Why**: Preserve the spec signatures and small edit surface; the implementation details are bounded by the task acceptance criteria.

### `packages/ai-parrot/tests/knowledge/wiki/test_cli_build_storage_dir.py` (CREATE)

```python
"""Hermetic behavioral tests for FEAT-672."""
from pathlib import Path
import pytest

def test_build_storage_dir_overrides_plane_location(tmp_path: Path) -> None:
    """`--storage-dir` places the plane at the absolute path, not `<root>/.parrot/wiki`."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

def test_build_storage_dir_does_not_persist_config(tmp_path: Path) -> None:
    """After the run, the scanned repo has no new/changed `.parrot/wiki.json` and no env overlay."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

def test_build_storage_dir_rejects_relative_path(tmp_path: Path) -> None:
    """A relative value raises `ClickException`."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

def test_build_without_storage_dir_unchanged(tmp_path: Path) -> None:
    """Omitting the flag keeps today's persistence behaviour."""
    # FILL IN: arrange isolated fixtures and assert this observable behavior.

```

**Why**: These tests cover the spec failure modes without network, provider calls or shared conftest changes. Implement fixtures in this file.

### Mechanical insertion details

Before `with wiki_write_lock(config.storage_path(root))`, add:

```python
if storage_dir is not None:
    if not Path(storage_dir).is_absolute():
        raise click.ClickException("--storage-dir must be an absolute path")
    config.storage_dir = storage_dir
```

Wrap the existing `save_project_config` call in `if storage_dir is None:`;
change the following overlay condition to
`if storage_dir is None and effective.overlay_path is None:`. Leave its body intact.
This prevents a lock or configuration write in the clone before the override applies.

### FILL IN checklist

- [ ] Add the Click option and validate an absolute path before acquiring the writer lock — the lock must guard the external store, not the repository default.
- [ ] Set only the effective config storage_dir; guard both save_project_config and overlay generation with storage_dir is None — a run-scoped override must leave the scanned repository untouched.
- [ ] Keep all unflagged build behavior and existing callback callers compatible; test both fresh and preconfigured repositories with local fixtures.
- [ ] Replace all blueprint placeholders with complete typed, documented implementation and assertions; no unfinished placeholders in delivered source.

## Acceptance Criteria

The feature criteria below apply to this task’s declared scope; cross-module portions are completed by their owning tasks.

- [ ] AC-1: `wikitoolkit build --path <clone> --storage-dir <abs>` writes the plane at `<abs>` and leaves the scanned repository's `.parrot/` untouched (no `wiki.json` write, no overlay generation); omitting the flag is behaviourally unchanged.
- [ ] All task-local tests pass; black formatting and ruff check are clean on changed Python files. No unrelated source changes.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_build_storage_dir.py -q`

## Test Specification

- `test_build_storage_dir_overrides_plane_location`: `--storage-dir` places the plane at the absolute path, not `<root>/.parrot/wiki`.
- `test_build_storage_dir_does_not_persist_config`: After the run, the scanned repo has no new/changed `.parrot/wiki.json` and no env overlay.
- `test_build_storage_dir_rejects_relative_path`: A relative value raises `ClickException`.
- `test_build_without_storage_dir_unchanged`: Omitting the flag keeps today's persistence behaviour.

## Agent Instructions

1. Use `$sdd-start TASK-4335` to provision the feature worktree; do not implement on dev.
2. Read the spec and ensure dependencies are done in `sdd/tasks/index/github-reviewer-local-repo-wiki.json`.
3. Reverify contracts and anchors, including prerequisite-created anchors; update stale task evidence before implementing.
4. Implement only declared files, run Validation Commands, and retain logs under artifacts/logs/.
5. Commit scoped code, then close with `scripts.sdd.finalize_task` and real TaskCompletionEvidence.
   Let the finalizer own the completion note and active-to-completed move; commit its SDD state separately.

## Completion Note

Implemented by gpt-5.6-terra (codex), merged by orchestrator. test_cli_build_storage_dir.py: pass (with test_repo_cache, 9 passed).
