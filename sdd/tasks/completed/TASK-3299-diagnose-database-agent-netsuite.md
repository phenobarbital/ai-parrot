# TASK-3299: Diagnose (then fix) DatabaseAgent import errors + netsuite `token_store` drift

**Feature**: FEAT-562 — CI Test-Failure Root-Cause Remediation
**Spec**: `sdd/specs/ci-test-failures-root-cause-remediation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements Module 7 — the one diagnosis-first module. Two distinct
test-core failures whose root cause was NOT established at spec time:

1. `ImportError: cannot import name 'DatabaseAgentToolkit'` / `'DatabaseAgent'`
   (5 occurrences across `tests/unit/test_database_agent.py` and
   `tests/manager/test_botmanager_wiring.py`). Both symbols genuinely exist in
   source (`toolkits/_internal.py:45`, `agent.py:105`); the `(unknown
   location)` qualifier points at the test's non-standard dynamic module loader
   (`_spec.loader.exec_module`), OR at the now-fixed tqdm import cascade (M1
   landed on `dev` after these logs) — so **the first job is to re-reproduce
   post-M1** and see whether the errors even remain.
2. `create_netsuite_mcp_server() got an unexpected keyword argument
   'token_store'` (1 occurrence, `tests/mcp/test_netsuite_mcp.py:228`). The
   test injects `token_store=store` ("A custom token_store (e.g.
   VaultTokenStore) can be injected") but the factory signature
   (`integration.py:769`) has no such parameter. Given the vault-crypto-
   hardening work (navigator-session 1.0 / VaultTokenStore) just landed on
   `dev`, this is almost certainly a real source gap — the factory was not
   updated to accept the injection the test asserts — not a stale test.

---

## Scope

- **Re-reproduce (1) against a verified environment post-M1**, ideally a
  minimal local repro (`uv sync --package ai-parrot` + `pytest
  tests/unit/test_database_agent.py`). Determine the concrete cause. Then
  EITHER fix it and make both files pass, OR — if the cause is confirmed
  out-of-scope (e.g. a CI-runner cache artifact) — record an evidenced,
  explicitly-tracked deferral (SDD ledger). No silent skip.
- **For (2)**: read `create_netsuite_mcp_server` and `test_netsuite_mcp.py`'s
  `test_custom_token_store_accepted` / `test_no_token_store_wires_supplier`.
  Determine whether the source should accept `token_store` (add the param + wire
  it into token storage) or the test is stale. The evidence strongly favours
  the source fix; implement it in `integration.py`. If diagnosis overturns
  that, fix the test instead — but justify it.

**NOT in scope**: adding the `mcp` importorskip guard to `test_netsuite_mcp.py`
(TASK-3297 owns that dependency guard — this task touches the netsuite SOURCE
in `integration.py`, not the test file's guard). The 15-package CI job
(TASK-3297). The other stale-test modules (M5/M6/M8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/integration.py` | MODIFY | Add `token_store` param to `create_netsuite_mcp_server` + wire it (if diagnosis confirms source fix) |
| `tests/unit/test_database_agent.py` | MODIFY | Only if diagnosis finds a test-side cause (e.g. dynamic-loader bug); else untouched |
| `tests/manager/test_botmanager_wiring.py` | MODIFY | Only if diagnosis finds a test-side cause; else untouched |

