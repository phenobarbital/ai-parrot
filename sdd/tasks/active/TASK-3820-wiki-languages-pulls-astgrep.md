# TASK-3820: `wiki-languages` extra pulls `ast-grep-py`

**Feature**: FEAT-609 — Honest structural tier, Svelte component symbols, module-local JS functions, and federated symbol queries in wikitoolkit
**Spec**: `sdd/specs/wikitoolkit-structural-coverage.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §8 Q1 (answered "yes" by Jesús): installing "the language plugins" must be enough to get
symbols. Today `wiki-languages` (`packages/ai-parrot/pyproject.toml:301`) ships only the
tree-sitter grammars, and every non-Python symbol comes from the ast-grep seam, which lives in
`wiki-structural` (`:316`). A user with `wiki-languages` gets outlines and **0 symbols**, with no
warning. This was measured on `navigator-svelte`: 0 symbols before, 13,574 after. Spec §3
Module 1 (packaging bullet), G7.

---

## Scope

- Add `"ast-grep-py>=0.45",` to the `wiki-languages` extra.
- Keep `wiki-structural` exactly as it is (same single entry), so existing install lines
  (`ai-parrot[wiki-structural]`) keep working.
- Rewrite the comment above `wiki-languages` so it no longer says the extra only adds
  tree-sitter outlines, and says it now brings the structural (symbol) tier too.
- Add a packaging test that parses `pyproject.toml` and asserts the extra lists `ast-grep-py`.

**NOT in scope**: the build warning and `status` line (TASK-3824), making ast-grep a core
dependency (spec Non-Goals), touching `uv.lock` or any other manifest.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | add `ast-grep-py>=0.45` to `wiki-languages`; update its comment |
| `tests/knowledge/wiki/test_extras_packaging.py` | CREATE | assert the extra's content |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import tomllib  # stdlib, Python >= 3.11
from pathlib import Path
```

### Existing Signatures to Use
```toml
# packages/ai-parrot/pyproject.toml:301
wiki-languages = [
    "tree-sitter>=0.23",
    "tree-sitter-php>=0.23",
    "tree-sitter-typescript>=0.23",
    "tree-sitter-javascript>=0.23",
    "tree-sitter-rust>=0.23",
    "tree-sitter-perl>=0.23",
    "tree-sitter-luau>=1.2",
]
# packages/ai-parrot/pyproject.toml:316
wiki-structural = [
    "ast-grep-py>=0.45",
]
# packages/ai-parrot/pyproject.toml:333
wiki = [
    "ai-parrot[graphindex,wiki-languages,wiki-structural,leiden]",
    ...
]
```

### Does NOT Exist
- ~~A `[project.optional-dependencies]` entry named `wiki-symbols`~~: do not invent one.
- ~~A root-level `pyproject.toml` extra for ai-parrot~~: the ai-parrot distribution's
  extras live in `packages/ai-parrot/pyproject.toml`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/pyproject.toml", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_extras_packaging.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- This task edits a dependency manifest, so it is **exclusive** (`parallel: false`) in the
  index.
- Do not reorder the existing grammar entries: a minimal diff keeps the review obvious.
- Do not regenerate any lock file.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `ast-grep-py` line at the end of `wiki-languages`. *Why*: Q1. Appending leaves the
   existing lines untouched in the diff.
2. Update the comment block that precedes `wiki-languages`. *Why*: it currently promises
   outlines only, and that is exactly the misunderstanding FEAT-609 fixes.
3. Write the packaging test. *Why*: a later edit that drops the line would otherwise be silent
   again.

### `packages/ai-parrot/pyproject.toml` (MODIFY)
```toml
# occurrences: 1 (verified: grep -c 'wiki-languages = \[' packages/ai-parrot/pyproject.toml)
# AFTER — insert as the last entry of the list opened by `wiki-languages = [` (verified: pyproject.toml:301)
    # FEAT-609 (Q1): for every non-Python language, symbols come ONLY from the
    # ast-grep seam; without it this extra gave outlines and 0 sym: pages.
    "ast-grep-py>=0.45",
```
**Why**: `wiki-structural` stays as an identical alias, so `ai-parrot[wiki]` (which lists both
extras) resolves the same package once.

### `tests/knowledge/wiki/test_extras_packaging.py` (CREATE)
```python
"""FEAT-609 Q1: the `wiki-languages` extra must bring the structural tier."""

from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[3] / "packages" / "ai-parrot" / "pyproject.toml"


def _extras() -> dict[str, list[str]]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


def test_wiki_languages_extra_pulls_astgrep() -> None:
    """Installing the language plugins alone must yield symbols (spec G7)."""
    names = [spec.split(">")[0].split("=")[0].strip() for spec in _extras()["wiki-languages"]]
    assert "ast-grep-py" in names


def test_wiki_structural_extra_kept() -> None:
    """The old extra name keeps working for existing install lines."""
    assert any(spec.startswith("ast-grep-py") for spec in _extras()["wiki-structural"])
```
**Why**: `parents[3]` from `tests/knowledge/wiki/` is the repo root. Verify it with a
`print(_PYPROJECT)` before trusting it.

### FILL IN checklist
- [ ] Rewrite the comment block above `wiki-languages`. Bound: it must mention that the
  structural symbol tier is included (spec G7).

---

## Acceptance Criteria

- [ ] `wiki-languages` lists `ast-grep-py>=0.45`, and `wiki-structural` is unchanged.
- [ ] Mutation check: remove the new line and confirm `test_wiki_languages_extra_pulls_astgrep`
      goes RED, then restore it.
- [ ] `pytest tests/knowledge/wiki/test_extras_packaging.py -q` passes.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_extras_packaging.py -q`

---

## Test Specification

See the CREATE block above: both tests are complete as written.

---

## Agent Instructions

1. **Work in the feature worktree**, never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-structural-coverage --feature-id FEAT-609`).
2. Read the spec. Check `Depends-on` (none). Verify the Codebase Contract.
3. Set this task to `"in-progress"` in `sdd/tasks/index/wikitoolkit-structural-coverage.json`.
4. Implement from the blueprint. Run the Validation Commands. Stage only the listed files.
5. Close with `scripts/sdd/close_task.sh TASK-3820 wikitoolkit-structural-coverage verified`,
   then fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
