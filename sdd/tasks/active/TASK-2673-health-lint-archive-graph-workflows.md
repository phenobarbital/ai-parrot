# TASK-2673: Health / Lint / Archive / Graph workflows (§29–§32)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2662, TASK-2664, TASK-2671
**Assigned-to**: unassigned
**Parallel**: true

---

## Context

Spec Module 14. The read-only / maintenance intents that keep the vault coherent.

## Scope

- `nodes/health.py` (§29): fast read-only check — required dirs/control files exist, count pending bundles, detect duplicate source ids, count open reviews/contradictions, recent-log sanity, `Private/` never touched.
- `nodes/lint.py` (§30): integrity scan (broken wikilinks, orphans, unreachable pages, duplicate ids/aliases, missing registry/source pairs, stale project pages, daily notes that copy instead of synthesize, active refs past the window, …); `--fix` applies only the §30 safe repairs; never auto-fix contradictions/classification/locked pages.
- `nodes/archive.py` (§31): rolling **configurable** active window (default `WIKI_KB_ACTIVE_WINDOW_DAYS=14`) — move old daily notes to `Diary/Archive/YYYY/`; move old project meeting refs to `Meeting Summaries/Archive/`; never move canonical `Wiki/Sources/Meetings/` pages or raw bundles. Callable both standalone and as ingest step 22 (TASK-2672).
- `nodes/graph_report.py` (§32): derived, rebuildable reports under `Wiki/Graph/` (mermaid/inventories), labeled derived, never canonical.

**NOT in scope**: ingest, compilation.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `.../wiki_ingest/nodes/{health,lint,archive,graph_report}.py` | CREATE | four workflows |
| `packages/ai-parrot/tests/unit/test_wiki_kb_workflows.py` | CREATE | health/lint/archive/graph tests |

## Codebase Contract (Anti-Hallucination)
### Existing Signatures to Use
```python
async def list_notes(...); async def read_note(...); async def move_note(...)  # tools/obsidian.py:257/212/538
```
### Does NOT Exist
- ~~archiving canonical source pages or raw bundles~~ — forbidden (§31).

## Implementation Notes
- Window is configurable (D7): compute cutoff = `today - (window - 1)` days.
- Lint `--fix` limited to the §30 safe-fix list; report everything else.

## Acceptance Criteria
- [ ] Health is read-only and reports the §29 items.
- [ ] Lint detects broken links/orphans; `--fix` only applies safe repairs.
- [ ] Archive respects the configurable window; never moves canonical pages/raw.
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
async def test_archive_configurable_window(): ...
async def test_lint_detects_broken_links(): ...
```
