# TASK-2398: Extend `ConceptType` with `Issue`, `Person`, `Project`

**Feature**: FEAT-454 — Jira Ticket Extractor → LLM Wiki (`issues` namespace)
**Spec**: `sdd/specs/jira-extractor-llmwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 6** of the spec (§3 M6, G11). The renderer (TASK-2401)
emits `type: Issue` into every ticket document's frontmatter. For that value
to be a *controlled-vocabulary* member rather than a look-alike string,
`ConceptType` must carry it. This is the only leaf task with no dependencies
and it unblocks the renderer, so it goes first.

Purely additive. The module's own design note (`ontology.py` docstring lines
13-14) states that existing member **values** must remain identical strings —
this task must not touch any of them.

---

## Scope

- Add three members to `ConceptType` in
  `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py`:
  - `ISSUE = "Issue"`
  - `PERSON = "Person"`
  - `PROJECT = "Project"`
- Place them in a new, commented section (`# --- Jira / work-tracking types
  (FEAT-454) ---`) mirroring how FEAT-239 / FEAT-260 / FEAT-216 grouped their
  additions.
- Update the module docstring's "Design notes" with a FEAT-454 line, matching
  the existing FEAT-239 / FEAT-240 convention.
- Write the unit test proving the addition is additive.
- Verify (with a test, not by inspection) that the two consumers which
  enumerate `ConceptType` into an LLM prompt or a validation list do not
  regress.

**NOT in scope**:
- Adding anything to `RelationType`. `BLOCKS` / `DUPLICATES` / `RELATES_TO`
  are explicitly **not** added by this feature (§6 "Does NOT Exist"); link
  precision lives in the ticket frontmatter and the graph edge stays
  `references`.
- Touching `CATEGORY_TO_OKF_TYPE` or `okf_type` in `export.py` — no change
  needed (see the Codebase Contract caveat below).
- Touching `scan_vault`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` | MODIFY | Add `ISSUE`/`PERSON`/`PROJECT` to `ConceptType`; docstring note |
| `packages/ai-parrot/tests/knowledge/okf/test_concept_type_feat454.py` | CREATE | Additive-vocabulary + consumer-regression tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against the working tree on 2026-08-24 at commit
> `53df566ef`. Confirm each anchor before writing code.

### Verified Imports

```python
from parrot.knowledge.okf.ontology import ConceptType, RelationType, RelatesTo
from parrot.knowledge.okf import ConceptType  # re-exported: okf/__init__.py:15-30
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/okf/ontology.py:29
class ConceptType(str, Enum):
    # --- Existing PageIndex types (values unchanged) ---
    SECTION = "Section"; POLICY = "Policy"; CONTROL = "Control"
    SAFEGUARD = "Safeguard"; EVIDENCE = "Evidence"; PLAYBOOK = "Playbook"
    PROCEDURE = "Procedure"; STANDARD = "Standard"; FRAMEWORK = "Framework"
    REGULATION = "Regulation"; GUIDELINE = "Guideline"
    # --- New graph-native types (FEAT-239) ---
    SYMBOL = "Symbol"; RATIONALE = "Rationale"; SKILL = "Skill"
    CONCEPT_NODE = "Concept"; DOCUMENT_NODE = "Document"
    # --- Wiki page types (FEAT-260) ---
    WIKI_SUMMARY = "Wiki Summary"; WIKI_ENTITY = "Wiki Entity"
    WIKI_COMPARISON = "Wiki Comparison"; WIKI_SYNTHESIS = "Wiki Synthesis"
    WIKI_OVERVIEW = "Wiki Overview"
    # --- Work-lineage types ---
    RUN = "Run"; CLAIM = "Claim"
    # --- Open-vocabulary fallback (FEAT-216) ---
    OTHER = "Other"
# ^ 24 members today. Docstring lines 13-14 are the "values MUST remain
#   identical strings" design note this task must respect.
```

**The two enumerating consumers to regression-test** (§7 "Known Risks"):

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/migrate.py:134-138
#   builds an LLM classification prompt from
#   ', '.join(t.value for t in ConceptType)
# packages/ai-parrot-tools/src/parrot_tools/obsidian.py:749
#   validates against sorted(item.value for item in ConceptType)
```
Verify both line numbers with `grep -n 'ConceptType' <file>` before asserting
on them; if they moved, assert on behaviour (the joined/sorted string
contains the three new values) rather than on a line number.

### Does NOT Exist

- ~~`ConceptType.ISSUE` / `.PERSON` / `.PROJECT`~~ — this task creates them.
- ~~`RelationType.BLOCKS` / `.DUPLICATES` / `.RELATES_TO`~~ — not in the
  vocabulary (`ontology.py:77-114`) and **not added by this feature**.
- ~~`ConceptType.TICKET` / `.JIRA_ISSUE` / `.USER`~~ — do not invent
  alternative names. The three values are exactly `Issue`, `Person`,
  `Project`.
- ~~`export.py::_okf_type_for`~~ — the real helper is `okf_type`
  (`export.py:71`). **Caveat**: `scan_vault` hard-codes `category="document"`
  on every note page (`vault_scan.py:166`), so no issues-plane page will
  carry category `issue`. These enum members are consumed via the markdown
  frontmatter `type:` key, **not** via `WikiPageRecord.category`. Do not
  "fix" `export.py` or `scan_vault` to close that gap — out of scope.

---

## Implementation Notes

### Pattern to Follow

Copy the existing section style verbatim:

```python
    # --- Work-lineage types (graph-knowledge-persistence) ---
    RUN = "Run"
    CLAIM = "Claim"

    # --- Jira / work-tracking types (FEAT-454) ---
    ISSUE = "Issue"
    PERSON = "Person"
    PROJECT = "Project"