> The file list is provisional — this is a diagnosis task. The implementer
> updates it to match the confirmed cause before completing. If (1) is already
> resolved by M1, those two files stay untouched and that is recorded.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.toolkits import DatabaseAgentToolkit  # verified: packages/ai-parrot/src/parrot/bots/database/toolkits/__init__.py:16
from parrot.bots.database.agent import DatabaseAgent  # verified: packages/ai-parrot/src/parrot/bots/database/agent.py:105
from parrot.mcp.integration import create_netsuite_mcp_server  # verified: packages/ai-parrot/src/parrot/mcp/integration.py:769
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/integration.py:769 — CURRENT signature (no token_store):
def create_netsuite_mcp_server(
    *, account_id: str, client_id: str, user_id: str,
    name: str = "netsuite", headers: Optional[Dict[str, Any]] = None,
) -> MCPServerConfig: ...
# The test that fails: tests/mcp/test_netsuite_mcp.py
#   :218 test_custom_token_store_accepted — "A custom token_store (e.g.
#        VaultTokenStore) can be injected."
#   :228 calls create_netsuite_mcp_server(..., token_store=store)
# Look at a SIBLING factory in the same module (e.g. create_oauth_mcp_server)
# for the established token_store/token_supplier wiring pattern before adding it.
```

### Does NOT Exist
- ~~a `token_store` parameter on `create_netsuite_mcp_server`~~ — not present
  today (verified: signature above). The test assumes it; the fix adds it (if
  diagnosis confirms).
- ~~a proven satellite/optional-dependency cause for the DatabaseAgent errors~~
  — the symbols exist in core; do NOT add an `importorskip` guessing at a
  missing package. Diagnose the actual cause first.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/mcp/integration.py", "action": "MODIFY" },
    { "path": "tests/unit/test_database_agent.py", "action": "MODIFY" },
    { "path": "tests/manager/test_botmanager_wiring.py", "action": "MODIFY" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/integration.py#create_netsuite_mcp_server",
    "sym:packages/ai-parrot/src/parrot/bots/database/agent.py#DatabaseAgent",
    "sym:packages/ai-parrot/src/parrot/bots/database/toolkits/_internal.py#DatabaseAgentToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Diagnosis before fix. A minimal local repro is strongly preferred over
  reading logs — the logs predate M1.
- The netsuite fix must follow the module's existing token-store wiring pattern
  (find the sibling factory that already accepts a token store) so it integrates
  with `parrot.mcp.oauth2_config` / the token supplier, not a bolt-on.
- `test_netsuite_mcp.py` requires the `mcp` SDK, so verifying the netsuite fix
  needs it installed — that happens in TASK-3297's `test-optional-integrations`
  job. This task authors the source change; its live verification runs there.
  (Worktree agents cannot install `mcp` — `.claude/rules/worktree-management.md` §4.)

---

## Implementation Blueprint

### Steps (in order)
1. Re-run `tests/unit/test_database_agent.py` + `tests/manager/
   test_botmanager_wiring.py` against a current `test-core`-shaped env — *why*:
   M1 may already have resolved the import cascade; confirm before touching them.
2. If they still fail, minimally repro and identify the cause (dynamic loader vs
   real import) — *why*: the `(unknown location)` hint points at the test's
   `exec_module`, not a missing package.
3. Read `create_netsuite_mcp_server` + its sibling token-store-accepting factory
   + the failing netsuite test — *why*: decide source-fix vs stale-test on
   evidence, then implement the confirmed direction.

### `packages/ai-parrot/src/parrot/mcp/integration.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def create_netsuite_mcp_server' packages/ai-parrot/src/parrot/mcp/integration.py)
# MODIFY the signature at line 769 to accept the injection the test asserts,
# mirroring the sibling factory's token-store wiring:
#     def create_netsuite_mcp_server(
#         *, account_id: str, client_id: str, user_id: str,
#         name: str = "netsuite", headers: Optional[Dict[str, Any]] = None,
#         token_store: Optional[<TokenStore type from the sibling factory>] = None,
#     ) -> MCPServerConfig:
# FILL IN: the exact token_store type + how it threads into the OAuth2/token
# supplier wiring — copy the sibling factory's pattern verbatim; bounded by
# test_netsuite_mcp.py::test_custom_token_store_accepted and
# ::test_no_token_store_wires_supplier (the default path must still wire a
# supplier when token_store is None). Only implement this block if step 3 confirms
# the source fix; otherwise leave integration.py untouched and fix the test.
```
**Why**: the test documents intended VaultTokenStore injection; the factory
just wasn't updated. Adding an optional `token_store` param is backward
compatible (default `None` preserves current behaviour). Do NOT invent a
storage mechanism — reuse the sibling factory's.

### FILL IN checklist
- [ ] Post-M1 repro result for the DatabaseAgent errors recorded (fixed-by-M1 / real cause) — bounded by Scope.
- [ ] `token_store` param type + wiring copied from the sibling factory (if source-fix confirmed) — bounded by the two netsuite tests.
- [ ] Files-to-Modify table updated to the confirmed cause before completion.

---

## Acceptance Criteria

- [ ] The DatabaseAgent errors are either fixed (`pytest
      tests/unit/test_database_agent.py tests/manager/test_botmanager_wiring.py
      -q` passes) OR an evidenced, ledger-tracked deferral is recorded — never
      a silent skip. A concrete root cause is written in the Completion Note.
- [ ] The netsuite `token_store` mismatch is resolved (source param added +
      wired, verified under TASK-3297's job; or the test corrected with
      justification). `test_custom_token_store_accepted` and
      `test_no_token_store_wires_supplier` both pass with `mcp` installed.
- [ ] `ruff check` clean on every file this task ends up modifying.

---

## Test Specification

Existing tests are the spec: `test_database_agent.py`,
`test_botmanager_wiring.py`, and `test_netsuite_mcp.py::TestNetsuite*`. This
task makes them pass (or defers with evidence). No new test module is required,
though a regression assertion for the `token_store` default-supplier path is
welcome if the source fix lands.

---

## Agent Instructions

Standard SDD flow. No hard dependencies. This is diagnosis-first: do NOT guess
a fix before reproducing. The netsuite source change is verified live only in
TASK-3297's job (needs `mcp`); author it here regardless.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
