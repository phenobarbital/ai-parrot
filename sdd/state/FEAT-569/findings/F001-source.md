---
id: F001
query_id: Q001
type: read
intent: Owner direction and unexecuted spike gates
executed_at: 2026-09-17T21:50:09.640444+00:00
duration_ms: null
parent_id: null
depth: 1
---

# F001 — Owner direction and unexecuted spike gates

## Summary

Preserve Option B: full FSRS-6, verified outcomes only, recall does not reinforce, forgotten is recoverable, and coder feedback joins episodic memory. The source explicitly requires S1–S4 before specification. Its formulas, compatibility claims and proposed symbols are design input, not implemented contracts.

## Citations

- path: `sdd/proposals/agent-memory-dynamics.brainstorm.md`
  lines: 31-55
  symbol: `owner constraints`
  excerpt: |
    Who is affected: every `LongTermMemoryMixin` / `EpisodicMemoryMixin` agent, the dream cycle, `UnifiedMemoryManager` context assembly, the SDD coder engine (`_feedback_for`) and the `sdd-worker` / `sdd-coder` agent definitions.

    ## Constraints & Requirements


- path: `sdd/proposals/agent-memory-dynamics.brainstorm.md`
  lines: 565-600
  symbol: `spikes and open questions`
  excerpt: |
    - **S1 — Cold-start behaviour of FSRS-6 defaults on agent time scales.** Simulate 30 days of a `sdd-coder` model namespace from the existing `events.jsonl` `coder_feedback` history (import → replay `coder_record_review` outcomes as grades) and a synthetic generic-agent trace (tool episodes at minutes-to-hours cadence). Measure: fraction of lessons forgotten before their first review; retrievability of lessons that later prevented a recurrence; rank correlation between the new score and the current `(scope_score, recurrence, timestamp)` ranking. Pass: no lesson with `lapse_count == 0` and ≥ 1 GOOD review falls below `forget_threshold` within 30 days under defaults; otherwise decide between rescaling `t` (hours as "days") and shipping a pre-fitted parameter set.
    - **S2 — File-local concurrent episodic backend for the SDD shared root.** Prototype `SQLiteEpisodeBackend` (aiosqlite, WAL, `busy_timeout`, `BEGIN IMMEDIATE`, cosine in Python over ≤ 10k rows) and run N=8 worktree writers + readers concurrently (the same harness the ledger spike used). Compare with `FAISSBackend` snapshot files under the same load. Pass: zero lost writes, p95 `recall_similar` < 50 ms at 5k episodes.
    - **S3 — Attribution precision for generic agents.** On recorded tool traces of an existing agent with `EpisodicMemoryMixin`, compute how many injected memories the overlap rule attributes per outcome and how many of those a reviewer judges as actually relevant (sample of 50). Decide `max_overlap_reviews` and whether overlap reviews should be disabled by default outside SDD.
    - **S4 — Page-state storage.** Confirm whether FSRS state for brain pages fits in the existing page record (frontmatter in `body`, or `summary` sidecar) without breaking `search_fts` / `pack_results`, or whether `WikiPageRecord` needs a `metadata` JSON column (touches `SQLiteWikiStore`, Arango, Postgres wiki backends).

## Notes

Read-only inspection at dev HEAD 9ab95566e5982dbc3fe1cee8b03789ddcf6f161c. Proposed changes are inferences, not existing APIs. Range excerpts are locators; the summary uses the inspected surrounding range.
