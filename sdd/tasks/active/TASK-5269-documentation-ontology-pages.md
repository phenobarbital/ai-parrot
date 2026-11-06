# TASK-5269: Documentation — wiki/knowledge/ontology-backend-programme.md, wiki/knowledge/ontology-vocabulary-store.md

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5250, TASK-5251, TASK-5264, TASK-5266, TASK-5267, TASK-5268
**Assigned-to**: unassigned

---

## Context

Spec Module 12 and §10 Documentation (`docs.policy: required`). Two wiki pages from the
techwiki template: the ArangoDB retirement programme and the vocabulary store. Runs last because
it documents the delivered symbols and the G1 verdict.

---

## Scope

- `wiki/knowledge/ontology-backend-programme.md` — create: plane-to-destination table (spec §2
  "Programme architecture"), binding decisions D-P1…D-P7, phases and gates (roadmap + retirement
  gate), the G1 verdict from `sdd/state/FEAT-824/g1/report.md`, the ADR link
  (`docs/decisions/graph-backends-postgres-surrealdb.md`), and what is and is not removed yet.
- `wiki/knowledge/ontology-vocabulary-store.md` — create: data model and temporal semantics,
  publishing Turtle, validation rules and issue codes, `resolve` and `expand`, snapshots and offline
  use, the `ONTOLOGY_*` settings table, the `parrot ontology` CLI, the HTTP routes, and how the
  concept catalog publishes into it. Public API links to `parrot.knowledge.ontology.vocabulary` symbols.
- Both pages follow `sdd/templates/techwiki-page.md` (frontmatter `title`, `summary`; sections
  Purpose, Public API, Configuration & Parameters, Usage Examples, Gotchas, Related).

**NOT in scope**: editing existing wiki pages beyond adding a "Related" link if one is clearly
needed (list it in the note).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/knowledge/ontology-backend-programme.md` | CREATE | programme page |
| `wiki/knowledge/ontology-vocabulary-store.md` | CREATE | vocabulary-store page |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_docs.py` | CREATE | page-shape test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Public API (for ref: links) — created by TASK-5253…5268:
from parrot.knowledge.ontology.vocabulary import (
    OntologyStore, OntologyPublisher, PostgresOntologyStore, PostgresOntologyPublisher, SnapshotOntologyStore,
    create_ontology_store, register_vocabulary_backend, ConceptRef, Resolution, PublishResult, StoreStatus)
```

### Existing Signatures to Use
```text
sdd/templates/techwiki-page.md      # page template (frontmatter title/summary; six sections)
sdd/specs/ontology-backend.spec.md  # §2 (architecture, data model, settings), §10 (page contents)
# Delivered sources the pages document (read them, document what they actually do):
sdd/state/FEAT-824/g1/report.md                                                   # TASK-5250 — G1 verdict
docs/decisions/graph-backends-postgres-surrealdb.md                               # TASK-5251 — ADR
packages/ai-parrot/tests/knowledge/ontology/vocabulary/store_conformance.py       # TASK-5264 — behaviour guaranteed by ALL_CASES
packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py        # TASK-5266 — vocabulary_publisher hook
packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/cli.py                # TASK-5267 — `parrot ontology` subcommands
packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/http.py               # TASK-5268 — HTTP routes and auth rules
```

### Does NOT Exist
- ~~`wiki/knowledge/ontology-*.md`~~ — created here.
- Verify every symbol you link with `wikitoolkit symbols lookup <name>` before linking; do not
  document a symbol that the delivered code does not have.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/knowledge/ontology-backend-programme.md", "action": "CREATE"},
    {"path": "wiki/knowledge/ontology-vocabulary-store.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read the delivered modules and the G1 report — *why*: pages describe what shipped, not the plan.
2. Write both pages from the template.
3. Run `parrot sdd techwiki check`.

### `wiki/knowledge/ontology-vocabulary-store.md` (CREATE)
```markdown
---
title: Ontology vocabulary store
summary: Versioned RDF vocabularies on PostgreSQL with offline SQLite snapshots (FEAT-824).
---

# Ontology vocabulary store

## Purpose
<!-- FILL IN: what the store is, the two stores of the programme, when to use resolve/expand -->

## Public API
- [`OntologyStore`](ref:parrot.knowledge.ontology.vocabulary.OntologyStore) — read contract
<!-- FILL IN: remaining public names -->

## Configuration & Parameters
<!-- FILL IN: ONTOLOGY_* table, CLI subcommands, HTTP routes -->

## Usage Examples
<!-- FILL IN: publish Turtle via CLI; resolve + expand in Python; offline snapshot -->

## Gotchas
<!-- FILL IN: schema name ontology_store (not ontology); blank nodes rejected; embedding dim fixed at
     schema creation; trigram parity; cross-ontology parents; IRIs cannot be renamed -->

## Related
- [Ontology backend programme](ontology-backend-programme.md) — phases and the ArangoDB retirement
```
`ontology-backend-programme.md` follows the same template with the programme content of Scope.

### `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_docs.py` (CREATE)
```python
"""The FEAT-824 documentation pages exist and follow the techwiki template."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[6]
PAGES = ["wiki/knowledge/ontology-backend-programme.md", "wiki/knowledge/ontology-vocabulary-store.md"]
SECTIONS = ["## Purpose", "## Public API", "## Configuration & Parameters", "## Usage Examples", "## Gotchas", "## Related"]


@pytest.mark.parametrize("page", PAGES)
def test_page_follows_template(page: str) -> None:
    text = (ROOT / page).read_text(encoding="utf-8")
    assert text.startswith("---\n") and "\ntitle:" in text and "\nsummary:" in text
    for section in SECTIONS:
        assert section in text, (page, section)
    assert "FILL IN" not in text
```
(`parents[6]` of `packages/ai-parrot/tests/knowledge/ontology/vocabulary/<file>` is the repo root —
same depth as `tests/knowledge/wiki/decisions/test_seed_rules.py`, which uses `parents[6]`.)

### FILL IN checklist
- [ ] both pages' sections.
- [ ] G1 verdict quoted from the committed report.

---

## Acceptance Criteria

- [ ] Both pages exist under `wiki/knowledge/` and follow the techwiki template.
- [ ] `parrot sdd techwiki check --spec sdd/specs/ontology-backend.spec.md --root .` passes.
- [ ] Every linked symbol exists in the delivered code.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_docs.py -q`

Also run (acceptance, not a registered test runner):
`parrot sdd techwiki check --spec sdd/specs/ontology-backend.spec.md --root .`

---

## Agent Instructions

1. Work in the feature worktree; confirm every `Depends-on` task is `done`.
2. Mark `in-progress`; write the pages; run the Validation Commands.
3. Commit only the listed files; close with `parrot sdd task close TASK-5269 ontology-backend verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
