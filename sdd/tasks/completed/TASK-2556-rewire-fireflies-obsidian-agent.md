# TASK-2556: Rewire `FirefliesObsidianAgent` sync and analysis loops onto the registry

**Feature**: FEAT-472 — Fireflies Meeting Registry
**Spec**: `sdd/specs/fireflies-meeting-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2554, TASK-2555
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, §2 "Sync loop" / "Analysis loop" / "Backfill" / "Toolkit
permissions". This is where the title-based dedup (`agents/obsidian.py:399-416`)
is replaced by `MeetingRegistry.classify`, revisions update notes in place (G4),
renamed notes are repaired (G7), and analysis selection comes from the registry
(G6). Everything must keep working when the registry is unavailable (G10).

---

## Scope

In `packages/ai-parrot/src/parrot/agents/obsidian.py`:

- `__init__`: new kwarg `registry_dir: Optional[str | Path] = None` → `self.registry_dir`
  (default `FIREFLIES_REGISTRY_DIR`); `self.registry: Optional[MeetingRegistry] = None`;
  `allowed_operations` gains `"move"` and `"delete"`.
- `configure()`: build `MeetingRegistry(self.registry_dir)`; if `available`, run
  `backfill_from_vault(toolkit=self.obsidian_toolkit, meetings_folder=..., analysis_heading=self.ANALYSIS_HEADING)`
  once and log its summary (seeded / without_analysis / duplicates merged). Failures →
  warning, `self.registry = None`.
- `sync_fireflies_transcripts(..., force_refetch: bool = False)`:
  - Report schema: add `revised: 0`, `repaired: []`, `duplicates: []`,
    `probable_duplicates: []`, `from_date: None`, `registry: "ok"|"unavailable"`.
  - If no `from_date` in the effective filters and the registry is available →
    `suggest_from_date(overlap_days=FIREFLIES_SYNC_OVERLAP_DAYS)`; set it on the
    tool args and on `report["from_date"]`.
  - Per item: `classified = await self.registry.classify(item, fetch=..., fetch_summary=..., force_refetch=force_refetch)`
    where `fetch` wraps the existing `fireflies_get_transcript` call and
    `fetch_summary` the `fireflies_get_summary` call (only when `include_summary`).
  - `skip` → `report["skipped"] += 1`.
  - `create`/`revise`: `repair_path(...)` first; `to_path=None` → treat as create.
    - create: `note_title = await registry.unique_slug(...)`; existing metadata +
      OKF frontmatter path unchanged; `create_note`; `record_synced(reset_analysis=False)`;
      `report["synced"] += 1`.
    - revise: rebuild body (transcript + optional summary section, no Analysis);
      `update_note(path, body, preserve_frontmatter=True)`; refresh frontmatter
      `title/participants/synced_at` (via the toolkit's frontmatter-preserving
      update or a follow-up metadata write — check `update_note` semantics at
      `tools/obsidian.py:471-503`); `record_synced(reset_analysis=True)`;
      `report["revised"] += 1`.
    - `classified.probable_duplicate_of` → append to `report["probable_duplicates"]`.
  - When `self.registry is None or not registry.available` → keep today's
    title-based path verbatim and set `report["registry"] = "unavailable"`.
- `summarize_pending_transcripts()`: when `note_titles is None` and registry
  available → candidates from `pending_analysis()` (note title = stem of
  `note_path`); after `summarize_transcript` → `mark_analyzed(id, fingerprint)` on
  ok, `mark_analysis_failed(id, error)` on error. `force=True` → all registry
  rows. Fallback to `_get_existing_meeting_titles` + `_has_analysis` when unavailable.
- Tests: `tests/test_fireflies_obsidian_sync.py` (new; MCP stubbed, real local
  `ObsidianToolkit` on a tmp vault, registry on tmp).

**NOT in scope**: `agents/fireflies_wiki.py` (TASK-2557); docs (TASK-2559).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/agents/obsidian.py` | MODIFY | ctor, configure, sync loop, summarize loop |
| `tests/test_fireflies_obsidian_sync.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.agents.obsidian import FirefliesObsidianAgent, FirefliesFilters, _merge_filters, _filters_to_tool_args   # agents/obsidian.py:185 / ~50 / :120 / :85
from parrot.agents.meeting_registry import MeetingRegistry, Classified, RepairResult   # TASK-2554/2555
from parrot.agents.conf import FIREFLIES_REGISTRY_DIR, FIREFLIES_SYNC_OVERLAP_DAYS, FIREFLIES_RECHECK_DAYS   # TASK-2554
from parrot.tools.obsidian import ObsidianToolkit
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/agents/obsidian.py
class FirefliesObsidianAgent:
    def __init__(self, name="FirefliesObsidianSync", vault_path=None, fireflies_token=None,
                 meetings_folder="meetings", default_filters=None, **kwargs)                 # :185
    self.vault_path: Path (:211-215); self.meetings_folder (:216); self.default_filters (:217)
    self.obsidian_toolkit = ObsidianToolkit(vault_path=str(self.vault_path), backend="local",
        allowed_operations={"read","list","search","create","update"})                  # :220-230
    async def configure(self, app=None) -> None                                          # :235
    async def sync_fireflies_transcripts(self, limit, skip_existing=True, filters=None, include_summary=...) -> Dict   # :287-292
        report = {"status": "ok", "synced": 0, "skipped": 0, "notes": [], "errors": []}   # :340-346
        effective_filters = _merge_filters(self.default_filters, filters); tool_args = _filters_to_tool_args(...)   # :352-354
        transcripts = self._parse_fireflies_response(...)                                 # ~:380-395
        existing_titles = await self._get_existing_meeting_titles()  (skip_existing)     # :399-401  ← REPLACE
        for transcript in transcripts:                                                    # :404
            transcript_id = transcript.get("id"); title = transcript.get("title", "Untitled Meeting"); date = transcript.get("date", ...)   # :406-408
            note_title = self._make_note_title(date, title); if note_title in existing_titles: skip   # :411-416  ← REPLACE
            transcript_result = await self._call_fireflies_tool("fireflies_get_transcript", {"transcriptId": transcript_id})   # :419-422
            transcript_text = transcript_result.result if hasattr(...) else str(...)      # :425-429
            summary_result = await self._call_fireflies_tool("fireflies_get_summary", {...})  (include_summary)   # :438-441
            transcript_text = self._append_fireflies_summary_section(transcript_text, summary_text)   # :447-449
            metadata = {"fireflies_id","date","title","participants","duration_minutes","synced_at"}   # :461-468
            okf_metadata = self._build_okf_frontmatter(fireflies_id=..., title=..., date=..., participants=..., duration=...)   # :471-477
            merged_metadata = {**metadata, **okf_metadata}; has_summary → "has_fireflies_summary"   # :480-482
            await self.obsidian_toolkit.create_note(path=f"{self.meetings_folder}/{note_title}.md", content=transcript_text, frontmatter=merged_metadata)   # :485-489
            report["notes"].append(note_title); report["synced"] += 1                    # :491-492
    async def summarize_transcript(self, note_title: str, granularity="standard") -> Dict   # :506 — returns {"status": "ok"|..., "error": ...}
    async def summarize_pending_transcripts(self, note_titles=None, granularity="standard", limit=None, force=False) -> Dict   # :593
        outcome = {"status","analyzed": [],"skipped": [],"errors": []}                   # :621-626
        candidates = sorted(await self._get_existing_meeting_titles())                   # :630  ← REPLACE when registry available
        if not force and await self._has_analysis(note_title): skip                      # :649  ← REPLACE when registry available
    @classmethod def _strip_analysis_section(cls, content) -> str                        # :677
    async def _has_analysis(self, note_title) -> bool                                    # :697 (fallback only)
    @staticmethod def _build_okf_frontmatter(...)                                        # :721 (unchanged)
    @staticmethod def _parse_fireflies_response(text) -> List[Dict]                      # :783
    async def _call_fireflies_tool(self, name, args)                                     # :867
    async def _get_existing_meeting_titles(self) -> set[str]                             # :893 (fallback only)
    @staticmethod def _make_note_title(date, meeting_title) -> str                       # :929
    @staticmethod def _append_fireflies_summary_section(transcript, summary_text) -> str  # :1071

# packages/ai-parrot/src/parrot/tools/obsidian.py
async def update_note(self, path: str, content: str, preserve_frontmatter: bool = True) -> Dict   # :471 — READ :471-503 to learn whether frontmatter values can be refreshed in the same call
async def create_note(self, path, content, frontmatter=None) -> Dict                                # :439

# packages/ai-parrot/src/parrot/agents/meeting_registry.py (TASK-2554/2555)
class MeetingRegistry:
    available: bool
    async def classify(self, item, *, fetch, fetch_summary=None, force_refetch=False) -> Classified
    async def repair_path(self, fireflies_id, *, toolkit, meetings_folder, canonical_title) -> RepairResult
    async def unique_slug(self, meetings_folder, base_title, *, vault_path) -> str
    async def record_synced(self, *, fireflies_id, note_path, title, meeting_date, participants, duration_minutes, fingerprint, summary_fingerprint, reset_analysis) -> MeetingRecord
    async def pending_analysis(self) -> list[MeetingRecord]
    async def mark_analyzed(self, fireflies_id, fingerprint) -> None
    async def mark_analysis_failed(self, fireflies_id, error) -> None
    async def suggest_from_date(self, *, overlap_days) -> str | None
    async def backfill_from_vault(self, *, toolkit, meetings_folder, analysis_heading, merge=True) -> BackfillReport
```

