# TASK-2666: Canonical meeting source page renderer (§17)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2661, TASK-2662, TASK-2665
**Assigned-to**: unassigned

---

## Context

Spec Module 8 + §3.1 (deterministic rendering). Extract typed fields with the
**cheap-tier client**, then render the exact §17 template in Python.

## Scope

- `nodes/meeting_page.py` + `render/meeting.py`: `cheap_client.invoke(output_type=MeetingExtraction)` (decisions/requirements/action-items[owner,due,status,confidence]/risks/open-questions).
- **Deterministically render** the §17 page verbatim (headings/section order/Action-Items table) under `Wiki/Sources/Meetings/<meeting filename>`; frontmatter from the §10.1 model; `## Verified Quotes` only when the transcript was read.
- Wikilinks for participants/projects/clients/concepts (queued-if-missing per §8.1); plain paths for raw provenance (D1); no fabrication (rule #12).

**NOT in scope**: project/entity/concept/daily updates.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/nodes/meeting_page.py` | CREATE | extraction node |
| `.../wiki_ingest/render/meeting.py` | CREATE | deterministic §17 renderer |
| `packages/ai-parrot/tests/unit/test_wiki_kb_meeting_page.py` | CREATE | template-fidelity tests |

## Codebase Contract (Anti-Hallucination)
### Verified Imports
```python
# MeetingExtraction / MeetingSourceFrontmatter from TASK-2661 models
# vault + naming from TASK-2662; cheap client from TASK-2660
```
### Existing Signatures to Use
```python
async def invoke(self, prompt, *, output_type=None, ...) -> InvokeResult   # clients/base.py:1747
async def create_note(self, path, content, frontmatter=None)               # tools/obsidian.py:439
```
### Does NOT Exist
- ~~LLM emitting page markdown directly~~ — the LLM returns a model; Python renders (§3.1).

## Implementation Notes
- Headings must match §17 exactly (conformance suite checks verbatim).
- Verified Quotes require `processing_mode == "summary-and-transcript"`.

## Acceptance Criteria
- [ ] Rendered page matches the §17 heading structure verbatim.
- [ ] Verified Quotes present only when the transcript was read.
- [ ] Raw provenance as plain paths; participant/project wikilinks resolve or are queued.
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
async def test_meeting_page_heading_fidelity(): ...
async def test_verified_quotes_only_with_transcript(): ...
```
