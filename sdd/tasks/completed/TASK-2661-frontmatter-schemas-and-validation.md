# TASK-2661: §10 frontmatter schemas + §34 validation (QA oracle)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2660
**Assigned-to**: unassigned

---

## Context

The **shared contract** every other node depends on (spec Module 5). Freeze first.
Pydantic models for all contract §10 page types + the §34 Post-Operation Validation
checklist as an executable function (the QA oracle).

## Scope

- `models.py`: one Pydantic model per §10 page type — meeting-source (§10.1), project (§10.2), entity (§10.3), concept (§10.4), contradiction (§10.5), daily-note (§10.6), synthesis (§10.7); plus `Classification`, `MeetingExtraction`, `ValidationResult`.
- Enforce **D1** (`raw_summary`/`raw_transcript` are plain relative paths — reject `[[...]]`), **D2** (`primary_project ∈ projects`), **D4** (`source_id = "fireflies:<id>"`).
- `validation.py`: `validate(ctx) -> ValidationResult` covering §34's four groups (source / knowledge / Obsidian / operational) **plus**: §19 diff-guard (Q2 — no live-sourced claim dropped), `Private/`-never-accessed, new wikilinks resolve (§8.1), Obsidian-safe filenames (§8.2), no fabricated-looking values (rule #12).

**NOT in scope**: rendering, extraction, orchestration.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/models.py` | CREATE | §10 Pydantic schemas + node contracts |
| `.../wiki_ingest/validation.py` | CREATE | executable §34 checklist |
| `packages/ai-parrot/tests/unit/test_wiki_kb_models.py` | CREATE | validator + invariant tests |

## Codebase Contract (Anti-Hallucination)
### Verified Imports
```python
from pydantic import BaseModel, Field, field_validator   # pydantic v2 (already required)
```
### Notes
- `source_id` identity aligns with FEAT-472 `external_id` (`agents/meeting_registry.py`).
- See spec §2 Data Models + §6 for the full field lists.
### Does NOT Exist
- ~~any existing "wiki page frontmatter" Pydantic model~~ — create fresh here.

## Implementation Notes
- Field types match contract §10 exactly (headings/keys verbatim). Validators raise `ValueError` with clear messages.
- `ValidationResult(passed: bool, failures: list[str], warnings: list[str])`.

## Acceptance Criteria
- [ ] `primary_project ∉ projects` fails validation (D2).
- [ ] A `[[...]]` value in `raw_transcript`/`raw_summary` fails (D1).
- [ ] `validate()` returns structured pass/fail covering all §34 groups + the extra assertions.
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
def test_primary_project_invariant(): ...
def test_raw_provenance_plain_paths(): ...
def test_validate_flags_dangling_wikilink_and_fabrication(): ...
```

### Completion Note

`models.py`: one Pydantic model per §10 page type (meeting-source,
project, entity, concept, contradiction, daily-note, synthesis) with
field names/enums verbatim from
`sdd/references/obsidian-wiki-operating-contract.md` §10, plus
`Classification`/`ActionItem`/`MeetingExtraction`/`ValidationResult`.
D1 (plain-path raw provenance), D2 (`primary_project ∈ projects`), and D4
(`source_id = "fireflies:<id>"`) are enforced as Pydantic
field/model validators that raise with the decision label (`D1`/`D2`/`D4`)
in the message.

`validation.py`: `ValidationContext` (evidence bag — every field
defaults to "nothing to check" so a partial/unit-test context validates
cleanly) + `validate(ctx) -> ValidationResult`, covering all four §34
groups (source/knowledge/Obsidian/operational integrity) plus the Q2
diff-guard, `Private/`-never-accessed, §8.1 dangling-wikilink, §8.2
unsafe-filename, and rule #12 no-fabrication assertions. Later
pipeline nodes (Modules 6-14) populate the context fields relevant to
the operation they performed.

Verified: `pytest packages/ai-parrot/tests/unit/test_wiki_kb_models.py`
(13 passed); `ruff check` clean.