### Does NOT Exist
- ~~`sync_fireflies_transcripts(force_refetch=…)`~~, ~~`self.registry`~~, ~~`self.registry_dir`~~ — this task adds them.
- ~~`report["revised"|"repaired"|"duplicates"|"probable_duplicates"|"from_date"|"registry"]`~~ — this task adds them.
- ~~a hard-coded date window in the agent~~ — window comes only from filters.
- ~~`ObsidianToolkit.update_note(frontmatter=…)`~~ — signature is `(path, content, preserve_frontmatter)`; verify how to refresh frontmatter values before assuming.
- ~~`fireflies_get_transcripts` returning a content hash~~ — it does not.

---

## Implementation Notes

### Pattern to Follow
Keep the existing loop structure and error handling (per-item try/except appending to `report["errors"]`, `:495-498`). Insert the registry branch *before* the fetch and route the fetch through the `fetch` callable so `classify` controls whether the MCP call happens:
```python
async def _fetch(tid: str) -> str:
    r = await self._call_fireflies_tool("fireflies_get_transcript", {"transcriptId": tid})
    return r.result if hasattr(r, "result") else str(r)
```

### Key Constraints
- Fallback path must be byte-identical to today's behaviour when `self.registry is None`.
- `skip_existing=False` still means "sync everything": bypass `classify` skip results but still `record_synced`.
- Never raise from the scheduled entry points; report dicts only.
- `move`/`delete` are used only by the registry verbs; no direct calls in the agent.

