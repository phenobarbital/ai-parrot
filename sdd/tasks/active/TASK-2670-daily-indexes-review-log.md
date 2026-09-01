# TASK-2670: Daily diary, indexes/overview, review queue, log (§23/§24/§26/§33)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2661, TASK-2662, TASK-2666
**Assigned-to**: unassigned
**Parallel**: true

---

## Context

Spec Module 12. The connective tissue: daily synthesis, navigation, human-judgment
queue, and the append-only operation log.

## Scope

- `nodes/daily.py` + `render/daily.py`: §23 daily note — **synthesis across the day's meetings, not concatenation**; de-duplicate statements; exact §23 template.
- `nodes/indexes.py`: §24 `Wiki/index.md` (every managed page reachable) + `Wiki/overview.md` (update only on material change); §18 project meeting indexes (active window + `Archive/` by YYYY/MM).
- `nodes/review_queue.py`: §26 Review Queue entries (allowed types **minus `source-revision`**); resolve flow.
- `nodes/log.py`: §33 append-only `Wiki/log.md` (ops **minus `revision-detected`**); never reorder.

**NOT in scope**: page compilation, archive movement (TASK-2673).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/nodes/{daily,indexes,review_queue,log}.py` | CREATE | four connective nodes |
| `.../wiki_ingest/render/daily.py` | CREATE | §23 renderer |
| `packages/ai-parrot/tests/unit/test_wiki_kb_connective.py` | CREATE | synthesis + index + log tests |

## Codebase Contract (Anti-Hallucination)
### Existing Signatures to Use
```python
async def create_note(...); async def update_note(...); async def read_note(...)  # tools/obsidian.py:439/471/212
```
### Does NOT Exist
- ~~`source-revision` review type / `revision-detected` log op~~ — removed (R3); do not emit them.

## Implementation Notes
- Daily note synthesizes; a lint check (TASK-2673) flags copy-paste daily notes.
- Log is append-only — never rewrite existing entries.

## Acceptance Criteria
- [ ] Daily note synthesizes (not concatenates); multiple same-date meetings merge.
- [ ] Every new page reachable from `Wiki/index.md`; overview updated only on material change.
- [ ] Review types exclude `source-revision`; log ops exclude `revision-detected`.
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
async def test_daily_synthesizes_not_concatenates(): ...
async def test_index_reachability_and_append_only_log(): ...
```
