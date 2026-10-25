---
id: FW-012
query_id: Q011
type: read
intent: "Overlap: read the semantic-layer spec sections on result handles, audit ledger and PBAC gate (planned, not shipped?)."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-012 — FEAT-704 semantic layer (0/26 tasks started) already specifies owner-bound ResultHandles, a signed SemanticAuditLedger, a PBAC GovernancePipeline and a guarded hand-off sink — strong design overlap, nothing shipped

## Summary

`sdd/tasks/index/semantic-layer.json` (FEAT-704, base dev, completed_at null): all 26 tasks are `pending`, including TASK-4469 (PBAC gate + lineage), TASK-4474 (signed audit ledger + Postgres sink) and TASK-4476 (owner-bound result handle store). The spec (1343 lines, rev 0.4) defines in M9 a `ResultHandle` (result_id, agent/user/tenant/session, subject_digest, model/policy digests, expires_at, members, physical lineage, columns, rows, audit_id, governed_sql) with `ResultHandleStore.put/claim()` where claim re-verifies owner/session/digests ("metadata alone is never authorization", same error code for every mismatch), in M8 a `SemanticAuditEntry` carrying pbac/outcome/row_count/duration_ms/signature, and in M9H a `GovernedDatasetSink` whose `publish(name, handle, authorize_read)` re-authorizes every downstream read. These are in-process, satellite-local (`ai-parrot-semantic`), hold rows inline, and are not content-addressed — but the ownership/claim/provenance semantics are the same ones the brainstorm's handle ACL ("a key is not a bearer") needs. The protocol should either consume these as its first "capability provider" or define the shared handle contract both use.

## Citations

- path: `sdd/tasks/index/semantic-layer.json`
  excerpt: |
    {"feature":"semantic-layer","feature_id":"FEAT-704","type":"feature","base_branch":"dev","completed_at":null}
    TASK-4469 pending | Fail-closed PBAC and full column lineage (M6a)
    TASK-4474 pending | Signed audit ledger and optional Postgres sink (M8)
    TASK-4476 pending | Scoped result handles and exact retained provenance (M9b)
    (26 tasks, all pending)
- path: `sdd/specs/semantic-layer.spec.md`
  lines: 634-671
  symbol: `ResultHandleStore`
  excerpt: |
    class ResultHandle(BaseModel): result_id, agent_id, user_id, tenant_id, session_id, subject_digest, model, model_digest,
        policy_digest, expires_at, members, physical_columns, physical_tables, columns, rows, audit_id, governed_sql
    class ResultHandleStore: __init__(*, ttl_s=900, max_entries=256); put(handle) -> str (secrets.token_urlsafe);
        claim(result_id, *, identity, subject_digest, model_digest, policy_digest) -> ResultHandle  # all must match, else SemanticResultError
- path: `sdd/specs/semantic-layer.spec.md`
  lines: 605-633
  symbol: `SemanticAuditLedger`
  excerpt: |
    class SemanticAuditEntry(BaseModel): ... pbac: Literal["allow","deny","unavailable","not_governed"];
        outcome: Literal["ok","denied","validation_error","execution_error"]; row_count; duration_ms; signature
    class SemanticAuditLedger: append(entry, *, required=False); verify(entry); durable property
- path: `sdd/specs/semantic-layer.spec.md`
  lines: 679-687
  symbol: `GovernedDatasetSink`
  excerpt: |
    dataset_manager_factory(identity) -> Awaitable[GovernedDatasetSink]; async publish(name, handle, authorize_read) -> dict
    "This is a trusted host integration, never an LLM parameter."
- path: `sdd/specs/semantic-layer.spec.md`
  lines: 541-590
  symbol: `GovernancePipeline`
  excerpt: |
    ### Module 6: Governance pipeline (PBAC gate, lineage, RLS push-down, masking, positive guard)
    class GovernancePipeline: govern(compiled, ctx, model)
- path: `sdd/tasks/active/TASK-4476-semantic-result-handles.md`
  wiki_page_id: file:sdd/tasks/active/TASK-4476-semantic-result-handles.md (score 0.28)
  excerpt: |
    **Status**: pending — "Every mismatch raises the SAME code (result_unavailable) — never reveal whether a handle exists for someone else."
- path: `sdd/proposals/semantic-layer-rev2.proposal.md`
  wiki_page_id: file:sdd/proposals/semantic-layer-rev2.proposal.md (score 0.32)

## Notes

- Memory [[feat-704-paused-agpl]]: the built feat branch is salvage-only; the rev2 proposal is committed; spec rev 0.4 is the authority. Any shared handle contract must be defined in core, not in the semantic satellite, to be reachable by a RemoteToolkit.
- The semantic layer's "mcp-local static_subject" identity binding (M10c, TASK-4710) is the same problem as the protocol's caller identity on a deterministic path.
