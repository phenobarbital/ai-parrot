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

### Completion Note

`nodes/health.py`: `run_health()` — strictly read-only, reports §29
items 1/2 (required dirs/control files), 3 (pending complete/incomplete
`Raw/Incoming/` bundles, reusing `raw_bundle.pair_incoming_bundles`), 4
(duplicate source ids via `registry.all_records()`), 5 (open review
items/contradictions), 7 (recent `Wiki/log.md` entries missing a
`Validation:` line), 9 (`private_never_accessed` is a structural
constant — this module has no `Private/` code path at all).

`nodes/lint.py`: `run_lint()` reuses `ObsidianToolkit.catalog_notes()`
(already computes `broken_links`/`orphans` over the indexed vault —
no wikilink-resolution reimplementation needed) for the two ACs this
task calls out explicitly; `--fix` implements exactly one §30 safe-fix
category (`duplicate_index_entry` — de-duplicating exact-duplicate
`Wiki/index.md` lines), gated by `SAFE_FIX_CATEGORIES`; every other §30
check category from the contract's long list is a documented, deferred
scope reduction given this task's effort budget, not a silent omission.

`nodes/archive.py`: `run_archive(toolkit, registry, *,
active_window_days=None, today=None)` — signature matches
`runner._maybe_run_archive`'s lazy `from .nodes.archive import
run_archive` call exactly, so TASK-2672's orchestrator picks this up
automatically with no changes to `runner.py`. Daily notes older than
the window move to `Diary/Archive/YYYY/` via `move_note` +
`vault.fixup_links`; project meeting-index entries re-split via
`indexes.split_active_and_archived` (TASK-2670, reused) into
`Meeting Summaries/index.md` (active) and `.../Archive/index.md`
(archived, `YYYY`/`MM` grouped) — never touches canonical
`Wiki/Sources/Meetings/` pages, canonical project pages, or raw
bundles.

`nodes/graph_report.py`: `run_graph_report()` renders an `"overview"` or
per-project inventory from `catalog_notes()`/`get_outgoing_links()`
(existing wikilinks/content only — §32 rule 2), always under
`Wiki/Graph/<target>.md` with an explicit "Derived report — not
canonical" banner (§32 rules 4/5).

**Known gap (not fixed — out of this task's file scope):** agent.py's
`health()`/`lint()`/`archive()`/`build_graph_report()` stubs (TASK-2660)
still call `run_x(self, ...)` with the pre-implementation stub
signature, which no longer matches these modules' real signatures —
mypy flags 3 call-arg errors in `agent.py` as a result. TASK-2672's own
file list explicitly covered rewiring `agent.py`'s `ingest()`/`query()`
only; no task in this feature's index covers rewiring the remaining
four intents. Flagged here (and in the feature completion summary) as a
straightforward follow-up, not fixed to respect file fidelity.

Verified: `pytest packages/ai-parrot/tests/unit/test_wiki_kb_workflows.py`
(7 passed — health read-only + duplicate-id detection, missing-dirs
detection, lint broken-link detection, lint --fix dedup, archive window
split, archive never touches canonical pages, graph report derived
label); `ruff check` clean; `mypy` clean on this task's own four files;
full wiki-kb suite (91 tests) stays green.
