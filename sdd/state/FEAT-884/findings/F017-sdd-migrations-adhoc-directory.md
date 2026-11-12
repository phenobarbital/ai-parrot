---
id: F017
query_id: Q018
type: git_log
intent: "Follow-up: history of the ad-hoc sdd/migrations/ SQL directory referenced by creation.sql."
executed_at: 2026-11-12T20:39:39Z
duration_ms: 900
parent_id: null
depth: 1
merged_from: [FG-003]
---

# F017 — sdd/migrations/ is an unversioned, unordered bag of 15 hand-run SQL files (9 touch ai_bots)

## Summary

`sdd/migrations/` (repo root, outside any package — not shipped in wheels) holds 15 SQL files added 2026-04-13..2026-11-07 with inconsistent naming (`FEAT-<n>-…`, `FEAT-<word>-…`, `NAV-<n>-…`, bare slugs), no ordering, no ledger, and mixed concerns: ai_bots schema (prompt_config, embedding fold, legacy-LLM fold, stale tool names, recreate-table, FEAT-593 tooling, FEAT-638 language nullable, homologate-botmodel, FEAT-752 suggestion columns), ontology curation tables (FEAT-159 + rollback), and *data* seeds for planograms (FEAT-096 v1/v2/v3, NAV-7762). `botmodel-recreate-table.sql` was edited after creation (fd6748e669, bb209cd2ff), so a file name does not identify a fixed change. These are the natural seed set for `parrot self migration`'s first versioned ai_bots migration chain.

## Citations

- path: `sdd/migrations/`
  lines: n/a (git ls-tree origin/dev)
  symbol: null
  excerpt: |
    FEAT-096-planogram15-config{,-v2,-v3}.sql   FEAT-159-ontology-curation{,-rollback}.sql
    FEAT-593-ai-bots-tooling-columns.sql        FEAT-638-bot-language-nullable.sql
    FEAT-752-ai-bots-suggestion-columns.sql     FEAT-add-prompt-config-ai-bots.sql
    FEAT-fix-stale-bot-tool-names.sql           FEAT-fold-embedding-model-into-vector-store-config.sql
    FEAT-fold-legacy-llm-columns.sql            NAV-7762-ecotank-endcap-rows.sql
    ai-bots-homologate-botmodel.sql             botmodel-recreate-table.sql

- path: `sdd/migrations/FEAT-add-prompt-config-ai-bots.sql`
  lines: n/a (git)
  symbol: null
  excerpt: |
    a423a27937 2026-04-30 — added

- path: `sdd/migrations/FEAT-fold-embedding-model-into-vector-store-config.sql`
  lines: n/a (git)
  symbol: null
  excerpt: |
    f591fc86b2 2026-05-06 "homologates embedding model to one column"

- path: `sdd/migrations/FEAT-fold-legacy-llm-columns.sql`
  lines: n/a (git)
  symbol: null
  excerpt: |
    9c022af2b4 2026-07-14 — added with FEAT-fix-stale-bot-tool-names.sql and botmodel-recreate-table.sql

- path: `sdd/migrations/botmodel-recreate-table.sql`
  lines: n/a (git)
  symbol: null
  excerpt: |
    added 9c022af2b4 (2026-07-14); modified fd6748e669 (2026-07-17) and bb209cd2ff (2026-10-21)

- path: `sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql`
  lines: n/a (git)
  symbol: null
  excerpt: |
    6989d23243 2026-09-30 "sql migration for bots tooling"

- path: `sdd/migrations/FEAT-638-bot-language-nullable.sql`
  lines: n/a (git)
  symbol: null
  excerpt: |
    26faeb80c3 2026-10-08 (jiraspecialist-agent-multilang TASK-4125)

- path: `sdd/migrations/ai-bots-homologate-botmodel.sql`
  lines: n/a (git)
  symbol: null
  excerpt: |
    bb209cd2ff 2026-10-21 "github reviewer work" — described in creation.sql as "idempotent, covers every column"

- path: `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql`
  lines: n/a (git)
  symbol: null
  excerpt: |
    8a1e54fac2 2026-10-28 (followup-suggestion-chips TASK-4811)

- path: `sdd/migrations/FEAT-159-ontology-curation.sql`
  lines: n/a (git)
  symbol: null
  excerpt: |
    c6b1085ec7 2026-05-12 — with FEAT-159-ontology-curation-rollback.sql (only file with an explicit rollback)

## Notes

- Ordering of the ai_bots files by first commit date gives a plausible version chain: prompt_config (04-30) → embedding fold (05-06) → legacy-LLM fold + stale tool names (07-14) → FEAT-593 tooling (09-30) → FEAT-638 language (10-08) → homologate (10-21) → FEAT-752 suggestions (10-28).
- Data-seed files (planogram, NAV-7762) are a different concern than schema migrations — scope decision needed.
- [cross-lane: type=read, intent=read sdd/migrations/ai-bots-homologate-botmodel.sql to see whether it is a safe idempotent baseline for migration 001]
- [cross-lane: type=glob, intent=Q008 globs **/*.sql only under packages/ — it will miss sdd/migrations/]
