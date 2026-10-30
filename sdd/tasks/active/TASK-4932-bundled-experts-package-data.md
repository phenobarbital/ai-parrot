# TASK-4932: Ship the bundled experts in the wheel (package-data)

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4930, TASK-4931
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (package-data part), AC28, §7 risk "Package-data is opt-in with setuptools". `ai-parrot` builds
with setuptools and ships non-Python files only when `[tool.setuptools.package-data]` names them
(`packages/ai-parrot/pyproject.toml:975-992`). Without this entry the wheel contains `bundled/__init__.py` and no
bundle, while every source-tree test still passes. This task adds the entry and proves it with a real wheel build.

**Exclusive (`parallel: false`)**: it edits `pyproject.toml`, a dependency manifest other tasks' environments read.

---

## Scope

- Add `"parrot.experts.bundled" = [...]` after the `parrot.flows.dev_flow` package-data line.
- Write `test_bundled_wheel.py`: `importlib.resources.files("parrot.experts.bundled")` lists both bundles with
  their `expert.yaml` (source tree); a second test, marked to run only when `uv` is available, builds the wheel
  into `tmp_path` (`uv build --wheel packages/ai-parrot --out-dir <tmp>`) and asserts the archive contains every
  bundle file.

**NOT in scope**: any dependency change (none needed — `uv.lock` must stay untouched).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | One package-data entry |
| `packages/ai-parrot/tests/experts/test_bundled_wheel.py` | CREATE | Resource + wheel-content tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import importlib.resources   # stdlib
import zipfile               # stdlib — inspect the built wheel
```

### Existing Signatures to Use
```toml
# packages/ai-parrot/pyproject.toml
[tool.setuptools.package-data]                                   # line 975
"parrot.flows.dev_loop" = ["_subagent_data/*.md"]                # line 989
"parrot.flows.dev_flow" = ["_subagent_data/*.md"]                # line 992 — insert after this line
```

### Does NOT Exist
- ~~`MANIFEST.in` for ai-parrot~~ — package data is declared only in `pyproject.toml`.
- ~~recursive `**` globs in this table for bundles~~ — use the explicit per-subdir patterns below (setuptools
  globs are relative to the package directory).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/experts/test_bundled_wheel.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the entry — *why*: AC28.
2. Write the tests; run the wheel test locally once and paste the file list in the Completion Note.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c '"parrot.flows.dev_flow" = \["_subagent_data/\*.md"\]' packages/ai-parrot/pyproject.toml)
# AFTER — insert below `"parrot.flows.dev_flow" = ["_subagent_data/*.md"]` (verified: pyproject.toml:992)
# FEAT-778: package-bundled domain experts, read via importlib.resources by parrot.experts.loader.
"parrot.experts.bundled" = ["*/expert.yaml", "*/persona.md", "*/identity/*.md", "*/knowledge/*.md", "*/rules/*.md", "*/adr/*.md"]
```

### FILL IN checklist
- [ ] Wheel test: skip cleanly (`pytest.skip`) when `uv` is not on PATH; never touch the shared `.venv`.

---

## Acceptance Criteria

- [ ] AC28 — the built wheel contains every file of `cve-analyst` and `cve-remediation`.
- [ ] `uv.lock` unchanged; `git diff packages/ai-parrot/pyproject.toml` is the one entry plus its comment.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_bundled_wheel.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_bundled_wheel.py
def test_bundled_resources_list_both_experts(): ...   # FILL IN
def test_built_wheel_contains_bundles(tmp_path): ...  # FILL IN: uv build --wheel …; zipfile namelist
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4932 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
