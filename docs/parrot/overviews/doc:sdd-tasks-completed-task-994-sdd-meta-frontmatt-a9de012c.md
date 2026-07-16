---
type: Wiki Overview
title: 'TASK-994: SDD frontmatter parser (`sdd_meta`)'
id: doc:sdd-tasks-completed-task-994-sdd-meta-frontmatter-parser-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 1** of FEAT-145. Every other task that needs to read
---

# TASK-994: SDD frontmatter parser (`sdd_meta`)

**Feature**: FEAT-145 — SDD Flow Types and Per-Spec Index
**Spec**: `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of FEAT-145. Every other task that needs to read
or emit YAML frontmatter on brainstorm/proposal/spec files depends on
this small shared library. Validation rules (e.g. `type: hotfix` ⇒
`base_branch: main`) live here, not duplicated across commands.

---

## Scope

- Create `scripts/sdd/__init__.py` (empty package marker).
- Create `scripts/sdd/sdd_meta.py` exposing:
  - `class FlowMeta(BaseModel)` with fields `type: Literal["feature", "hotfix"]` and `base_branch: str`.
  - A Pydantic v2 `model_validator` (or `field_validator`) that enforces `type == "hotfix" ⇒ base_branch == "main"`.
  - `def parse(doc_path: Path) -> FlowMeta` that reads the file, extracts the YAML block between the first two `---` lines (Jekyll-style frontmatter), and returns `FlowMeta`. When no frontmatter is present, return defaults `FlowMeta(type="feature", base_branch="dev")` — never raise on missing frontmatter.
  - A `def emit(meta: FlowMeta) -> str` helper that renders frontmatter as a `---\n...\n---\n` block (used by generation commands in TASK-997).
- Create `tests/scripts/__init__.py` (empty package marker, only if `tests/scripts/` does not already exist).
- Create `tests/scripts/test_sdd_meta.py` with the four unit tests listed in the spec §4.

**NOT in scope**:
- Any change to `.claude/commands/*.md` or `.claude/agents/*.md` (those are TASK-997, 998, 999, 1000, 1001).
- Migration logic (TASK-995).
- Template files (TASK-996).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/__init__.py` | CREATE | Empty package marker |
| `scripts/sdd/sdd_meta.py` | CREATE | `FlowMeta` + `parse()` + `emit()` |
| `tests/scripts/__init__.py` | CREATE (if missing) | Empty package marker |
| `tests/scripts/test_sdd_meta.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import yaml                              # pyyaml ≥ 6 — already in tree
from pathlib import Path                 # stdlib
from typing import Literal               # stdlib
from pydantic import BaseModel           # pydantic v2 — already in tree
from pydantic import model_validator     # pydantic v2 ≥ 2.0
```

### Existing Signatures to Use

`pydantic.model_validator` is the v2 replacement for v1's `root_validator`. Use mode `"after"` so the validator runs against the constructed model:

```python
from pydantic import BaseModel, model_validator

class FlowMeta(BaseModel):
    type: Literal["feature", "hotfix"]
    base_branch: str

    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta":
        if self.type == "hotfix" and self.base_branch != "main":
            raise ValueError("type='hotfix' requires base_branch='main'")
        return self
```

### Does NOT Exist

- ~~`from scripts.sdd import sdd_meta`~~ — does not exist yet; this task creates it.
- ~~`yaml.load(...)`~~ without a `Loader` — never use; always `yaml.safe_load(...)`.
- ~~`pydantic.root_validator`~~ — Pydantic v1 only; this codebase is v2.
- ~~`tests/scripts/`~~ directory may not exist — verify and create if absent.

---

## Implementation Notes

### Frontmatter parsing

A Jekyll-style frontmatter block starts on line 1 with `---`, ends with the next `---` on its own line, and contains valid YAML between. If the file does NOT start with `---`, the file has no frontmatter and `parse()` returns defaults.

```python
def parse(doc_path: Path) -> FlowMeta:
    text = doc_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return FlowMeta(type="feature", base_branch="dev")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return FlowMeta(type="feature", base_branch="dev")
    block = yaml.safe_load(parts[1]) or {}
    return FlowMeta(**block)  # ValidationError propagates if invalid
```

### Emit helper

```python
def emit(meta: FlowMeta) -> str:
    body = yaml.safe_dump(meta.model_dump(), sort_keys=False).rstrip()
    return f"---\n{body}\n---\n"
```

### Key Constraints

- Pure stdlib + already-installed deps (pyyaml, pydantic).
- No I/O outside `parse()` (which reads a single file).
- `FlowMeta` must be importable as `from scripts.sdd.sdd_meta import FlowMeta, parse, emit`.

---

## Acceptance Criteria

- [ ] `scripts/sdd/__init__.py` and `scripts/sdd/sdd_meta.py` exist.
- [ ] `from scripts.sdd.sdd_meta import FlowMeta, parse, emit` succeeds.
- [ ] `pytest tests/scripts/test_sdd_meta.py -v` passes (all 4 tests).
- [ ] `ruff check scripts/sdd/ tests/scripts/test_sdd_meta.py` passes.
- [ ] Parsing a file without frontmatter returns `FlowMeta(type="feature", base_branch="dev")`.
- [ ] Parsing `type: hotfix` with `base_branch: dev` raises `pydantic.ValidationError`.

---

## Test Specification

```python
# tests/scripts/test_sdd_meta.py
from pathlib import Path
import pytest
from pydantic import ValidationError
from scripts.sdd.sdd_meta import FlowMeta, parse, emit


def test_parse_no_frontmatter_returns_defaults(tmp_path: Path):
    f = tmp_path / "doc.md"
    f.write_text("# Heading\nbody\n")
    meta = parse(f)
    assert meta.type == "feature"
    assert meta.base_branch == "dev"


def test_parse_feature_with_dev_base(tmp_path: Path):
    f = tmp_path / "doc.md"
    f.write_text("---\ntype: feature\nbase_branch: dev\n---\n# body\n")
    meta = parse(f)
    assert meta.type == "feature"
    assert meta.base_branch == "dev"


def test_parse_hotfix_requires_main(tmp_path: Path):
    f = tmp_path / "doc.md"
    f.write_text("---\ntype: hotfix\nbase_branch: dev\n---\n")
    with pytest.raises(ValidationError):
        parse(f)


def test_parse_unknown_type_rejected(tmp_path: Path):
    f = tmp_path / "doc.md"
    f.write_text("---\ntype: bug\nbase_branch: dev\n---\n")
    with pytest.raises(ValidationError):
        parse(f)


def test_emit_round_trips(tmp_path: Path):
    meta = FlowMeta(type="hotfix", base_branch="main")
    block = emit(meta)
    assert block.startswith("---\n") and block.endswith("---\n")
    f = tmp_path / "doc.md"
    f.write_text(block + "# body\n")
    assert parse(f) == meta
```

---

## Agent Instructions

1. Activate venv: `source .venv/bin/activate`.
2. Verify `pyyaml` and `pydantic` are importable: `python -c "import yaml, pydantic; print(pydantic.VERSION)"`. Pydantic must be ≥ 2.0.
3. Implement `sdd_meta.py` per the contract above.
4. Run `pytest tests/scripts/test_sdd_meta.py -v` and iterate until green.
5. Run `ruff check scripts/sdd/ tests/scripts/test_sdd_meta.py` and fix any issues.
6. Commit: `feat(sdd): TASK-994 — sdd_meta frontmatter parser`.

---

## Completion Note

**Completed by**: Claude (Opus 4.7) — interactive session via `/sdd-start TASK-994`
**Date**: 2026-05-05
**Notes**: Implemented `FlowMeta` (Pydantic v2) + `parse()` + `emit()` in `scripts/sdd/sdd_meta.py`. All 5 unit tests pass.

**Deviations from scope** (each justified by integration friction discovered at runtime):

1. **Renamed `tests/scripts/` → `tests/sdd_scripts/`.** The original name shadowed the worktree's real `scripts/` package via pytest's `tests/`-on-`sys.path[0]` behaviour (PEP 420 namespace package collision). Renaming is the minimal fix; tests still discovered cleanly by `python_files = "test_*.py"`.
2. **Edited `conftest.py` (worktree root):** added `_WORKTREE_ROOT` to the existing `_EXTRA_PATHS` list so `from scripts.sdd.sdd_meta import …` resolves under pytest. Single-line addition that follows the conftest's documented pattern.
3. **Lint step substituted.** Neither `ruff` nor `pyflakes` are available in the worktree `.venv`. `python -m py_compile` succeeds on both new files; ruff should run cleanly under TASK-1002 once a lint pass is added to the suite.

**Files actually touched (vs contract):**
- `scripts/sdd/__init__.py` (CREATE — as specified)
- `scripts/sdd/sdd_meta.py` (CREATE — as specified)
- `tests/sdd_scripts/__init__.py` (CREATE — renamed from `tests/scripts/`)
- `tests/sdd_scripts/test_sdd_meta.py` (CREATE — renamed; +1 round-trip test for `emit`)
- `conftest.py` (MODIFY — sys.path fix for namespace package)
