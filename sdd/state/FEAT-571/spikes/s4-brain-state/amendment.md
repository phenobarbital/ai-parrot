# Proposed spec amendment — S4 (TASK-3385) · status: PROPOSED (owner + architecture review; G2 coordination required)

## Freeze

- **Page-state storage: (A) frontmatter** — a fenced, machine-parseable state block prepended to
  `body`, stripped by `searchable_body()` before anything reaches FTS/summary/pack. Evidence:
  REPORT.md "Per-Design Comparison" — A is the *only* design where `survives_copy_page_to = PASS`;
  B (sidecar record) and C (simulated metadata column) both `FAIL` that row because
  `BrainStore.copy_page_to` (brain.py:146-177) copies only the `WikiPageRecord` fields of the ONE
  page it was given — it never knows to also copy a sidecar row or a companion-table row for a
  DIFFERENT concept_id / a different file. Since the spec explicitly requires state to survive
  `copy_page_to()` (§ Context), A is the only candidate that satisfies that requirement with **zero**
  changes to `copy_page_to`/`remember()`. All three designs pass 5x-redistillation (distinct
  versions, old excluded from search, state preserved per version) and show no meaningful FTS/pack
  token-cost drift (REPORT.md "Per-Design Comparison" — packed token costs differ by at most 1
  token, from BM25/length effects, not from state text leaking into `summary`/pack lines).
- **Migration list: none required.** Design A stores state as prose-adjacent text inside the
  EXISTING `body` column — no schema change to `WikiPageRecord` (store.py:409), `SQLiteWikiStore`
  (store.py:821), `ArangoDBWikiStore` (arango_store.py:135) or `PostgresWikiStore`
  (postgres_store.py:127). This is the main practical advantage over the C `metadata`-column arm,
  which would require a real DDL/field addition on all four.
- **Version identity**: `content_version = sha1(body_without_state | sorted(source_episode_ids))`;
  `page_id` (today's `"mem-" + sha1(title|category)`) stays the family key. A new version gets a
  distinct row (`concept_id = f"{page_id}-{content_version[:10]}"` in this spike); the row that a
  new version supersedes is re-categorized `category="archive"` so it is excluded from ordinary
  `search_fts()` by the ALREADY-EXISTING default filter (store.py:1963-1965) — no new admission
  mechanism needed for exclusion.
- **Forwarding/admission**: reviews credit the DELIVERED version, never a canonically-forwarded one
  (`Lineage.canonical()` walks `supersedes` forward strictly for ranking/exclusion — see
  `test_review_on_old_version_does_not_credit_new_version`, harness.py `Lineage.canonical`/
  `credit_targets`). `credit_targets()` collapses two alias ids that cite the SAME current version
  to one canonical credit target (duplicate forwarding), but never reassigns a review of an OLD
  version onto whatever superseded it. Lineage depth bound: `MAX_LINEAGE_DEPTH = 32` (harness.py);
  a traversal exceeding it, or a revisited node, raises the single event category `lineage_cycle`
  (spec §7).
- **Promotion evidence**: keep `reinforcement_counts`/`org_promotion_cycles` as a read-only LEGACY
  signal in dynamics mode (see "Legacy Promotion Evidence Inventory" below) — replace it as the
  GATE for promotion with direct verified reviews recorded against the promoted `content_version`
  plus the S1 retention/lapse policy. Summed prior review counts inherited across
  re-distillations must never be counted as new-version evidence (spec §2) — `PageState` keeps
  `prior_stability`/`prior_difficulty` separate from `review_count` for exactly this reason; a
  fresh version's `review_count` starts at its own earned total, not the sum of its ancestors'.
- **Report fields**:
  - `pages_redistilled` = count of DISTINCT `page_id` families that produced a NEW `content_version`
    this cycle (i.e. re-distillations that changed body/evidence enough to mint a new version, not
    every `remember()` call — an idempotent re-distill with identical body+evidence keeps the same
    `content_version` and must not increment this).
  - `memories_forgotten` = count of versions ARCHIVED (category flipped to `"archive"`) this cycle
    as a direct result of being superseded — evaluated at report-clock (i.e. counted once, when the
    archival write happens), not re-evaluated retroactively from a later report.
- **FEAT-390 note**: the cycle-count promotion policy (`reinforcement_counts` ≥
  `org_promotion_cycles`) is superseded ONLY in dynamics mode; `sdd/specs/
  dream-cycle-brain-consolidation.spec.md` should record this narrowing on acceptance, not before.

## G2 coordination points

- **Must join G2's atomic review transaction**: the write that updates a version's `PageState`
  (`stability`/`difficulty`/`review_count`) as a direct result of an applied review — this is the
  state a duplicate/stale review-apply must not double-count, so it needs the same idempotency
  guarantee G2 already builds for the episodic review ledger (`apply_revision`/duplicate rejection,
  per S2's `sqlite_prototype.ReviewCommand`). This spike did not implement that transaction; it only
  used a single non-transactional `upsert_pages` call per state write.
- **May be best-effort**: archiving a superseded version's `category` (this spike's
  admission/exclusion mechanism) is idempotent and order-insensitive on its own — re-running it
  twice is a no-op — so it does not need to be inside G2's transaction, only ordered to happen
  no earlier than the new version's own write commits.
- **Open question for G2**: whether a review command should carry `content_version` as part of its
  identity key (recommended — see Freeze § Forwarding/admission) or only `page_id`; the former
  is required for "a review of old content must not automatically count as verified success of
  newly synthesized content" (spec §2) to hold once G2's transaction is designed.

## Pass/Fail

- State survives `remember()`/`copy_page_to()`: **A PASS/PASS · B PASS/FAIL · C PASS/FAIL** (see
  REPORT.md Pass/Fail; only A survives the copy without any change to `copy_page_to`)
- FTS/pack unaffected: **PASS** for all three designs (packed token cost differs by ≤1 token across
  designs; state text never appears in `summary`, so `pack_results` stub lines stay clean regardless
  of where the design stores state)
- 5× re-distill → 5 distinct versions, old excluded: **PASS** for all three designs · watermark
  recovery path identified: **PASS** (see REPORT.md "Watermark Recovery") · duplicate forwarding →
  one credit: **PASS** for all three designs (`Lineage.credit_targets`)

## Sections to edit on acceptance

§2 "Durable Storage and Lineage" (brain paragraph — freeze design A, no `WikiPageRecord` schema
change), §2 Data Models (`MemoryRef.content_version`), §3 M4 eligibility + file list (M4 consumes
`content_version`/`Lineage` as designed here), §6 C6/C7 (close both: C6 resolved by "no schema
change" design A; C7 resolved by the `pages_redistilled`/`memories_forgotten` semantics above), §8
brain-state question (resolved: frontmatter, not a `metadata` column).
