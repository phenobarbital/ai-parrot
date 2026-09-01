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

### Completion Note

`nodes/classify.py`: `run_classify(strong_client, meeting, *, context=None,
force_transcript=False) -> ClassificationResult`. Summary-first (rule #7):
a single `strong_client.invoke(output_type=Classification)` call reading
only the Fireflies summary + §15.1 existing-context (own
`ExistingContext` model — GraphIndex-backed candidates are best-effort,
since Module 13 is not a Module 7 dependency); §15.4 fallback is decided
deterministically in Python — a keyword scan for HR/legal/security/
compliance/financial content or an explicit `force_transcript` fires
immediately, otherwise a `medium`/`low` confidence from the first pass
triggers one transcript-informed re-classification. `processing_mode`
is set from whether the transcript was actually read, never guessed by
the LLM. §15.5: confidence still `low` after the fallback sets
`review_required=True` + a `ReviewItemDraft` (written by Module 12, not
here) — per this task's scope boundary, the bundle simply stays wherever
Module 3 already placed it (`Uncategorized/`); relocating a *resolved*
classification's client/project is the orchestrator's job (Module 6),
not this node's.

Verified: `pytest packages/ai-parrot/tests/unit/test_wiki_kb_classify.py`
(6 passed — summary-only on high confidence, medium→transcript fallback,
low-confidence review-item draft, high-impact keyword forces transcript
even at high confidence, force_transcript flag, existing-context threaded
into the prompt); `ruff check` clean; `mypy` clean; full wiki-kb suite
(49 tests) stays green.
