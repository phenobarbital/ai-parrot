# TASK-3235: Ledger MCP tools and general-purpose provenance

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3226, TASK-3232, TASK-3234
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8. MCP agents need ledger tools while `wiki_remember` gains reusable provenance to ledger or code-plane nodes.

## Scope

- Add `derived_from`/`about` to `WikiRememberInput` and persist correct local/foreign edges.
- Add `ledger_open`, `ledger_ready`, `ledger_claim`, `ledger_close`, and `ledger_context` `AbstractTool`s backed by `LedgerService`.
- Mount ledger as a read-only overlay namespace in the MCP read store; writes use `LedgerService` only.
- Render Module 2.2 busy behavior and do not add an acknowledge MCP tool.

**NOT in scope**: overlay implementation, Click commands, human acknowledgement, or SQLite policy wiring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | Provenance and ledger tools. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | Ledger mount/tool composition. |
| `tests/knowledge/wiki/test_ledger_tools.py` | CREATE | Tool/provenance/busy coverage. |
| `tests/knowledge/wiki/test_mcp_server_ledger.py` | CREATE | Read-store mount tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
`WikiRememberInput`, `WikiRememberTool`, and `create_wiki_tools` are in `tools.py:130,272,544`; `create_wiki_mcp_server(root)` is in `mcp_server.py:90`; tools inherit `AbstractTool`.

### Existing Signatures to Use
`WikiRememberTool._execute` currently accepts fact/category/title/link_page_id/rel. `create_wiki_tools` returns the six current wiki tools and must extend that composition intentionally.

### Does NOT Exist
- ~~ledger MCP tool classes~~ — this task creates them.
- ~~`ledger_acknowledge` MCP tool~~ — acknowledgement is human-only CLI.
- ~~provenance restricted to SDD~~ — provenance is general-purpose.

## Acceptance Criteria

- [ ] Five ledger tools have docstrings and typed inputs.
- [ ] Provenance stores ledger targets foreign-qualified and code targets locally.
- [ ] Ledger reads mount as overlay; ledger writes never use the federated read store.
- [ ] `pytest tests/knowledge/wiki/test_ledger_tools.py tests/knowledge/wiki/test_mcp_server_ledger.py -q` passes.

## Test Specification

Assert tool names, foreign-edge strings, log-first soft success, and no acknowledge tool.

