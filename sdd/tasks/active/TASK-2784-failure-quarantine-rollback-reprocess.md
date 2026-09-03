# TASK-2784: Failure quarantine, rollback & reprocess (Module 17 fallback)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none (Modules 1–16 are all `done`; this extends them)
**Assigned-to**: unassigned

---

## Context

Implements **spec Module 17**. Meetings the LLM cannot compile into valid structured
output (observed: flash-tier Gemini degenerating on the large `MeetingPageExtraction`
schema → `InvokeError` / unparseable-truncated JSON) must not (a) leave partial pages in
the vault, nor (b) be silently marked processed and lost. This task makes each
per-meeting compile **transactional** and adds a **quarantine + bounded auto-retry**.

**Build on what already exists — do NOT reinvent rollback.** `runner.py` already has
`_PageWrite`, `_write_note()` (snapshots prior content), `_rollback()` (undoes writes,
never touches `Raw/`), and a per-meeting `try/except` that calls `_rollback` on a compile
exception (runner.py:511-516) and in the batch loop (runner.py:653-663). Two gaps remain
(this task closes them):
1. On failure the raw bundle has **already been promoted to `Raw/Processed/`** (see the
   runner.py:319 comment) and/or the id marked in `MeetingRegistry` → it is treated as
   done and never retried (**lost**).
2. Any per-meeting page write that does **not** go through `_write_note()` (e.g. a
   batch-level control-page touch) is **not** captured by `writes`, so `_rollback` leaves
   it behind → partial artifacts survive.

## Scope

- **Defer raw promotion until success (Module 3 change).** Move the raw bundle to
  `Raw/Processed/...` **only after** compile + §34 both pass. On failure, move it to
  **`Raw/Failed/<source-id>/`** instead (pre/post hash verify, same as Processed), and
  write a sidecar `Raw/Failed/<source-id>/failure.json` =
  `{source_id, attempts, last_error, first_failed_at, last_failed_at, models{strong,cheap}}`.
- **Never mark a failed id processed.** On failure the `source_id` is NOT written to
  `MeetingRegistry` as processed and is NOT a §14.3 permanent-skip — it stays reprocessable.
- **Complete the transactional guarantee.** Ensure **every** per-meeting page create/update
  (incl. control pages: index/overview/log/daily/review-queue/registry-mirror touched for
  this meeting) is routed through `_write_note()` so `_rollback()` restores the vault
  byte-identical to its pre-meeting state. Add a test that asserts zero residual diff after
  a forced compile failure.
- **Review-queue surfacing (Module 12 change).** Write a `failed-processing` Review Queue
  item linking the quarantined bundle + last error; on the cap, re-type it
  `reprocess-exhausted`.
- **Bounded auto-retry (Module 2 change).** Before fetching new meetings, the fetch-gate
  enumerates `Raw/Failed/` and re-submits each bundle to the normal compile path (NO
  re-download — bytes are local), incrementing `attempts` in `failure.json`. Success →
  promote `Raw/Failed/ → Raw/Processed/`, mark processed, clear the Review Queue item.
  After `WIKI_KB_MAX_REPROCESS_ATTEMPTS` (default 3, new conf key) → park as
  `reprocess-exhausted`, skip in the auto-retry loop until a human re-drops it.
- **Config.** Add `WIKI_KB_MAX_REPROCESS_ATTEMPTS` to `conf.py` (default `3`, via
  `config.getint`), exported in `__all__`.

