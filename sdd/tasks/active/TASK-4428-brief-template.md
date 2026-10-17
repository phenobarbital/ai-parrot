# TASK-4428: Brief document template (`sdd/templates/brief.md`)

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4425
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 and §2 "The brief document". `/sdd-brief` fills this
template to produce `sdd/briefs/<slug>.brief.md`. Its frontmatter must parse
as `BriefMeta` (TASK-4425) once placeholders are substituted, and its body
carries the sections every implementer reads: Problem · Root cause ·
Research findings · Decisions / Assumptions · Fix plan · Validation
commands. Task details do **not** live here — they are materialized as
standard task files (spec §2 "Task materialization").

---

## Scope

- Create `sdd/templates/brief.md`: frontmatter block with every `BriefMeta`
  field as a placeholder, then the six body sections, each with a one-line
  guidance comment. Root cause section states the research floor (S9):
  source, root-cause statement, ≥1 verified `path:line` anchor.
- Create `tests/sdd_scripts/test_brief_template_contract.py`: substitute the
  placeholders with sample values and assert `parse_brief` accepts the
  result; assert the six section headings exist.
- `git add -f` the template — `.gitignore` has a global `templates/` rule.

**NOT in scope**: the task-file template (reuse `sdd/templates/task.md`
unchanged); writing `/sdd-brief` itself (TASK-4429).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/brief.md` | CREATE | Brief template (needs `git add -f`) |
| `tests/sdd_scripts/test_brief_template_contract.py` | CREATE | Template parses + has the sections |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.brief_meta import parse_brief  # created by TASK-4425
```

### Existing Signatures to Use
```python
# scripts/sdd/brief_meta.py (TASK-4425)
def parse_brief(doc_path: Path) -> BriefMeta     # ValueError (no frontmatter) / ValidationError
# BriefMeta fields: kind, slug, key, base_branch, source{type, ref, url}, jira_issue_key, ledger_issue, created
```
- `.gitignore` global `templates/` rule — CLAUDE.md "Heads-up" (line ~245 of .gitignore); existing `sdd/templates/*.md` were tracked before it, a NEW one needs `git add -f`.

### Does NOT Exist
- ~~`sdd/templates/brief.md`~~ — created here.
- ~~a `type:` frontmatter key in briefs~~ — must not appear (it is `FlowMeta`'s key).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "sdd/templates/brief.md", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_brief_template_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Placeholders use `<angle>` tokens inside the YAML values (e.g.
  `slug: <slug>`) so the test can substitute them with `str.replace`.
- `source:` is a nested mapping (`type`, `ref`, `url`).
- `ledger_issue` and `jira_issue_key` placeholders default to `null`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the template — *why*: the command fills it verbatim.
2. Write the contract test — *why*: it keeps the template parseable as `BriefMeta` (AC-1).
3. `git add -f sdd/templates/brief.md` — *why*: the `templates/` ignore rule would otherwise drop it silently.

### `sdd/templates/brief.md` (CREATE)
```markdown
---
kind: brief
slug: <slug>
key: <key>
base_branch: <base_branch>
source:
  type: <source_type>
  ref: <source_ref>
  url: <source_url>
jira_issue_key: null
ledger_issue: null
created: <created>
---

# Brief: <Title>

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

## Problem
<!-- What is broken, for whom, and how it was observed (quote the source). -->

## Root cause
<!-- Research floor (required in every mode, including --research light):
     the fetched source, a one-paragraph root-cause statement, and at least one
     verified `path:line` anchor. Without these /sdd-brief creates no worktree. -->

## Research findings
<!-- Symbols touched, blast radius, related ledger issues, prior art. -->

## Decisions
<!-- Answers from the Q&A round. With --no-interview, rename to "## Assumptions". -->

## Fix plan
<!-- Ordered steps; one bullet per materialized task file (HOTFIX-<KEY>-N). -->

## Validation commands
<!-- File-level pytest only, e.g. `pytest path/to/test_file.py -q`. -->
```
**Why this shape**: frontmatter keys mirror `BriefMeta` field-for-field so
`parse_brief` is the single validator; the Root cause comment is where the
S9 research floor becomes visible to whoever fills the template.

### `tests/sdd_scripts/test_brief_template_contract.py` (CREATE)
```python
"""Contract: sdd/templates/brief.md stays parseable as BriefMeta — FEAT-698 / TASK-4428."""

from __future__ import annotations

from pathlib import Path

from scripts.sdd.brief_meta import parse_brief

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO_ROOT / "sdd/templates/brief.md"
_SECTIONS = ("## Problem", "## Root cause", "## Research findings", "## Decisions", "## Fix plan", "## Validation commands")


def test_template_sections_present() -> None:
    text = _TEMPLATE.read_text(encoding="utf-8")
    for heading in _SECTIONS:
        assert heading in text, f"brief template lost section {heading!r}"

# FILL IN: test_filled_template_parses — replace every <placeholder> with a valid sample
#          (slug "demo-fix", key "cs-224", base_branch "main", source_type "code-scanning",
#          source_ref "224", source_url "null", created ISO string), write to tmp_path, assert
#          parse_brief(...).feature_id == "BRIEF-cs-224" (AC-1)
# FILL IN: test_template_has_no_type_key — no line starting with "type:" at frontmatter top level (AC-2)
```

### FILL IN checklist
- [ ] placeholder substitution test — AC-1
- [ ] no top-level `type:` key test — AC-2

---

## Acceptance Criteria

- [ ] AC-1: the template with placeholders substituted parses through `parse_brief`.
- [ ] AC-2: the frontmatter has no top-level `type:` key.
- [ ] AC-3: all six body sections are present.
- [ ] AC-4: `git ls-files sdd/templates/brief.md` lists the file (it was force-added).

---

## Validation Commands

- `pytest tests/sdd_scripts/test_brief_template_contract.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-brief-hotfix-flow --feature-id FEAT-698`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-brief-hotfix-flow.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands from the worktree root
8. **Commit the code** — stage only the files this task lists (`git add -f` for the template)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4428 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
