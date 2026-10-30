# TASK-4897: `ingest-ddl --changed` diffs the right range

**Feature**: FEAT-771 — wikitoolkit CLI fixes
**Spec**: `sdd/specs/wiki-cli-fixes.spec.md`
**Discovered-from**: `issue:7f50ee6aaa74`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4896
**Assigned-to**: unassigned

---

## Context

Spec §1.C, §2 Module 3. The shared post-commit/post-merge hook runs `schema ingest-ddl --changed`, which
always diffs `ORIG_HEAD HEAD` — stale after a plain commit, missing in a fresh clone.

---

## Scope

- `cli.py`:
  - New `_git_changed_files(root: Path, diff_range: str | None) -> list[str]`:
    explicit range → `git diff --name-only <diff_range>`; else last reflog subject
    (`git reflog -1 --format=%gs HEAD`) starting with `merge`, `pull` or `commit (merge)` →
    `git diff --name-only ORIG_HEAD HEAD`; else → `git diff-tree --no-commit-id --name-only -r --root HEAD`.
    Git failures raise `click.ClickException` (as today).
  - `_changed_ddl_paths(root, origin, diff_range=None)` uses it; filtering unchanged.
  - `schema ingest-ddl --range TEXT` (UsageError without `--changed`), passed to `_changed_ddl_paths`.
- `docs/wiki/schema-plane.md`: `--changed` range rules and `--range`.
- `test_cli_schema.py`: new tests (spec §4 Module 3 rows); the lambda at :96 gains `diff_range=None`.

**NOT in scope**: hook text in `claude_code/assets.py` (installer never upgrades an existing block).

---

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY |
| `docs/wiki/schema-plane.md` | MODIFY |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_cli_schema.py` | MODIFY |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`from parrot.knowledge.wiki import cli` (module), `cli._changed_ddl_paths`; `subprocess`, `click`,
`PurePosixPath` already imported in cli.py.

### Existing Signatures
`_changed_ddl_paths(root: Path, origin: str) -> list[Path]` (cli.py:4086, diff at :4096);
`schema_ingest_ddl(paths, origin, dialect, changed, as_json, quiet)` (:4185, calls
`_changed_ddl_paths(root, alias)`); test lambda `lambda root, origin: ...` (test_cli_schema.py:96).
Line numbers are pre-TASK-4895.

### Does NOT Exist
`_git_changed_files`, `--range` — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_changed_ddl_paths",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#schema_ingest_ddl"
  ]
}
```

---

## Implementation Notes

- `--root` makes `diff-tree` list a repository's first commit.
- A merge commit made by `git commit` after a conflicted merge has reflog subject `commit (merge): …`.

---

## Acceptance Criteria

- [ ] Spec §5 criterion 8 holds.
- [ ] `ruff check` clean on the changed files.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_cli_schema.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_schema_hook_assets.py -q`

---

## Test Specification

Spec §4 Unit Tests, Module 3 rows (throwaway git repo in `tmp_path`).

---

## Agent Instructions

Implement inside `.claude/worktrees/feat-FEAT-771-wiki-cli-fixes`; run tests with
`PYTHONPATH=packages/ai-parrot/src`.

---

## Completion Note

_(filled on completion)_
