# TASK-3462: Wiki ledger ingest — surface projects/tags in the spec page summary

**Feature**: FEAT-576 — SDD Document Taxonomy (`projects` and `tags` frontmatter)
**Spec**: `sdd/specs/sdd-spec-changes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3459
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 6** (goal G7, AC9). `SDDGraphIngest._process_spec_file` builds
the `spec:` wiki page summary; adding projects/tags there makes `wikitoolkit query "<tag>"`
find specs by tag. Untagged specs must keep a byte-identical summary.

---

## Scope

- In `_process_spec_file`, call `parse_taxonomy(spec_path)`; on `ValidationError` log a
  warning and use an empty `DocTaxonomy` — the page is still produced.
- Build the summary as
  `SDD specification for <slug> (type: <t>, base: <b>; projects: a, b; tags: x, y)`,
  omitting `; projects: …` / `; tags: …` when that list is empty.
- New test file `tests/knowledge/wiki/test_ledger_sdd_ingest_taxonomy.py`.

**NOT in scope**: new edges/pages for tags; the task-index ingest (`_ingest_tasks`);
changes to `WikiPageRecord`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py` | MODIFY | taxonomy in summary |
| `tests/knowledge/wiki/test_ledger_sdd_ingest_taxonomy.py` | CREATE | summary tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.sdd_meta import parse as parse_spec_meta  # verified: sdd_ingest.py:18
from parrot.knowledge.wiki.ledger.sdd_meta import DocTaxonomy, parse_taxonomy  # created by TASK-3459
from parrot.knowledge.wiki.ledger.sdd_ingest import SDDGraphIngest   # verified: tests/knowledge/wiki/test_ledger_sdd_ingest.py:10
from pydantic import ValidationError
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py
logger = logging.getLogger(__name__)                                  # line 24
class SDDGraphIngest:                                                 # line 27
    def __init__(self, store: "LedgerStore", shared_root: Path) -> None:  # line 30
    def _process_spec_file(self, spec_path: Path) -> tuple[WikiPageRecord, list[tuple]] | None:  # line 111 (SYNC; runs via asyncio.to_thread)
        # line 120: spec_filename = spec_path.stem
        # line 124: meta = parse_spec_meta(spec_path)
        # line 134: summary=f"SDD specification for {spec_filename} (type: {meta.type}, base: {meta.base_branch})",
        # line 147: except Exception as e: logger.error("Error processing spec file %s: %s", spec_path, e); return None
```
- Tests can call `SDDGraphIngest(MagicMock(), tmp_path)._process_spec_file(path)` directly —
  it is sync and touches no store (verified: lines 118-145 only read the file).
- `spec_path.relative_to(self.shared_root)` is used for `source_id` (line 136) — the test file
  must live under the `shared_root` passed to the constructor.

### Does NOT Exist
- ~~`WikiPageRecord.tags`~~ — no tags field; taxonomy goes into `summary` only
- ~~`SDDGraphIngest._ingest_tags`~~ — do not add tag pages/edges

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_sdd_ingest_taxonomy.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py#SDDGraphIngest._process_spec_file"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The `ValidationError` must be caught **locally** around `parse_taxonomy` — otherwise the
  outer `except Exception` (line 147) drops the whole page, violating AC9/spec M6.
- No new async code: this method runs in `asyncio.to_thread` (line 73).

---

## Implementation Blueprint

### Steps (in order)
1. Extend the import at line 18 — *why*: reuse the same module the flow parser comes from.
2. Add a private `_taxonomy_suffix` helper and use it in the summary — *why*: keeps the f-string readable and the "omit when empty" rule in one place.
3. Write the three tests.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.wiki.ledger.sdd_meta import parse as parse_spec_meta' sdd_ingest.py)
# REPLACE line 18 with:
from pydantic import ValidationError

from parrot.knowledge.wiki.ledger.sdd_meta import DocTaxonomy, parse_taxonomy
from parrot.knowledge.wiki.ledger.sdd_meta import parse as parse_spec_meta
```

### `sdd_ingest.py` (MODIFY — module-level helper, above `class SDDGraphIngest:`)
```python
# occurrences: 1 (verified: grep -c '^class SDDGraphIngest:' sdd_ingest.py)
def _taxonomy_suffix(taxonomy: DocTaxonomy) -> str:
    """Return ``"; projects: a, b; tags: x"`` — each segment omitted when its list is empty."""
    # FILL IN: join non-empty segments; "" when both empty — bounded by AC9 byte-identical rule
    raise NotImplementedError
```

