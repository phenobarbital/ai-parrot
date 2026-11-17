---
id: F009
query_id: Q009
type: grep
intent: "Inventory which branch modules have zero sidemantic references and are reusable as-is"
executed_at: 2026-10-25T10:45:00Z
duration_ms: 6000
parent_id: null
depth: 0
---

# F009 — 2,264 of 3,630 satellite source lines have zero sidemantic references; +494 need a one-line edit

## Summary

Per-file `grep -c -i sidemantic` over `packages/ai-parrot-semantic/src/parrot/semantic/**/*.py` on the branch: zero references in `audit.py` (185), `cache.py` (48), `catalog.py` (158), `context.py` (22), `errors.py` (41), `execution.py` (97), `governance/guard.py` (179), `governance/lineage.py` (239), `governance/masking.py` (97), `governance/pbac.py` (79), `governance/pipeline.py` (126), `governance/rls.py` (161), `ossie.py` (53), `results.py` (89), `toolkit.py` (681), `version.py` (8) — 2,264 lines. One-line references only: `models.py` (202, the `engine` Literal), `policy.py` (292, the Literal default), `__init__.py` (27, docstring) — 521 lines. Coupled: `loader.py` (386, 7 refs), `engines/native.py` (236, 2 refs but six `layer.graph` call sites), `engines/__init__.py` (54, 3), `engines/sidemantic_engine.py` (169, 9). Outside the satellite the branch adds `handlers/semantic.py` (202 lines, 0 refs), `docs/tools/semantic-layer.md` (156 lines, 4 refs) and the `duckdb.py` source fix.

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 1-681
  symbol: `SemanticLayerToolkit` (branch, 0 sidemantic refs)
  excerpt: |
    681 lines; sl_* tools; no sidemantic import

- path: `packages/ai-parrot-semantic/src/parrot/semantic/governance/pipeline.py`
  lines: 1-126
  symbol: `GovernancePipeline` (branch, 0 refs)
  excerpt: |
    governance/{guard 179, lineage 239, masking 97, pbac 79, pipeline 126, rls 161} — all 0 refs

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 1-185
  symbol: `SemanticAuditEntry`, `SemanticAuditLedger` (branch, 0 refs)
  excerpt: |
    185 lines; signer reuse; 0 refs

- path: `packages/ai-parrot-semantic/src/parrot/semantic/ossie.py`
  lines: 1-53
  symbol: `is_ossie_document`, `validate_ossie_document` (branch, 0 refs)
  excerpt: |
    53 lines; JSON-Schema validation of Ossie 0.1.1 (schemas/ossie-0.1.1.schema.json)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/execution.py`
  lines: 1-97
  symbol: execution bridge (branch, 0 refs)
  excerpt: |
    97 lines; DatabaseQueryToolkit.get_source(driver).query(...)

- path: `packages/ai-parrot-server/src/parrot/handlers/semantic.py`
  lines: 1-202
  symbol: `SemanticLayerHandler` (branch, 0 refs)
  excerpt: |
    202 lines; BaseView; registered in manager.py

## Notes

Salvage mechanics: `git checkout origin/feat-FEAT-704-semantic-layer -- <zero-ref paths>` into the rev2 worktree, then re-verify imports against a new typed `LoadedModel`. The `uv.lock`, `authorizing.py`, `handlers/datasets.py` changes must NOT be salvaged (superseded by FEAT-738, F014).
