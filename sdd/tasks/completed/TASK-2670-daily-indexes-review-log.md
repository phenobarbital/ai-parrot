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

### Completion Note

`render/daily.py` + `nodes/daily.py`: `run_daily_synthesis()` parses the
existing day's note back into a typed `DailyState` (round-trip of our
own §23 format), asks the cheap-tier client to propose ONE merged/
de-duplicated synthesis (`DailySynthesisProposal`), then Python-merges
project updates/decisions/action-items/risks by exact-text dedup and
appends the new meeting link — a second same-day meeting produces one
coherent note, never a doubled concatenation.

`nodes/indexes.py`: `render_wiki_index()` deterministically renders every
§24.1 nav section (Projects/Sources/Entities/Concepts/Syntheses/
Contradictions/Review Queue + a bounded Recently-Updated trail);
`overview_materially_changed()` is the one LLM judgment call (§24.2 —
skips the call entirely when there are no new developments);
`split_active_and_archived()` + the two `render_project_meeting_index_*`
functions implement §18's active-window / `YYYY`/`MM`-grouped archive
split, deterministically.

`nodes/review_queue.py` / `nodes/log.py`: `ALLOWED_REVIEW_TYPES` /
`ALLOWED_LOG_OPS` are the §26/§33 lists **minus** `source-revision` /
`revision-detected` (R3) — `render_review_item()`/`render_log_entry()`
raise `ValueError` if ever asked to emit either. `append_review_item()`/
`append_log_entry()` only ever append; `resolve_review_item()` flips
`Status: Open` → `Resolved` and appends a Resolution/Resolved-at pair
while preserving the original issue text verbatim.

Verified: `pytest packages/ai-parrot/tests/unit/test_wiki_kb_connective.py`
(6 passed — daily synthesis dedup across two same-day meetings, fresh
daily note, full index reachability + append-only log, active/archive
project meeting index split, source-revision rejection, review-item
append+resolve preserving the original issue); `ruff check` clean;
`mypy` clean; full wiki-kb suite (77 tests) stays green.