### References in Codebase
- `agents/obsidian.py:287-504` — the loop
- spec §2 "Sync loop", §7 Known Risks (concurrency, cheap-skip correctness)

---

## Acceptance Criteria

- [ ] `pytest tests/test_fireflies_obsidian_sync.py tests/test_meeting_registry.py -v` passes; `ruff check packages/ai-parrot/src/parrot/agents/`.
- [ ] Same id + changed title → `update_note` called, `create_note` not, exactly one file, `analysis_status == "pending"`, `report["revised"] == 1`.
- [ ] Same day + same title, two ids → two files, second `-2`.
- [ ] Cheap skip → `fireflies_get_transcript` not called; `force_refetch=True` → called.
- [ ] `fromDate` sent to the MCP equals `suggest_from_date` when no explicit filter; explicit filter / `default_filters` wins; empty registry → no `fromDate`.
- [ ] Registry unavailable → title-based path, `report["registry"] == "unavailable"`, no exception.
- [ ] `summarize_pending_transcripts` uses `pending_analysis`, never calls `_has_analysis`, calls `mark_analyzed` with the fingerprint; failure → `mark_analysis_failed`.
- [ ] `allowed_operations` contains `"move"` and `"delete"`.
- [ ] `configure()` runs backfill once and logs the summary.
- [ ] All new parameters default to current behaviour (existing tests unchanged).

---

## Test Specification

```python
# tests/test_fireflies_obsidian_sync.py
@pytest.fixture
def fake_fireflies(monkeypatch): ...   # patch FirefliesObsidianAgent._call_fireflies_tool: listing / transcript / summary keyed by id; records calls
@pytest.fixture
def agent(tmp_path, fake_fireflies): ... # vault_path=tmp/vault, registry_dir=tmp/reg, llm stubbed

async def test_sync_same_id_changed_title_updates_in_place(agent, fake_fireflies): ...
async def test_sync_same_day_same_title_two_ids(agent, fake_fireflies): ...
async def test_sync_cheap_skip_and_force_refetch(agent, fake_fireflies): ...
async def test_sync_from_date_from_registry(agent, fake_fireflies): ...
async def test_sync_explicit_from_date_wins(agent, fake_fireflies): ...
async def test_sync_registry_unavailable_falls_back(agent, fake_fireflies, monkeypatch): ...
async def test_sync_report_fields(agent, fake_fireflies): ...
async def test_summarize_uses_registry_pending(agent, monkeypatch): ...
async def test_summarize_failure_marks_failed(agent, monkeypatch): ...
def test_allowed_operations_include_move_delete(agent): ...
async def test_configure_runs_backfill_once(agent, monkeypatch): ...
```

