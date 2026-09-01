# TASK-2665: Summary-first classification + confidence + transcript fallback (§15)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2661, TASK-2662, TASK-2664
**Assigned-to**: unassigned

---

## Context

Spec Module 7. First semantic node: classify the meeting summary-first, assign
confidence, apply the transcript-fallback ladder. Uses the **strong-tier client**.

## Scope

- `nodes/classify.py`: read existing context first (§15.1 — `Wiki/index.md`, `overview.md`, candidate matches via GraphIndex retrieval from TASK-2671 when available); read the Fireflies summary; `strong_client.invoke(output_type=Classification)`.
- Confidence high/medium/low (§15.3); transcript-fallback ladder (§15.4 — read the full transcript only when a trigger applies); set `processing_mode` accordingly.
- Low confidence after fallback (§15.5) → route to `Uncategorized/`, set `review_required: true`, add a `classification` review item, do not update a project.

**NOT in scope**: rendering pages, contradiction detection.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/nodes/classify.py` | CREATE | classification node |
| `packages/ai-parrot/tests/unit/test_wiki_kb_classify.py` | CREATE | confidence + fallback + uncategorized tests |

## Codebase Contract (Anti-Hallucination)
### Verified Imports
```python
# strong client built in TASK-2660; Classification model from TASK-2661
```
### Existing Signatures to Use
```python
# clients/base.py
async def invoke(self, prompt, *, output_type=None, model=None, system_prompt=None,
                 max_tokens=4096, temperature=0.0, ...) -> InvokeResult   # :1747
```
### Does NOT Exist
- ~~any existing meeting-classification function~~ — new here.

## Implementation Notes
- Match-before-create (rule #6): search existing projects/entities/concepts before proposing new ones.
- Summary-first (rule #7): only read the transcript when §15.4 triggers.
- No fabrication (rule #12): unresolved fields → `Unknown`/`Requires review`.

## Acceptance Criteria
- [ ] Returns a validated `Classification` with confidence.
- [ ] Transcript is read only when a §15.4 trigger applies (`processing_mode` set correctly).
- [ ] Low confidence → `Uncategorized/` + `review_required` + review item.
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
async def test_summary_first_no_transcript_when_high_confidence(): ...
async def test_low_confidence_routes_uncategorized(): ...
```
