---
id: F011
query_id: Q016
type: grep
intent: Determine whether any temporal-validity / versioning support exists, and what async work primitive backs OQ6
executed_at: 2026-08-23T00:22:57Z
depth: 0
parent_id: null
---

# F011 — Temporal validity is entirely absent from the knowledge layer; the async work primitive is the autonomous orchestrator, not a "qworker"

## Summary

A grep for `valid_from|valid_to|as_of` across the whole `parrot/knowledge/` tree returns 2
matches, both an unrelated `valid_toc_items` local in the PageIndex builder. There is no
version-history model, no as-of resolution, and no time-filtered retrieval anywhere. The
source's §3.5 (`versions[]`, `article_in_force`, per-version chunks, `derived` flag) is 100%
new work and is the single largest greenfield component of the design. For OQ6, there is no
`qworker`; the in-repo async work primitive is `parrot/autonomous/` in the ai-parrot-server
satellite, whose orchestrator and ledger support enqueue, resume and re-enqueue of stalled
work, with an explicit caveat that re-enqueueing is not idempotent.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/`
  excerpt: |
    $ grep -rniE "valid_from|valid_to|as_of" --include=*.py . | wc -l
    2
    # both hits are pageindex/builder.py:1476,1480 `valid_toc_items` (unrelated)

- path: `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py`
  lines: 231, 1400-1414
  excerpt: |
    re-enqueue incomplete executions from the previous session.
    """Re-enqueue incomplete executions found in the ledger.
    Idempotency note: re-enqueueing does NOT guarantee idempotent

- path: `packages/ai-parrot-server/src/parrot/autonomous/ledger.py`
  lines: 220, 785
  excerpt: |
    ``AutonomousOrchestrator.resume()`` to re-enqueue stalled work.
    """Convert a lifecycle event to a ``LedgerEvent`` and enqueue it.

## Notes

The absence of any as-of filtering also means the source's §3.2 "chunks are per article
version so vector retrieval can filter by as_of" requires new indexing on the pgvector side,
not just a graph change.