**NOT in scope**: a manual `reprocess` intent/CLI (auto-retry + human re-drop suffice for
v1); changing the §34 validator itself; touching FEAT-472 `MeetingRegistry` schema.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/wiki_ingest/nodes/quarantine.py` | CREATE | quarantine move + `failure.json` sidecar + retry-eligibility helpers |
| `.../wiki_ingest/runner.py` | MODIFY | defer promote-to-Processed; on failure quarantine + don't mark processed; ensure all per-meeting writes go via `_write_note` |
| `.../wiki_ingest/nodes/raw_bundle.py` | MODIFY | `Raw/Failed/<source-id>/` routing (parallel to Processed/Duplicates/Uncategorized) |
| `.../wiki_ingest/nodes/fetch_gate.py` | MODIFY | enumerate `Raw/Failed/` and re-submit eligible bundles (attempts < cap) before new fetches |
| `.../wiki_ingest/nodes/review_queue.py` | MODIFY | `failed-processing` + `reprocess-exhausted` item types |
| `.../wiki_ingest/conf.py` | MODIFY | `WIKI_KB_MAX_REPROCESS_ATTEMPTS` (default 3) |
| `packages/ai-parrot/tests/integration/test_wiki_kb_ingest.py` (or new `test_wiki_kb_quarantine.py`) | CREATE/MODIFY | rollback-integrity + quarantine + retry-cap tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified this session at the cited paths. Build on these — do not reinvent.

### Existing infrastructure to reuse (runner.py)
```python
# packages/ai-parrot/src/parrot/flows/wiki_ingest/runner.py
class WikiIngestContext(BaseModel): ...          # :50  (limit, force_refetch, since, lookback_days, agent)
class IngestReport(BaseModel): ...               # :79  (processed, skipped, failed, created, updated, contradictions, review_items, errors)
class _PageWrite(...)                            # rollback snapshot (path, previous_content)
class _MeetingOutcome(BaseModel): ...            # :~119 (validation_passed, validation_failures, writes, review_items, ...)
async def _write_note(toolkit, path, content, writes: list[_PageWrite]) -> None   # :134 snapshots prior content
async def _rollback(toolkit, writes: list[_PageWrite]) -> None                    # :146 undoes writes; NEVER touches Raw/
async def run_ingest(ctx: WikiIngestContext) -> IngestReport                      # :~600 orchestrator; per-meeting try/except at :511 and batch loop :653 already call _rollback
# NOTE: raw bundle currently promoted to Raw/Processed BEFORE compile — see comment at :319. Defer it.
```

### Vault + registry (vault.py) — reuse, no edits to tools/obsidian.py
```python
# packages/ai-parrot/src/parrot/flows/wiki_ingest/vault.py
def build_vault_toolkit(vault_path=None, **kw) -> ObsidianToolkit   # :94  (allowed_operations incl. move/delete)
def build_meeting_registry(vault_path=None) -> MeetingRegistry      # :114
# MeetingRegistry (FEAT-472): the dedup gate — do NOT mark a failed id processed.
```

### Raw bundle routing (nodes/raw_bundle.py) + fetch gate (nodes/fetch_gate.py)
```python
# nodes/raw_bundle.py — currently routes Raw/Incoming -> Raw/Processed/<client>/<project>/YYYY/MM/<source-id>/
#   with pre/post sha256 verify, plus Duplicates/ and Uncategorized/. ADD Raw/Failed/<source-id>/.
# nodes/fetch_gate.py — GatedMeeting(BaseModel) (fireflies_id, source_id, title, meeting_date, outcome,
#   summary_text, transcript_text, ...). ADD a Raw/Failed/ enumeration + re-submit path.
```

### Config (conf.py)
```python
# conf.py — pattern: WIKI_KB_MAX_CATCHUP_DAYS: int = config.getint("WIKI_KB_MAX_CATCHUP_DAYS", fallback=90)
# ADD:      WIKI_KB_MAX_REPROCESS_ATTEMPTS: int = config.getint("WIKI_KB_MAX_REPROCESS_ATTEMPTS", fallback=3)
#           and add it to __all__.
```

### Does NOT Exist (do not assume)
- ~~`Raw/Failed/` handling / `failure.json` sidecar~~ — this task creates it.
- ~~`WIKI_KB_MAX_REPROCESS_ATTEMPTS`~~ — not in `conf.py` yet (add it).
- ~~`nodes/quarantine.py`~~ — new file.
- ~~a manual `reprocess` intent~~ — out of scope; retry is automatic + human re-drop.
- ~~a §14.3 permanent-skip for failed compiles~~ — quarantine is NOT permanent-skip; the id stays reprocessable.

---

## Implementation Notes

- The `_write_note`/`_rollback`/`_MeetingOutcome` triad is the transactional backbone —
  the main correctness work is (1) routing **all** per-meeting writes through `_write_note`
  and (2) moving the raw-promotion + registry-mark to **after** the §34 gate, redirecting to
  `Raw/Failed/` on any failure.
- Keep raw bytes immutable (only *move* bundles; never edit). `failure.json` is metadata
  written alongside, not a mutation of the raw files.
- Guard the retry loop against infinite retries strictly by `attempts >= cap`.
- Async throughout; `self.logger`; Pydantic for `failure.json` shape.

## Acceptance Criteria

- [ ] A forced compile failure (mock `cheap_client.invoke` raising `InvokeError`, or a
      degenerate output) leaves the vault **byte-identical** to its pre-meeting state
      (assert no residual page diff) — no partial pages.
- [ ] The failed bundle is at `Raw/Failed/<source-id>/` with intact bytes (pre/post hash
      match) + a `failure.json`; it is **absent** from `Raw/Processed/`.
- [ ] The failed `source_id` is **not** marked processed in `MeetingRegistry` (a subsequent
      ingest still considers it).
- [ ] A `failed-processing` Review Queue item is written; no success log/registry entry; the
      batch continues to the next meeting.
- [ ] Auto-retry: a bundle that now compiles (mock succeeds on attempt 2) is promoted to
      `Raw/Processed/`, marked processed, and its Review Queue item cleared.
- [ ] After `WIKI_KB_MAX_REPROCESS_ATTEMPTS` (default 3) the bundle is parked
      `reprocess-exhausted` and skipped by the auto-retry loop.
- [ ] `pytest` for the new + existing wiki_ingest suites pass; `ruff`/`mypy` clean; no edits
      to `tools/obsidian.py` or FEAT-472 `MeetingRegistry` schema (G11).

## Test Specification

```python
# tests/integration/test_wiki_kb_quarantine.py (sketch)
async def test_compile_failure_rolls_back_and_quarantines(tmp_vault, monkeypatch):
    # force cheap-tier invoke to raise; run_ingest(limit=1)
    # assert: vault diff empty, Raw/Failed/<id>/ exists, not in Raw/Processed,
    #         registry has no processed row, review queue has failed-processing item.

async def test_auto_retry_success_promotes_and_clears(tmp_vault, monkeypatch):
    # attempt 1 fails, attempt 2 succeeds -> Raw/Processed, processed row, queue cleared.

async def test_retry_cap_parks_reprocess_exhausted(tmp_vault, monkeypatch):
    # always-fail; after WIKI_KB_MAX_REPROCESS_ATTEMPTS -> reprocess-exhausted, no further retry.
```

---

## Agent Instructions

1. Read the spec (Module 17 + §5 fallback criteria) and this contract.
2. Verify the runner.py anchors (`_write_note`/`_rollback`/`_MeetingOutcome`, the :319
   promote comment, the :511/:653 except blocks) before editing.
3. Implement per scope, reusing the rollback backbone.
4. Run the quarantine tests + full wiki_ingest suite; ruff/mypy clean.
5. Move this file to `sdd/tasks/completed/` and update the index → `done`.
6. Fill in the Completion Note.

## Completion Note
*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
