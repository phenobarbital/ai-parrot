# S4 (TASK-3385) — Brain Page State Storage, Version Identity and Lineage — Gate Report

Gate: G4/S4 (spec §3 row G4; brainstorm S4). This report is the reproducible artifact reviewed by the owner; it is not itself the gate pass — see `amendment.md`.

## Commands

```
Intended entry point (this task's Validation Commands):
PARROT_SPIKE_FULL=1 pytest packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/test_s4_harness.py::test_full_comparison_writes_report -q > artifacts/logs/feat-571-s4-<ts>.log 2>&1
```
```
Actual command run in this attempt worktree (pre-existing environment blocker — see Limitations): a bare `pytest` fails to COLLECT anything under packages/ai-parrot/tests/ because conftest.py's repo-wide autouse fixture transitively imports the missing compiled extensions parrot/utils/types.*.so and parrot/utils/parsers/toml.*.so. `-c /dev/null` bypasses only that broken root conftest chain, never any logic under this spike:
PARROT_SPIKE_FULL=1 PYTHONPATH=packages/ai-parrot/src python3 -m pytest -c /dev/null packages/ai-parrot/tests/memory/dynamics/spikes/s4_brain_state/test_s4_harness.py -q --asyncio-mode=auto > artifacts/logs/feat-571-s4-<ts>.log 2>&1
```

## Versions

- `MAX_LINEAGE_DEPTH` (traversal bound used by this report): 32
- `WikiPageRecord` has no `metadata` field (spec C6) — verified against store.py:409-453

## Per-Design Comparison

| Design | 5x redistill: distinct versions | old excluded from search | state per version preserved | survives remember-rewrite | survives copy_page_to | FTS hit w/ state | FTS hit w/o state | packed tokens (state) | packed tokens (control) |
|---|---|---|---|---|---|---|---|---|---|
| A-frontmatter | True | True | True | True | True | True | True | 43 | 43 |
| B-sidecar | True | True | True | True | False | True | True | 43 | 42 |
| C-metadata-column(simulated) | True | True | True | True | False | True | True | 44 | 44 |

## Lineage — Bound and Cycle Results

- Traversal bound: `MAX_LINEAGE_DEPTH` = 32 (report parameter; the amendment freezes the production bound)
- Cycle detection event category: `lineage_cycle` (spec §7)
- A-frontmatter: canonical(oldest) resolves to newest = True; duplicate forwarding → one credit = True
- B-sidecar: canonical(oldest) resolves to newest = True; duplicate forwarding → one credit = True
- C-metadata-column(simulated): canonical(oldest) resolves to newest = True; duplicate forwarding → one credit = True

## Watermark Recovery

- `last_run` watermark: 2026-09-18T12:41:04.718756+00:00
- Eligible episode ids for the next ordinary cycle: ['new-eligible']
- Excluded by the watermark: ['old-unconsolidated', 'old-consolidated', 'below-threshold']
- Recovery path: Episodes with created_at <= state.last_run are invisible to the ordinary next cycle (runner.py:253-256 — `since` is a lower bound on get_recent). Recovering them requires an explicit backfill query that bypasses `since` (e.g. a one-off get_recent(since=None) scoped by episode_id, or a dedicated scan for metadata['consolidated_into'] absent), never a `last_run` rewind — rewinding `last_run` would re-collect already-consolidated episodes too, since DreamState carries a single scalar cursor, not a per-episode watermark.

## Legacy Promotion Evidence Inventory

- `DreamCycleRunner.run_cycle` (runner.py:182-186) increments `state.reinforcement_counts[page_id]` once per DISTINCT CYCLE that reinforces a page — not per verified review of that page's content.
- Promotion to the org wiki (runner.py:196-201) fires when `reinforcement_counts[page_id] >= DreamConfig.org_promotion_cycles` (default 3, models.py:81) — a cycle-count threshold, not evidence of a verified successful outcome that actually used the promoted content.
- `DreamCycleReport` (models.py:103-129) has no `pages_redistilled` / `memories_forgotten` fields (spec C7) — this report proposes their count semantics only in `amendment.md`.

## G2 Coordination Points

- State-write ordering: whichever design is frozen must write its page-state update either in the SAME unit of work as G2's atomic review-apply transaction, or immediately after under a documented at-least-once/idempotent replay contract — this spike used a single, non-transactional `upsert_pages`/companion-write call per design and never modeled the atomic review transaction itself (that protocol is G2's; NOT in scope here).
- Version admission: a G2 review command should target a `content_version`, not a bare `page_id`, so a review that lands after a re-distillation can never silently apply to content the reviewer did not actually see (spec §2 'A review of old content must not automatically count as verified success of newly synthesized content').

## Pass/Fail

- A-frontmatter — 5× re-distill (distinct versions, old excluded, state preserved): PASS
- B-sidecar — 5× re-distill (distinct versions, old excluded, state preserved): PASS
- C-metadata-column(simulated) — 5× re-distill (distinct versions, old excluded, state preserved): PASS
- A-frontmatter — state survives remember()/copy_page_to(): PASS/PASS
- B-sidecar — state survives remember()/copy_page_to(): PASS/FAIL
- C-metadata-column(simulated) — state survives remember()/copy_page_to(): PASS/FAIL

## Limitations

- Environment: this attempt worktree is missing the compiled `parrot/utils/types.*.so` / `parrot/utils/parsers/toml.*.so` build artifacts; `packages/ai-parrot/tests/conftest.py`'s repo-wide autouse fixture transitively imports them, making a bare `pytest packages/ai-parrot/tests/...` uncollectable in this worktree — a pre-existing, worktree-wide gap unrelated to this task (see S1's REPORT.md for the same finding). Verified instead with `pytest -c /dev/null <path>`, which bypasses only the broken root conftest chain, never any logic under this spike.
- The atomic review protocol itself belongs to G2; this report only records the coordination points above, it does not design a second protocol.
- `SimulatedMetadataColumnDesign`'s companion table lives beside the wiki db file via the SQLite-specific `db_path` property; the real migration (if design C is chosen) is a genuine `WikiPageRecord.metadata` column across all four wiki backends (see `amendment.md`).
- `scenario_search_drift` uses query terms that never overlap the JSON state-block vocabulary, so it isolates document-length/BM25 normalisation drift rather than lexical noise; a state payload containing terms that accidentally match future queries is not modeled here.

See `amendment.md` in this directory for the proposed spec freeze.
