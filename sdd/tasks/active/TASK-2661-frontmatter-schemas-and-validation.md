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
