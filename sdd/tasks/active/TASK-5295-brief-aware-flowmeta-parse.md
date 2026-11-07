# TASK-5295: `sdd_meta.parse()` derives `type` for brief frontmatter

**Feature**: FEAT-836 — `sdd_meta.parse()` accepts brief frontmatter
**Spec**: `sdd/specs/ledger-sdd-meta-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:d713bb1cf575`

---

## Context

Spec §1-§2. `/sdd-brief` writes frontmatter `kind: brief`, `slug`, `key`, `base_branch` (sometimes
`hotfix_base`) and no `type`. `parse()` passes the block to `FlowMeta`, whose `type` is required, so it raises
`ValidationError`. `worktree_sync.resolve_base_branch` calls `parse(brief).base_branch`, logs
"Cannot parse selected brief …", then raises `SyncError` for `fix-*`/`hotfix-*` branches, so the host-side
stale-base advisory never runs for a brief worktree.

---

## Scope

- In `parse()`, when the frontmatter block has `kind: brief` and no `type` key, set
  `type = "hotfix"` if `block.get("base_branch") == cfg.hotfix_base`, else `"feature"`.
- An explicit `type` in a brief is left as written (still validated by `FlowMeta`).
- A brief without `base_branch` still raises `ValidationError` (do not invent a base).
- Update `parse()`'s docstring with the brief rule.
- New test file `packages/ai-parrot/tests/sdd/test_brief_flow_meta.py`.

**NOT in scope**: `worktree_sync.py` (no code change needed), `FlowMeta` fields/validator, `/sdd-brief`,
the brief frontmatter format.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` | MODIFY | derive `type` for `kind: brief` in `parse()` |
| `packages/ai-parrot/tests/sdd/test_brief_flow_meta.py` | CREATE | parse + resolve_base_branch tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.sdd_meta import FlowMeta, parse   # sdd_meta.py:108, :169
from parrot.sdd.config import SddConfig                              # sdd/config.py:25 (fields base_branch="dev", hotfix_base="main")
from parrot.sdd.scripts import worktree_sync                         # used the same way in tests/sdd/test_sdd_launch.py:16
from pydantic import ValidationError
```

### Existing Signatures to Use
```python
class FlowMeta(BaseModel):                                   # sdd_meta.py:108
    type: Literal["feature", "hotfix"]
    base_branch: str
    hotfix_base: str = Field(default=DEFAULT_HOTFIX_BASE, exclude=True)
    # _hotfix_implies_main: type="hotfix" requires base_branch == hotfix_base   (sdd_meta.py:116-122)
def _config_for(doc_path: Path | None, config: SddConfig | None) -> SddConfig      # sdd_meta.py:125
def _read_frontmatter(doc_path: Path) -> dict[str, Any] | None                      # sdd_meta.py:132
def parse(doc_path: Path, *, config: SddConfig | None = None) -> FlowMeta           # sdd_meta.py:169
    block = {k: v for k, v in block.items() if k != "hotfix_base"}                  # sdd_meta.py:195 (1 occurrence)
    return FlowMeta(**block, hotfix_base=cfg.hotfix_base)                           # sdd_meta.py:196

# worktree_sync.py
def _branch(wt: Path) -> str | None                                  # worktree_sync.py:101
def resolve_base_branch(wt: Path, override: str | None) -> str       # worktree_sync.py:189
#   brief path: wt / "sdd" / "briefs" / f"{slug}.brief.md" ; base = parse(brief).base_branch   (:202-209)
#   _slug_candidates: "fix-<KEY>-<slug>" -> suffixes after the 2nd part   (:172)
class SyncError(Exception)                                           # worktree_sync.py:51
```

