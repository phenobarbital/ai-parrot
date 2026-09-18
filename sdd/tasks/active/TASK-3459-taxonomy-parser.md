# TASK-3459: Taxonomy parser — `DocTaxonomy`, `parse_taxonomy`, `KNOWN_PROJECTS`

**Feature**: FEAT-576 — SDD Document Taxonomy (`projects` and `tags` frontmatter)
**Spec**: `sdd/specs/sdd-spec-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1**. This is the foundation that every other FEAT-576 task
reads: a soft project vocabulary, tag/project normalization, a `DocTaxonomy` Pydantic model
and a forgiving `parse_taxonomy(doc_path)` that reads the new `projects`/`tags` frontmatter
keys of brainstorm/proposal/spec documents. `FlowMeta` and `parse()` MUST NOT change
behavior (spec §2 Overview, AC4).

---

## Scope

- Add `KNOWN_PROJECTS`, `PROJECT_ALIASES`, `_TAG_RE`, `normalize_tag()`, `normalize_project()`,
  `DocTaxonomy`, `_read_frontmatter()` and `parse_taxonomy()` to
  `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py`.
- Refactor `parse()` to obtain its dict from `_read_frontmatter()` **without changing any
  return value** (no frontmatter / <3 parts / non-dict → `FlowMeta(type="feature", base_branch="dev")`).
- Re-export the new public names from the `scripts/sdd/sdd_meta.py` shim.
- Write `tests/sdd_scripts/test_sdd_taxonomy.py`.

**NOT in scope**: templates (TASK-3460), CLIs (TASK-3461, TASK-3463), ingest (TASK-3462),
any command `.md` file. Do NOT add fields to `FlowMeta`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` | MODIFY | taxonomy constants, model, parser; `_read_frontmatter` shared with `parse()` |
| `scripts/sdd/sdd_meta.py` | MODIFY | re-export new names |
| `tests/sdd_scripts/test_sdd_taxonomy.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import logging, re                       # verified: sdd_meta.py:14-15
from pathlib import Path                 # verified: sdd_meta.py:16
from typing import Literal               # verified: sdd_meta.py:17
import yaml                              # verified: sdd_meta.py:19
from pydantic import BaseModel, model_validator  # verified: sdd_meta.py:20 — ADD Field, field_validator to this line
from scripts.sdd.sdd_meta import FlowMeta, emit, parse  # verified: tests/sdd_scripts/test_sdd_meta.py:10 (test import style)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
logger = logging.getLogger(__name__)                                  # line 22
KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})  # line 30 — soft-vocabulary precedent
class FlowMeta(BaseModel):                                            # line 42 (no model_config → extra="ignore")
def parse(doc_path: Path) -> FlowMeta:                                # line 55; body lines 76-85:
    #   text = doc_path.read_text(encoding="utf-8")
    #   if not text.startswith("---"): return FlowMeta(type="feature", base_branch="dev")
    #   parts = text.split("---", 2)
    #   if len(parts) < 3: return FlowMeta(...defaults)
    #   block = yaml.safe_load(parts[1]) or {}
    #   if not isinstance(block, dict): return FlowMeta(...defaults)
    #   return FlowMeta(**block)

# scripts/sdd/sdd_meta.py:10-20 — `from parrot.knowledge.wiki.ledger.sdd_meta import (  # noqa: F401` + sorted name list
```

### Does NOT Exist
- ~~`FlowMeta.projects` / `FlowMeta.tags`~~ — must NOT be added
- ~~`KNOWN_PROJECTS`, `PROJECT_ALIASES`, `DocTaxonomy`, `parse_taxonomy`, `normalize_tag`, `normalize_project`, `_read_frontmatter`~~ — created by this task
- ~~`parrot.knowledge.wiki.ledger.taxonomy`~~ — no separate module; everything lives in `sdd_meta.py`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py", "action": "MODIFY"},
    {"path": "scripts/sdd/sdd_meta.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_sdd_taxonomy.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#FlowMeta",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#parse"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Unknown project → `logger.warning(...)` and KEEP the value (spec G2, AC3). Never raise for unknown.
- Malformed tag/project (fails `_TAG_RE` after normalization) → `ValueError` inside the
  validator, surfacing as `pydantic.ValidationError` from `parse_taxonomy` (AC3).
- Dedupe preserving first occurrence (spec G3).
- `KNOWN_PROJECTS` must include every `packages/*` dir with a `pyproject.toml` — the test
  enforces it by listing the directory (AC5). Verified list on 2026-09-19:
  `ai-parrot ai-parrot-advisors ai-parrot-client-amazon ai-parrot-client-anthropic
  ai-parrot-client-gemma4 ai-parrot-client-google ai-parrot-client-grok ai-parrot-client-groq
  ai-parrot-client-hf ai-parrot-client-jev ai-parrot-client-local ai-parrot-client-meta
  ai-parrot-client-moonshot ai-parrot-client-nvidia ai-parrot-client-openai
  ai-parrot-client-openrouter ai-parrot-client-vllm ai-parrot-client-zai ai-parrot-embeddings
  ai-parrot-integrations ai-parrot-loaders ai-parrot-openlit-bridge ai-parrot-pipelines
  ai-parrot-server ai-parrot-tools ai-parrot-visualizations navrules parrot-formdesigner`.
- Worktree test runs need `PYTHONPATH=packages/ai-parrot/src` (shared venv is editable-installed
  against the main checkout — see `.claude/rules/worktree-management.md` §4).

---

## Implementation Blueprint

### Steps (in order)
1. Extend the pydantic import to `from pydantic import BaseModel, Field, field_validator, model_validator` — *why*: the model needs `Field(default_factory=list)` and before-validators.
2. Add `from typing import Any, Literal` — *why*: `_read_frontmatter` returns `dict[str, Any] | None`.
3. Insert the constants block after `WORK_KIND_FLOW` (before `class FlowMeta`) — *why*: keeps module-level vocabularies together, next to the `KNOWN_BRANCHES` precedent.
4. Add `_read_frontmatter` and rewrite `parse()` to use it — *why*: one frontmatter-splitting implementation for both parsers (spec M1); behavior of `parse()` must stay identical (AC4).
5. Add `normalize_tag`, `normalize_project`, `DocTaxonomy`, `parse_taxonomy` after `emit()` — *why*: new public API grouped after the existing one.
6. Re-export in the shim; write tests; run `test_sdd_meta.py` unmodified to prove AC4.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` (MODIFY — constants)
```python
# occurrences: 1 (verified: grep -c '^class FlowMeta(BaseModel):' sdd_meta.py)
# BEFORE — insert above `class FlowMeta(BaseModel):` (verified: sdd_meta.py:42)

#: Canonical ``projects`` values for SDD docs (FEAT-576): every ``packages/<dist>``
#: directory name plus non-package areas. Soft vocabulary — like
#: ``KNOWN_BRANCHES``, an unknown value logs a warning and is kept, never rejected.
KNOWN_PROJECTS: frozenset[str] = frozenset(
    {
        # FILL IN: every packages/* dir name listed in Implementation Notes (28 names) — bounded by AC5 drift test
        "sdd-tooling",
        "dev-loop",
        "admin-ui",
        "docs",
        "ci",
    }
)

#: alias -> canonical project name, applied after tag-style normalization.
PROJECT_ALIASES: dict[str, str] = {
    "parrot-core": "ai-parrot",
    "core": "ai-parrot",
    "parrot": "ai-parrot",
    "formdesigner": "parrot-formdesigner",
    "server": "ai-parrot-server",
    "tools": "ai-parrot-tools",
    "parrot-tools": "ai-parrot-tools",
    "sdd": "sdd-tooling",
    "ui": "admin-ui",
}

_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

```
**Why**: spec §3 M1 Interface Skeleton fixes these names and the alias map verbatim.

### `sdd_meta.py` (MODIFY — `_read_frontmatter` + `parse` refactor)
```python
# occurrences: 1 (verified: grep -c '^def parse(doc_path: Path) -> FlowMeta:' sdd_meta.py)
# REPLACE the body lines 76-85 of parse() (keep its docstring verbatim) with:
    block = _read_frontmatter(doc_path)
    if block is None:
        return FlowMeta(type="feature", base_branch="dev")
    return FlowMeta(**block)


# and ADD above `def parse(`:
def _read_frontmatter(doc_path: Path) -> dict[str, Any] | None:
    """Return the leading YAML frontmatter of ``doc_path`` as a dict.

    Same rules as :func:`parse`: the block must start at byte 0 with ``---``.
    Returns ``None`` when there is no usable block (no leading ``---``, an
    unterminated block, or a non-mapping body) and ``{}`` for an empty block.
    """
    text = doc_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    block = yaml.safe_load(parts[1]) or {}
    return block if isinstance(block, dict) else None
```
**Why**: `None` vs `{}` preserves `parse()` byte-for-byte: an empty block (`---\n---`) still
reaches `FlowMeta(**{})` and raises exactly as before, while the three "no frontmatter" cases
still return the defaults (AC4).

### `sdd_meta.py` (MODIFY — public taxonomy API, append after `emit()`)
```python
def normalize_tag(raw: str) -> str:
    """Normalize a tag: lowercase, trim, whitespace/underscore runs -> '-', collapse '--', strip '-'.

    Raises:
        ValueError: when the result does not match ``^[a-z0-9][a-z0-9-]{0,39}$``.
    """
    # FILL IN: implement with re.sub; bounded by spec §4 test_normalize_tag ("Tool Output_Pruning" -> "tool-output-pruning")
    raise NotImplementedError


def normalize_project(raw: str) -> str:
    """Normalize like a tag, then map through ``PROJECT_ALIASES``.

    Logs a warning (never raises) when the canonical value is not in ``KNOWN_PROJECTS``.

    Raises:
        ValueError: only when the value is malformed (see :func:`normalize_tag`).
    """
    value = normalize_tag(raw)
    value = PROJECT_ALIASES.get(value, value)
    if value not in KNOWN_PROJECTS:
        logger.warning("Unknown SDD project %r (not in KNOWN_PROJECTS); keeping it", value)
    return value


class DocTaxonomy(BaseModel):
    """Organizational metadata of an SDD doc: the projects it concerns and its tags."""

    projects: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("projects", mode="before")
    @classmethod
    def _norm_projects(cls, value: Any) -> list[str]:
        """Coerce None/str to a list, normalize each entry, dedupe preserving order."""
        # FILL IN: shared helper `_as_list(value)` (None->[], str->[str], list->list; other types -> ValueError) then dedupe normalize_project(v) — bounded by AC3, G3
        raise NotImplementedError

    @field_validator("tags", mode="before")
    @classmethod
    def _norm_tags(cls, value: Any) -> list[str]:
        """Same as projects, with :func:`normalize_tag` and no vocabulary check."""
        # FILL IN: same shape as _norm_projects using normalize_tag
        raise NotImplementedError


def parse_taxonomy(doc_path: Path) -> DocTaxonomy:
    """Parse ``projects``/``tags`` from a brainstorm/proposal/spec frontmatter (FEAT-576).

    Args:
        doc_path: Markdown document to inspect.

    Returns:
        A ``DocTaxonomy``; empty lists when the doc has no frontmatter or no keys.

    Raises:
        pydantic.ValidationError: when a tag/project is malformed.
    """
    block = _read_frontmatter(doc_path) or {}
    return DocTaxonomy(projects=block.get("projects"), tags=block.get("tags"))
```
**Why**: signatures are fixed by the spec §3 M1 skeleton; `parse_taxonomy` never looks at
`type`/`base_branch`, so it works on the proposal template whose `type:` is a placeholder
string that `parse()` would reject.

### `scripts/sdd/sdd_meta.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'KNOWN_BRANCHES,' scripts/sdd/sdd_meta.py)
# REPLACE the import list (lines 10-20) with — keep alphabetical order, as today:
from parrot.knowledge.wiki.ledger.sdd_meta import (  # noqa: F401
    KNOWN_BRANCHES,
    KNOWN_PROJECTS,
    PROJECT_ALIASES,
    WORK_KIND_FLOW,
    WORKTREE_ROOT,
    DocTaxonomy,
    FlowMeta,
    WorktreePlan,
    emit,
    normalize_project,
    normalize_tag,
    parse,
    parse_taxonomy,
    plan_worktree,
    resolve_flow,
)
```
**Why**: every SDD script and test imports through the shim (`scripts.sdd.sdd_meta`).

### FILL IN checklist
- [ ] `KNOWN_PROJECTS` — all 28 `packages/*` names; bounded by AC5 drift test
- [ ] `normalize_tag` — regex normalization; bounded by `test_normalize_tag`
- [ ] `DocTaxonomy` validators — `_as_list` coercion + ordered dedupe; bounded by AC3/G3
- [ ] Add `test_parse_empty_block_still_raises` (`---\n---\n` → `ValidationError` from `parse()`) to lock AC4
---

## Acceptance Criteria

- [ ] `from scripts.sdd.sdd_meta import DocTaxonomy, parse_taxonomy, KNOWN_PROJECTS, PROJECT_ALIASES, normalize_tag, normalize_project` works
- [ ] Unknown project kept + warned; malformed tag raises `ValidationError` (AC3)
- [ ] `tests/sdd_scripts/test_sdd_meta.py` and `test_sdd_meta_resolve_flow.py` pass **unmodified** (AC4)
- [ ] Drift test: every `packages/*/pyproject.toml` dir ∈ `KNOWN_PROJECTS` (AC5)
- [ ] `ruff check` clean on both modified Python files

---

## Validation Commands
- `pytest tests/sdd_scripts/test_sdd_taxonomy.py -q`
- `pytest tests/sdd_scripts/test_sdd_meta.py -q`
- `pytest tests/sdd_scripts/test_sdd_meta_resolve_flow.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_sdd_taxonomy.py
"""Unit tests for the FEAT-576 SDD taxonomy parser."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.sdd.sdd_meta import KNOWN_PROJECTS, DocTaxonomy, normalize_tag, parse, parse_taxonomy

REPO_ROOT = Path(__file__).resolve().parents[2]


def _doc(tmp_path: Path, front: str) -> Path:
    p = tmp_path / "x.spec.md"
    p.write_text(f"---\n{front}---\n# X\n", encoding="utf-8")
    return p


def test_parse_taxonomy_absent_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "plain.md"
    p.write_text("# no frontmatter\n", encoding="utf-8")
    assert parse_taxonomy(p) == DocTaxonomy()


def test_parse_taxonomy_scalar_coerced(tmp_path: Path) -> None:
    assert parse_taxonomy(_doc(tmp_path, "tags: memory\n")).tags == ["memory"]


def test_normalize_tag() -> None:
    assert normalize_tag("Tool Output_Pruning") == "tool-output-pruning"
    with pytest.raises(ValueError):
        normalize_tag("!!")


def test_project_alias(tmp_path: Path) -> None:
    t = parse_taxonomy(_doc(tmp_path, "projects: [parrot-core, formdesigner]\n"))
    assert t.projects == ["ai-parrot", "parrot-formdesigner"]


def test_unknown_project_warns_not_fails(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        t = parse_taxonomy(_doc(tmp_path, "projects: [mystery-area]\n"))
    assert t.projects == ["mystery-area"]
    assert "mystery-area" in caplog.text


def test_dedupe_preserves_order(tmp_path: Path) -> None:
    assert parse_taxonomy(_doc(tmp_path, "tags: [b, a, B]\n")).tags == ["b", "a"]


def test_malformed_tag_raises(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        parse_taxonomy(_doc(tmp_path, "tags: ['!!']\n"))


def test_parse_unchanged_with_taxonomy_keys(tmp_path: Path) -> None:
    meta = parse(_doc(tmp_path, "type: feature\nbase_branch: dev\nprojects: [ai-parrot]\ntags: [x]\n"))
    assert (meta.type, meta.base_branch) == ("feature", "dev")


def test_known_projects_covers_packages_dir() -> None:
    dists = {p.parent.name for p in (REPO_ROOT / "packages").glob("*/pyproject.toml")}
    assert dists, "packages/*/pyproject.toml not found"
    assert dists <= KNOWN_PROJECTS, f"missing from KNOWN_PROJECTS: {sorted(dists - KNOWN_PROJECTS)}"
```

---

## Agent Instructions

1. Read the spec (§2 Overview, §3 Module 1, §5 AC2–AC5).
2. Verify the Codebase Contract line numbers before editing.
3. Implement from the blueprint; complete every `FILL IN`.
4. Run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src` inside a worktree).
5. Fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
