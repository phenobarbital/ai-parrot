# TASK-3243: Ledger core integration and wiki regression gate

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226, TASK-3231, TASK-3232, TASK-3233, TASK-3234, TASK-3235, TASK-3236, TASK-3237, TASK-3238
**Assigned-to**: unassigned

---

## Context

Core integration gate from spec §§4-5. Verifies durable log/index/service/federation/MCP/CLI together and protects unaffected wiki behavior.

## Scope

- Add full lifecycle, SDD ingest, scoped context, federated query, and local-symbol inbound-ledger integration cases.
- Run federation/tool/MCP/CLI/project/DevLoop regression suites.
- Store deterministic evidence in `artifacts/logs/feat-566-ledger-core.log`.

**NOT in scope**: unrelated production fixes or a second ledger backend.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/knowledge/wiki/test_ledger_integration.py` | CREATE | Cross-component integration. |
| `artifacts/logs/feat-566-ledger-core.log` | CREATE | Test evidence. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`LedgerService`, `FederatedWikiStore`, and `create_wiki_mcp_server` are provided by preceding tasks/current modules.

### Existing Signatures to Use
Use public `LedgerService` operations and `FederatedWikiStore.get_page/neighbors`; do not reach into private SQLite connection setup.

### Does NOT Exist
- ~~permission to weaken existing non-overlay federation assertions~~ — prohibited.

## Acceptance Criteria

- [ ] Full lifecycle/ingestion yields consistent log/index state.
- [ ] `wiki_related` exposes inbound ledger links; non-overlay suites remain unchanged.
- [ ] Required wiki suites pass and evidence is retained.

## Test Specification

Run `pytest tests/knowledge/wiki/ -q` with repository timeout convention and save result.

