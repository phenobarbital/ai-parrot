# TASK-3235: Ledger MCP tools and general-purpose provenance

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: done
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

- [x] Five ledger tools have docstrings and typed inputs.
- [x] Provenance stores ledger targets foreign-qualified and code targets locally.
- [x] Ledger reads mount as overlay; ledger writes never use the federated read store.
- [x] `pytest tests/knowledge/wiki/test_ledger_tools.py tests/knowledge/wiki/test_mcp_server_ledger.py -q` passes.

## Test Specification

Assert tool names, foreign-edge strings, log-first soft success, and no acknowledge tool.

### Completion Note

Dispatched via the pool (codex-spark hit the 1800s wall-clock cap with
no output; the qwen retry completed and merged: `feat-FEAT-566-sdd-work-ledger--TASK-3235-a2`,
files exactly as declared).

Post-merge integration review found and fixed two real defects the
merged tests never caught (both against this task's own acceptance
criteria and its files only):

1. `WikiRememberInput.about` was `str | None` — the spec's own Module 8
   interface skeleton (and `IssueOpenedPayload.about`) declare it
   `list[str] | None`.
2. The "foreign-qualify ledger targets" if/else was dead code: both
   branches appended the identical unqualified edge, so a
   `derived_from`/`about` target naming a ledger kind was **never**
   actually stored as `ledger::<target>` — directly failing this
   task's own "Provenance stores ledger targets foreign-qualified"
   acceptance criterion, undetected because the merged test only
   checked that a `"derived-from"`/`"about"` relation existed, not its
   destination string.

Also found (in `mcp_server.py`, same commit) `WikiNamespaceConfig(name="ledger",
path=...)` — `name` isn't a field on that model and `path` means something
else — which raised a `pydantic.ValidationError` on **every**
`create_wiki_mcp_server()` call, breaking 6 unrelated pre-existing tests
across 4 files that never touch the ledger. Fixed to use `store=` (the
field that satisfies the "exactly one source" validator without
resolve_namespaces() ever opening it — the `NamespaceHandle` wraps the
already-open `LedgerStore` directly) and gated ledger construction on
`find_shared_root(root) is not None`, since `LedgerService.from_root`
never raises on a git-less directory and would otherwise mount a ledger
namespace (changing tool counts) for every bare test fixture.

All fixes committed as `fix(sdd-work-ledger): TASK-3235 — ...` directly
after the merge, touching only this task's own two files. Full evidence:
`pytest tests/knowledge/wiki/test_ledger_tools.py
tests/knowledge/wiki/test_mcp_server_ledger.py
tests/knowledge/wiki/test_mcp_server_structural.py
tests/knowledge/wiki/test_namespaces_e2e.py
tests/knowledge/wiki/test_structural_e2e.py
tests/knowledge/wiki/test_env_call_sites.py -q` → 20 passed, 0 failed
(was 6 failed pre-fix). `ruff check` / `black --check` clean.

Seat: qwen (nova) · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct
· Attempts: 2 (codex-spark timeout, qwen success) · Duration: 1801.1s +
234.2s · Tokens: n/a (codex-spark) + 1,998,590 in / 11,678 out (qwen).
Post-merge fidelity/regression fixes applied by sdd-worker (sonnet).