```

Insert **before** the `OTHER = "Other"` fallback block so the open-vocabulary
fallback stays visually last, matching its comment ("Open-vocabulary
fallback").

### Key Constraints

- Additive only. Do not reorder, rename, or re-value any existing member.
- `ConceptType` is a `str, Enum` — members are usable directly as strings.
- No new imports needed.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/okf/ontology.py` — the file itself;
  FEAT-239/260/216 additions are the precedent.
- `packages/ai-parrot/tests/knowledge/okf/` — existing test location.

---

## Acceptance Criteria

- [ ] `ConceptType.ISSUE.value == "Issue"`, `ConceptType.PERSON.value ==
      "Person"`, `ConceptType.PROJECT.value == "Project"`.
- [ ] Every member that existed before this task still has its original
      `.value` (asserted against a hard-coded frozen list of the 24
      pre-existing `(name, value)` pairs — **G11**).
- [ ] `len(ConceptType) == 27`.
- [ ] The `migrate.py` classification-prompt string and the `obsidian.py`
      validation list both include the three new values (no consumer raises).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/okf/test_concept_type_feat454.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/okf/ontology.py`
- [ ] `RelationType` is unchanged (asserted).

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/okf/test_concept_type_feat454.py
import pytest

from parrot.knowledge.okf.ontology import ConceptType, RelationType

# Frozen snapshot of the vocabulary BEFORE FEAT-454. Any diff here is a
# breaking change to YAML frontmatter parsing across every index.
PRE_FEAT454: dict[str, str] = {
    "SECTION": "Section", "POLICY": "Policy", "CONTROL": "Control",
    "SAFEGUARD": "Safeguard", "EVIDENCE": "Evidence", "PLAYBOOK": "Playbook",
    "PROCEDURE": "Procedure", "STANDARD": "Standard",
    "FRAMEWORK": "Framework", "REGULATION": "Regulation",
    "GUIDELINE": "Guideline", "SYMBOL": "Symbol", "RATIONALE": "Rationale",
    "SKILL": "Skill", "CONCEPT_NODE": "Concept", "DOCUMENT_NODE": "Document",
    "WIKI_SUMMARY": "Wiki Summary", "WIKI_ENTITY": "Wiki Entity",
    "WIKI_COMPARISON": "Wiki Comparison", "WIKI_SYNTHESIS": "Wiki Synthesis",
    "WIKI_OVERVIEW": "Wiki Overview", "RUN": "Run", "CLAIM": "Claim",
    "OTHER": "Other",
}

NEW_MEMBERS = {"ISSUE": "Issue", "PERSON": "Person", "PROJECT": "Project"}


class TestConceptTypeAdditive:
    def test_new_members_exist_with_exact_values(self):
        """G11: the three new members carry exactly these strings."""
        for name, value in NEW_MEMBERS.items():
            assert getattr(ConceptType, name).value == value

    def test_no_preexisting_value_changed(self):
        """The additive guarantee: every old member keeps its old value."""
        for name, value in PRE_FEAT454.items():
            assert getattr(ConceptType, name).value == value, name

    def test_vocabulary_size(self):
        assert len(ConceptType) == len(PRE_FEAT454) + len(NEW_MEMBERS) == 27

    def test_relation_type_untouched(self):
        """This feature adds no edge kinds (spec §6 Does NOT Exist)."""
        for absent in ("BLOCKS", "DUPLICATES", "RELATES_TO", "BLOCKED_BY"):
            assert not hasattr(RelationType, absent)


class TestEnumeratingConsumers:
    """§7 risk: ConceptType is enumerated into a prompt and a validator."""

    def test_migrate_prompt_includes_new_values(self):
        from parrot.knowledge.pageindex.okf import migrate  # noqa: F401
        joined = ", ".join(t.value for t in ConceptType)
        for value in NEW_MEMBERS.values():
            assert value in joined

    def test_obsidian_validation_list_includes_new_values(self):
        allowed = sorted(item.value for item in ConceptType)
        for value in NEW_MEMBERS.values():
            assert value in allowed

    def test_str_enum_usable_as_string(self):
        assert ConceptType.ISSUE == "Issue"
        assert f"{ConceptType.ISSUE.value}" == "Issue"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jira-extractor-llmwiki.spec.md` (§3 M6, G11, §7 "Known Risks") for full context
2. **Check dependencies** — none; this task is a leaf and may start immediately
3. **Verify the Codebase Contract** — before writing ANY code:
   - `grep -n 'ConceptType' packages/ai-parrot/src/parrot/knowledge/okf/ontology.py`
   - Re-derive the `PRE_FEAT454` snapshot from the real file; if it differs
     from the table above, fix the table in this task file FIRST, then implement
   - Locate the two enumerating consumers by grep, not by trusting line numbers
4. **Update status** in `sdd/tasks/index/jira-extractor-llmwiki.json` → `"in-progress"`
5. **Implement** following the scope and notes above — additive only
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2398-okf-concept-type-issue-person-project.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