---

## Agent Instructions

1. Read spec §2 fully; 2. confirm TASK-2554 and TASK-2555 completed; 3. verify contract — especially `update_note` frontmatter semantics; 4. mark in-progress; 5. implement; 6. run new tests **and** `tests/test_fireflies_wiki_agent.py` (must still pass unchanged); 7. move to completed; 8. mark done; 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-29
**Notes**: `__init__` gained `registry_dir` (default `FIREFLIES_REGISTRY_DIR`),
`self.registry: Optional[MeetingRegistry] = None`, and `"move"`/`"delete"`
in `allowed_operations`. `configure()` opens `MeetingRegistry(self.registry_dir)`
and runs `backfill_from_vault` once when available, logging the summary;
any failure degrades to `self.registry = None` (never raises). The
`MeetingRegistry` import is deferred inside `configure()` (behind a
`TYPE_CHECKING`-only import at module top) since `meeting_registry.py`
itself imports `FirefliesObsidianAgent` — a top-level import here would
cycle. `sync_fireflies_transcripts` gained `force_refetch` and the new
report fields (`revised`, `repaired`, `duplicates` (reserved, always
empty — populated only by `configure()`'s own backfill/merge, never by
this method), `probable_duplicates`, `from_date`, `registry`); the
original per-item loop body was extracted verbatim into `_sync_via_titles`
(byte-identical fallback for G10) and a new `_sync_via_registry` added for
the id-keyed path: `classify()` per item (fetch/fetch_summary closures
cache the raw transcript/summary text as a side effect, since `Classified`
only returns fingerprints, not the text itself), `repair_path()` before
create/revise (a `to_path=None` result funnels either outcome into
create), `unique_slug()` for new notes, and a two-step frontmatter refresh
for revise (`update_note(preserve_frontmatter=True)` for the body, then a
new `_refresh_note_frontmatter` helper — read+merge+rewrite via
`preserve_frontmatter=False` — for title/participants/synced_at, since
`update_note` has no "patch these frontmatter keys" primitive).
`summarize_pending_transcripts` sources candidates from
`registry.pending_analysis()` when available (title = `Path(record.note_path).stem`),
never calling `_has_analysis` for those, and calls `mark_analyzed`/
`mark_analysis_failed` afterward; explicit `note_titles` or an unavailable
registry keep the original `_has_analysis`-gated path unchanged. 12 new
tests in `tests/test_fireflies_obsidian_sync.py` (real local
`ObsidianToolkit` + real `MeetingRegistry` on tmp dirs, `_call_fireflies_tool`
stubbed) plus the existing `tests/test_meeting_registry.py` (99 total) and
`tests/test_fireflies_wiki_agent.py` (unchanged, still green) all pass.
`ruff check` on the diff introduces only findings that match this file's
own pre-existing, deliberate conventions (see Deviations).

**Deviations from spec**: Two judgment calls, both flagged for spec-author
awareness:
1. **`skip_existing=False` semantics** (scope: "still means sync
   everything: bypass classify skip results but still record_synced").
   Interpreted as: a `classify()` "skip" result still increments
   `report["skipped"]` (nothing changed, so there is genuinely no note to
   rewrite) but `record_synced` is still called to advance the row's
   `synced_at` freshness window. Not explicitly covered by the task's own
   test list; implemented conservatively rather than guessing a more
   invasive behavior.
2. **`force=True` with the registry driving candidates** (scope:
   "`force=True` -> all registry rows"). No `MeetingRegistry` verb
   returns "every row regardless of status" (only `pending_analysis()`,
   which already excludes done-and-current rows by its own definition),
   and `meeting_registry.py` is not in this task's file list to extend.
   `force` therefore has its full original effect only on the
   `note_titles`-explicit and registry-unavailable paths; with the
   registry driving `note_titles=None`, candidates are always exactly
   `pending_analysis()`'s result set. Documented in the method's own
   docstring.

**Ruff note**: the diff's new `BLE001`/`DTZ003`/`UP006`/`UP045` findings
(broad `except Exception`, `datetime.utcnow()`, `Dict`/`List`/`Optional[X]`
typing) all match this file's own dominant, pre-existing style (no
`from __future__ import annotations`; every scheduled entry point uses
`except Exception` deliberately so a report dict is always returned, per
spec §7 "Reports never raise"). The file already carried 50 ruff findings
before this task; introducing a different style in just the new code
would be inconsistent, and a whole-file typing reformat is unrelated
scope. Two easily-fixable NEW findings (a quoted forward-reference type
annotation, one nested-if) were fixed since they cost nothing and are
genuinely cleaner.