### `sdd_ingest.py` (MODIFY — inside `_process_spec_file`)
```python
# occurrences: 1 (verified: grep -c 'meta = parse_spec_meta(spec_path)' sdd_ingest.py)
# AFTER — insert below `meta = parse_spec_meta(spec_path)` (verified: sdd_ingest.py:124)
            try:
                taxonomy = parse_taxonomy(spec_path)
            except ValidationError as exc:
                logger.warning("Invalid projects/tags in %s, ingesting without taxonomy: %s", spec_path, exc)
                taxonomy = DocTaxonomy()

# and REPLACE line 134 with:
                summary=(
                    f"SDD specification for {spec_filename} "
                    f"(type: {meta.type}, base: {meta.base_branch}{_taxonomy_suffix(taxonomy)})"
                ),
```
**Why**: exact summary format fixed by spec §3 M6.

### FILL IN checklist
- [ ] `_taxonomy_suffix` — segment joining; bounded by AC9

---

## Acceptance Criteria

- [ ] Summary contains `; projects: a; tags: x` when present (AC9)
- [ ] Summary is byte-identical to the old format when both lists are empty (AC9)
- [ ] Invalid taxonomy → page still produced, warning logged
- [ ] Existing `tests/knowledge/wiki/test_ledger_sdd_ingest.py` passes unmodified

---

## Validation Commands
- `pytest tests/knowledge/wiki/test_ledger_sdd_ingest_taxonomy.py -q`
- `pytest tests/knowledge/wiki/test_ledger_sdd_ingest.py -q`

---

## Test Specification

```python
# tests/knowledge/wiki/test_ledger_sdd_ingest_taxonomy.py
"""FEAT-576: projects/tags in the SDD spec page summary."""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parrot.knowledge.wiki.ledger.sdd_ingest import SDDGraphIngest


def _spec(root: Path, front: str) -> Path:
    p = root / "sdd" / "specs" / "demo.spec.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntype: feature\nbase_branch: dev\n{front}---\n# Demo\n", encoding="utf-8")
    return p


def test_ingest_summary_with_taxonomy(tmp_path: Path) -> None:
    page, _ = SDDGraphIngest(MagicMock(), tmp_path)._process_spec_file(_spec(tmp_path, "projects: [ai-parrot]\ntags: [x]\n"))
    assert page.summary == "SDD specification for demo.spec (type: feature, base: dev; projects: ai-parrot; tags: x)"


def test_ingest_summary_untagged_unchanged(tmp_path: Path) -> None:
    page, _ = SDDGraphIngest(MagicMock(), tmp_path)._process_spec_file(_spec(tmp_path, ""))
    assert page.summary == "SDD specification for demo.spec (type: feature, base: dev)"


def test_ingest_invalid_taxonomy_still_ingests(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        result = SDDGraphIngest(MagicMock(), tmp_path)._process_spec_file(_spec(tmp_path, "tags: ['!!']\n"))
    assert result is not None
    assert "Invalid projects/tags" in caplog.text
```

---

## Agent Instructions

1. Read spec §3 Module 6. Confirm TASK-3459 is done.
2. Implement; run Validation Commands with `PYTHONPATH=packages/ai-parrot/src` inside a worktree.
3. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-coder (native, sonnet), via sdd-worker orchestration (FEAT-549)
**Date**: 2026-09-19
**Notes**: `SDDGraphIngest._process_spec_file` now calls `parse_taxonomy(spec_path)`,
catching `ValidationError` locally (logs a warning, falls back to empty
`DocTaxonomy` so the page is still produced). Added `_taxonomy_suffix()` helper
building `; projects: a, b; tags: x, y`, omitting either segment when empty
(byte-identical to the pre-FEAT-576 summary when both empty, per AC9), wired
into the summary f-string.

Verification: `pytest tests/knowledge/wiki/test_ledger_sdd_ingest_taxonomy.py
tests/knowledge/wiki/test_ledger_sdd_ingest.py -q` → 12 passed (3 new + 9
pre-existing unmodified).

Review: no defects found (`coder-review:17d8c0c020f0939130b9ed69`), fix_commits=[].

Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a

**Deviations from spec**: none
