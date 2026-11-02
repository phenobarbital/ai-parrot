---
id: FW-011
query_id: Q005
type: wiki_related
intent: "Confirm or refute the source's claim that no usage.* event kind or token/cost plane exists in the ledger."
executed_at: 2026-10-30T22:41:09Z
duration_ms: 0
parent_id: FW-008
depth: 2
---

# FW-011 — CONFIRMED: no `usage.*` event kind and no token/cost plane exist in the ledger; its per-execution planes are feedback / reviews / suspensions only

## Summary

This is the one "Does NOT exist" claim in the source that the wiki lane **confirms**. Repeated wiki
queries over the ledger (event kinds, planes, index schema, CLI groups) surface only work-item and
insight kinds (`issue.unclaimed`, task/spec events) and three per-execution planes —
`coder_feedback.py`, `coder_reviews.py`, `coder_suspensions.py`. No result at any score mentions a
usage, token, cost or pricing plane inside `knowledge/wiki/ledger/`. The `wikitoolkit ledger`
subcommand inventory surfaced by the CLI queries (`list`, `show`, `plan-fix`, `unclaim`, `close`,
`retract-feedback`, `context`, `open`, `claim`, `ready`) contains no usage subcommand, and the
registered MCP tools in this session (`ledger_claim`, `ledger_close`, `ledger_context`,
`ledger_list`, `ledger_open`, `ledger_ready`, `ledger_show`) contain none either.

So the gap the source identifies is real — but it is a gap *in the ledger specifically*, not in the
repo. Usage rows exist in `sdd_coder/telemetry.py` (FW-002) and usage metrics + USD exist in
`parrot.observability` (FW-003). The missing thing is a single join key, not a store.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/`
  lines: 1-1
  symbol: package listing — no usage.py, no pricing.py
  excerpt: |
    coder_feedback.py coder_reviews.py coder_suspensions.py events.py
    fix_planner.py index.py integration.py log.py operations.py outbox.py
    sdd_ingest.py sdd_meta.py service.py shared_log.py store.py

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
  lines: 1-1
  symbol: `LedgerEventKind`
  excerpt: |
    # no usage.* member surfaced by any wiki query over this file;
    # the only extension precedent found is TASK-3387's `issue.unclaimed`

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py`
  lines: 1-1
  symbol: per-execution plane precedent

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py`
  lines: 1-1
  symbol: per-execution plane precedent

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_suspensions.py`
  lines: 1-1
  symbol: per-execution plane precedent

## Notes

Negative evidence from a wiki plane with 4547 stale sources is weaker than a grep. This finding is
a LEAD, not proof — the codebase lane must confirm by reading `ledger/events.py` directly.

[cross-lane: type=grep, intent=grep -n "usage" packages/ai-parrot/src/parrot/knowledge/wiki/ledger/ to prove absence at file level]
