# TASK-3460: Add `projects` / `tags` keys to the three SDD templates

**Feature**: FEAT-576 — SDD Document Taxonomy (`projects` and `tags` frontmatter)
**Spec**: `sdd/specs/sdd-spec-changes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3459
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 2** (goal G1, AC1). The templates are what every authoring
command copies; once they carry the commented `projects: []` / `tags: []` keys, new
brainstorms, proposals and specs get them by default.

---

## Scope

- Insert the taxonomy block (below) into the frontmatter of `sdd/templates/spec.md`,
  `sdd/templates/brainstorm.md` and `sdd/templates/proposal.md`.
- Write `tests/sdd_scripts/test_template_taxonomy.py`.

**NOT in scope**: `sdd/templates/task.md` (tasks inherit their spec's taxonomy); adding any
`**Projects**:` body line (frontmatter is the single source — spec M2); command `.md` files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/spec.md` | MODIFY | taxonomy keys after `base_branch: dev` |
| `sdd/templates/brainstorm.md` | MODIFY | taxonomy keys after `base_branch: dev` |
| `sdd/templates/proposal.md` | MODIFY | taxonomy keys after `base_branch: dev` |
| `tests/sdd_scripts/test_template_taxonomy.py` | CREATE | templates parse + declare both keys |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.sdd_meta import DocTaxonomy, parse_taxonomy  # created by TASK-3459 (re-exported in scripts/sdd/sdd_meta.py)
```

### Existing Signatures to Use
```text
sdd/templates/spec.md        lines 1-7: '---', 3 comment lines, 'type: feature' (5), 'base_branch: dev' (6), '---' (7)
sdd/templates/brainstorm.md  lines 1-7: identical frontmatter shape to spec.md
sdd/templates/proposal.md    lines 1-19: id/title/slug/type/mode/status/source(nested)/overall_confidence,
                             'base_branch: dev' (15), research_state (16), created (17), updated (18), '---' (19)
```
- `proposal.md`'s `type: feature | hotfix | bug-investigation` is a placeholder string —
  `parse()` rejects it, `parse_taxonomy()` ignores it. Tests MUST use `parse_taxonomy` only.
- `.gitignore` has a global `templates/` rule, but these three files are already tracked, so
  plain `git add` works for MODIFY (see CLAUDE.md heads-up). Do not create new template files.

### Does NOT Exist
- ~~`sdd/templates/*.md` `projects:`/`tags:` keys~~ — added by this task
- ~~a template-rendering script~~ — commands copy the templates by hand

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/templates/spec.md", "action": "MODIFY"},
    {"path": "sdd/templates/brainstorm.md", "action": "MODIFY"},
    {"path": "sdd/templates/proposal.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_template_taxonomy.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- The block text is fixed by spec §2 Overview — copy it verbatim.
- YAML comments must stay valid YAML (they are ignored by `yaml.safe_load`).

---

## Implementation Blueprint

### Steps (in order)
1. Insert the block below the `base_branch: dev` line in each template — *why*: groups the
   metadata a human edits first; for proposal.md it keeps the flow keys together.
2. Write the test and run it — *why*: locks AC1 so later template edits cannot drop the keys.

### `sdd/templates/spec.md` and `sdd/templates/brainstorm.md` (MODIFY)
```yaml
# occurrences: 1 per file (verified: grep -c '^base_branch: dev$' sdd/templates/spec.md sdd/templates/brainstorm.md)
# AFTER — insert below `base_branch: dev` (verified: spec.md:6, brainstorm.md:6)
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: []
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: []
```
**Why**: spec §2 Overview fixes this exact block for all three templates (G1).

### `sdd/templates/proposal.md` (MODIFY)
```yaml
# occurrences: 1 (verified: grep -c '^base_branch: dev$' sdd/templates/proposal.md)
# AFTER — insert below `base_branch: dev` (verified: proposal.md:15)
<the same six lines as above>
```

### `tests/sdd_scripts/test_template_taxonomy.py` (CREATE)
```python
"""FEAT-576: every SDD authoring template declares the taxonomy keys."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sdd.sdd_meta import DocTaxonomy, parse_taxonomy

TEMPLATES = Path(__file__).resolve().parents[2] / "sdd" / "templates"


@pytest.mark.parametrize("name", ["spec.md", "brainstorm.md", "proposal.md"])
def test_templates_declare_taxonomy_keys(name: str) -> None:
    path = TEMPLATES / name
    text = path.read_text(encoding="utf-8")
    front = text.split("---", 2)[1]
    assert "\nprojects: []\n" in front
    assert "\ntags: []\n" in front
    assert parse_taxonomy(path) == DocTaxonomy()
```

### FILL IN checklist
- [ ] none beyond copying the block into the 3 templates (proposal.md position differs)

---

## Acceptance Criteria

- [ ] All three templates contain `projects: []` and `tags: []` plus the two comment lines (AC1)
- [ ] `parse_taxonomy` on each template returns an empty `DocTaxonomy`
- [ ] `tests/sdd_scripts/test_design_research_templates.py` still passes (it reads `sdd/templates/`)

---

## Validation Commands
- `pytest tests/sdd_scripts/test_template_taxonomy.py -q`
- `pytest tests/sdd_scripts/test_design_research_templates.py -q`

---

## Test Specification

See the CREATE block above — it is the complete test file.

---

## Agent Instructions

1. Read spec §2 Overview (the YAML block) and §3 Module 2.
2. Confirm TASK-3459 is done (`parse_taxonomy` importable).
3. Apply the edits, run the Validation Commands, fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
