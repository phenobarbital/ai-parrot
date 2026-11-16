---
id: F020
query_id: Q005
type: tree
intent: "Follow-up: list sdd/migrations/ — the loose, hand-applied SQL folder surfaced by Q005."
executed_at: 2026-11-12T20:41:43Z
duration_ms: 300
parent_id: null
depth: 1
merged_from: [FW-005]
---

# F020 — sdd/migrations/ holds 15 loose, unordered, hand-applied SQL files mixing ai_bots DDL, data fixes and domain data

## Summary

`sdd/migrations/` has 15 files with four naming styles (`FEAT-NNN-*`, `FEAT-<slug>`, `NAV-NNNN-*`, bare slug) and no
numeric order, no ledger and no runner — the parrot equivalent of navauth's "DDL that no runner applies"
(`navigator-auth::file:sdd/state/FEAT-110/findings/F008-ddl-outside-runners.md`, score 1.00 on Q006). Contents mix
(a) **ai_bots schema DDL**: FEAT-593-ai-bots-tooling-columns, FEAT-638-bot-language-nullable,
FEAT-752-ai-bots-suggestion-columns, FEAT-add-prompt-config-ai-bots, ai-bots-homologate-botmodel,
FEAT-fold-legacy-llm-columns, FEAT-fold-embedding-model-into-vector-store-config, plus the destructive
botmodel-recreate-table; (b) **data fixes**: FEAT-fix-stale-bot-tool-names; (c) **non-parrot domain data**:
FEAT-096-planogram15-config (v1/v2/v3), NAV-7762-ecotank-endcap-rows; (d) **ontology**: FEAT-159-ontology-curation
+ a `-rollback` file. Files carry a free-text `Status : pending` header instead of recorded state.

## Citations

- path: `sdd/migrations/`
  lines: n/a (directory listing)
  symbol: `sdd/migrations`
  excerpt: |
    FEAT-096-planogram15-config{,-v2,-v3}.sql   FEAT-159-ontology-curation{,-rollback}.sql
    FEAT-593-ai-bots-tooling-columns.sql         FEAT-638-bot-language-nullable.sql
    FEAT-752-ai-bots-suggestion-columns.sql      FEAT-add-prompt-config-ai-bots.sql
    FEAT-fix-stale-bot-tool-names.sql            FEAT-fold-embedding-model-into-vector-store-config.sql
    FEAT-fold-legacy-llm-columns.sql             NAV-7762-ecotank-endcap-rows.sql
    ai-bots-homologate-botmodel.sql              botmodel-recreate-table.sql

- path: `sdd/migrations/ai-bots-homologate-botmodel.sql`
  lines: 20-31
  symbol: `fold migrations note`
  excerpt: |
    -- Additive only: it never drops anything. The columns the model no longer declares are removed by their own fold migrations:
    --   model_name/temperature/max_tokens/top_k/top_p -> FEAT-fold-legacy-llm-columns.sql
    --   embedding_model -> FEAT-fold-embedding-model-into-vector-store-config.sql
    -- Status : pending

## Notes

`sdd/` is not shipped in any wheel, so an installed `parrot` cannot find these files — the navauth decision was
"SQL lives in-package" (F019 §8). Order dependencies exist (homologate is additive; the fold files drop columns
afterwards) but are only expressed in comments. The planogram/ecotank/ontology files are not ai_bots and may not
belong in a parrot-owned catalog at all.