### Does NOT Exist
- No `parse_brief`, `BriefMeta` or brief-specific parser in `sdd_meta.py`.
- No `kind` field on `FlowMeta` (extra keys are ignored by pydantic's default config — do not add one).
- No direct unit test of `worktree_sync.resolve_base_branch` today.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_brief_flow_meta.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#parse",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#FlowMeta",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_sync.py#resolve_base_branch"
  ]
}
```

---

## Implementation Notes

- Derive `type` from `cfg.hotfix_base`, not a literal `"main"` — because the hotfix lane is configurable.
- Keep an explicit `type` — because a brief that declares a type means it, and the validator should judge it.
- `resolve_flow()` also calls `parse()`; it benefits without change.

---

## Implementation Blueprint

### `sdd_meta.py`
```python
# AFTER — insert below `    block = {k: v for k, v in block.items() if k != "hotfix_base"}`
# (verified: sdd_meta.py:195; occurrences: 1)
    if block.get("kind") == "brief" and "type" not in block:
        # /sdd-brief frontmatter carries no `type`; a brief on the hotfix base is a hotfix.
        block["type"] = "hotfix" if block.get("base_branch") == cfg.hotfix_base else "feature"
```
Docstring of `parse()`: add under "Returns" that `kind: brief` frontmatter without `type` gets
`type="hotfix"` when `base_branch` is the configured hotfix base, otherwise `"feature"`.

**Why**: the fix lives where the frontmatter is turned into `FlowMeta`, so every caller (`worktree_sync`,
`resolve_flow`, the `sdd_meta parse` CLI) accepts briefs.

### `test_brief_flow_meta.py`
```python
"""FEAT-836: ``sdd_meta.parse()`` and ``worktree_sync.resolve_base_branch`` on /sdd-brief frontmatter."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.ledger.sdd_meta import parse
from parrot.sdd.config import SddConfig
from parrot.sdd.scripts import worktree_sync

CFG = SddConfig(base_branch="dev", hotfix_base="main")


def _brief(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{body}---\n\n# Brief\n", encoding="utf-8")
    return path

# FILL IN: the four parse tests and the resolve_base_branch test from the Test Specification
```

### FILL IN checklist
- [ ] Brief branch in `parse()` + docstring.
- [ ] Five tests from the Test Specification.

---

## Acceptance Criteria

- [ ] AC-1 `parse()` on brief frontmatter without `type` → `type="hotfix"` on the hotfix base, else `"feature"`.
- [ ] AC-2 Explicit brief `type` is not overridden; a brief without `base_branch` raises `ValidationError`.
- [ ] AC-3 `resolve_base_branch` returns the brief's `base_branch` for a `fix-*` brief worktree.
- [ ] Existing `tests/sdd_scripts/test_sdd_meta.py` and `test_sdd_meta_resolve_flow.py` pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_brief_flow_meta.py -q`
- `pytest tests/sdd_scripts/test_sdd_meta.py -q`
- `pytest tests/sdd_scripts/test_sdd_meta_resolve_flow.py -q`

---

## Test Specification

- `test_parse_brief_on_hotfix_base_is_hotfix`: body `kind: brief\nslug: x\nkey: NAV-1\nbase_branch: main\nhotfix_base: main\n`
  → `type == "hotfix"`, `base_branch == "main"` (`parse(p, config=CFG)`).
- `test_parse_brief_on_dev_is_feature`: `kind: brief`, `base_branch: dev`, plus `source:` mapping and `created: "2026-11-02"`
  → `type == "feature"`, `base_branch == "dev"`.
- `test_parse_brief_explicit_type_kept`: `kind: brief\ntype: hotfix\nbase_branch: dev\n` → `ValidationError`.
- `test_parse_brief_without_base_branch_fails`: `kind: brief\nslug: x\n` → `ValidationError`.
- `test_resolve_base_branch_reads_brief_frontmatter`: write `tmp_path/wt/sdd/briefs/thing.brief.md` with
  `kind: brief`, `base_branch: dev`; `monkeypatch.setattr(worktree_sync, "_branch", lambda wt: "fix-abc123-thing")`;
  `resolve_base_branch(wt, None) == "dev"`. `parse` loads config from the doc's repo; a `tmp_path` without
  `sdd/config.json` gives the defaults, so no extra patching is needed.

---

## Agent Instructions

1. Work in `feat-FEAT-836-ledger-sdd-meta-fixes`; run tests with `PYTHONPATH=packages/ai-parrot/src`.
2. Implement from the Blueprint, run the Validation Commands.
3. Commit only the listed files; close with `parrot sdd task close TASK-5295 ledger-sdd-meta-fixes verified`.

---

## Completion Note

_(fill in on completion)_
