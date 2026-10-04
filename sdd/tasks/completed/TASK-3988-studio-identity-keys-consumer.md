# TASK-3988: Studio identity keys, consumer side — tooling_ref on TOOLKITS-added paths, namespace check, two-tenant regression (M9)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3977, TASK-3987
**Assigned-to**: unassigned
**Wave**: 3 (spec §9) · **Module**: M9 studio-identity-keys (consumer)

---

## Context

Spec P7 / review R3 / G8: overrides, vault names and revision markers are keyed by the bare agent **name**, so
same-named agents in two tenants collide. The scheme (`studio-agent:<agent_id>` tooling ref; `toolkit_vault_name`,
`mcp_vault_name`, `toolkit_override_vault_name`; override document key `{user_id, agent_id: <ref>, slug}`) is
**owned by FEAT-621** (M10 helpers in its W0, M13 plumbing in its W1, X17). This task is the consumer side: every
key computation **added by this feature** (M2 shim path in `toolkit_overrides._spec`, M4 `/me` refusal, M7 on
`tooling_store.py`) uses `state.tooling_ref` / `agent_tooling_ref`; the policy's build-time namespace check uses
the storage helpers; and it owns `test_same_names_two_tenants_independent_secrets_and_overrides`.

---

## Scope

- Audit every TOOLKITS-added line in `tooling_store.py` and `toolkit_overrides.py` (from TASK-3979/09/13): any key,
  vault name or session marker it computes takes the ref from the partitioned lookup (`ToolingState.tooling_ref`),
  never from the URL name. Fix the ones that do not.
- `tooling_policy.py`: re-verify the build-time check of TASK-3977 against FEAT-621 M10's final helpers
  (`toolkit_vault_name(slug, ref)`, `mcp_vault_name(server, ref)`); switch import/signature if M10 changed them.
- Regression `test_same_names_two_tenants_independent_secrets_and_overrides` (spec §4 integration, R3): one user;
  tenants `acme`, `beta`; agent `sales` in each with toolkit `tp_probe` (secret param) and a same-named MCP server;
  CRUD of agent secrets and the `/me` override in `acme` leaves `beta` untouched and vice versa; runtime hydration
  (`_apply_user_toolkit_overrides`) sees only its own tenant's override; names are exactly the storage scheme;
  delete + recreate `acme/sales` → no secrets, no override. Mutation: key by name ⇒ RED.

**NOT in scope**: edits to `handlers/toolkit_persistence.py`, `handlers/agent.py`, `tools/spec.py` (FEAT-621
M10/M13 own them); the purge on delete (FEAT-621); any new key scheme.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/tooling_policy.py` | MODIFY | build-time vault-name check aligned to FEAT-621 M10 helpers |
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | MODIFY | TOOLKITS-added key computations use state.tooling_ref |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` | MODIFY | TOOLKITS-added key computations use state.tooling_ref |
| `packages/ai-parrot-server/tests/studio/test_two_tenant_identity.py` | CREATE | R3 two-tenant same-name regression |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.spec import mcp_vault_name, toolkit_vault_name  # spec.py:59,64 today; FEAT-621 M10 owns final form
# FEAT-621 (not on dev @ 32b1a45d4 — verify before use):
#   agent_tooling_ref(bot), toolkit_override_vault_name(slug, ref), ToolingState.tooling_ref, ToolkitConfigService.purge_agent
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py (today; FEAT-621 M13 rewrites)
await ToolkitConfigService().load(user.user_id, name)  # :109, :157
vault_name = f"toolkit_{slug}_{name}_user"  # :170, :200
UserToolkitOverride(user_id=user.user_id, agent_id=name, slug=slug, params=clean, secret_refs=refs)  # :183 (occurrences: 1)
session.pop(f"{name}_toolkit_overrides_rev", None)  # :186, :204
# packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py (today)
toolkit_vault_name(slug, name)  # :201, :263; mcp_vault_name(candidate.name, name) :221
# packages/ai-parrot-server/src/parrot/handlers/agent.py:1099 overrides = await svc.load(str(user_id), agent.name)  (FEAT-621 M13 — no edit here)
```

### Does NOT Exist
- ~~`agent_tooling_ref`, `toolkit_override_vault_name`, `ToolingState.tooling_ref`, `ToolkitConfigService.purge_agent`~~ — introduced by FEAT-621 M10/M13; absent on `dev` @ 32b1a45d4.
- ~~a `studio/<agent_id>/…` vault-name form~~ — never existed (spec v0.2 placeholder).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/tooling_policy.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_two_tenant_identity.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#toolkit_vault_name",
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#mcp_vault_name",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py#StudioUserToolkitOverrideHandler.put"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Read the ref only from `AgentToolingStore.load(...)` → `ToolingState.tooling_ref` (FEAT-621 X5/X6). Legacy
  (non-Studio) agents keep bare-name keys (`agent_tooling_ref(bot) == bot.name`).
- Test secret **values** need the DocumentDB vault or FEAT-621 M12; skip with that reason otherwise (spec §4).

### Cross-feature ordering
- **M9 follows FEAT-621 M13 (its W1) on `tooling_store.py` / `toolkit_overrides.py` (and on
  `toolkit_persistence.py` / `agent.py`, where it makes no edit), and waits for FEAT-621 W3 on the two Studio
  handler files** (X16 identity-files rule).
- The two-tenant test needs FEAT-621 W2 (runtime `_tooling_ref`), FEAT-621 W3 (handler switch) and FEAT-605 W2.1
  (tenant partitions).

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. `git log -p` the TOOLKITS commits on the two handler files; list every key computation they added — *why*: M9 scope is exactly those.
2. Switch each to `state.tooling_ref`; re-verify the policy build check against M10 — *why*: X17.
3. Write the two-tenant regression; mutation: key by name ⇒ RED.

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` / `tooling_store.py` (MODIFY)
```python
# FILL IN: disambiguate — anchors depend on FEAT-621 M13's rewrite of these files; for each TOOLKITS-added key
#   computation found in step 1, quote 2–3 lines of context and replace the bare `name` with `state.tooling_ref`
```

### `packages/ai-parrot/src/parrot/tools/tooling_policy.py` (MODIFY)
```python
# FILL IN: in check_tooling's build branch, keep `ref = f"studio-agent:{subject.agent_id}"` and the helper calls,
#   switching to FEAT-621 M10's helper signatures/imports if they differ from parrot.tools.spec today
```

### FILL IN checklist
- [ ] Inventory of TOOLKITS-added key computations (record it in the Completion Note).
- [ ] Policy build check aligned with M10.

---

## Acceptance Criteria

- [ ] Every TOOLKITS-added key read/write on the identity files uses `state.tooling_ref`.
- [ ] `test_same_names_two_tenants_independent_secrets_and_overrides` passes incl. delete/recreate; mutation (key by name) ⇒ RED.
- [ ] `git diff` shows no change to `handlers/toolkit_persistence.py`, `handlers/agent.py`, `tools/spec.py`.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_two_tenant_identity.py -q`
- `pytest packages/ai-parrot/tests/tools/test_tooling_policy.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_two_tenant_identity.py
async def test_same_names_two_tenants_independent_secrets_and_overrides(host_plugins): ...  # R3 regression
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (tramo B1, sequential fallback)
**Date**: 2026-10-02
**Notes**: Inventory of TOOLKITS-added key computations: tooling_store (_toolkit_candidate -> split_toolkit_secrets ref=state.tooling_ref; delete_toolkit toolkit_vault_name(slug, state.tooling_ref); split_mcp_secrets ref=state.tooling_ref; _enforce computes no key), toolkit_overrides (_tooling_ref() -> state.tooling_ref for every override key, vault name and session marker; _params_refusal computes none), tooling_policy build check (f'studio-agent:{subject.agent_id}' with toolkit_vault_name/mcp_vault_name = the storage scheme). ALL already ref-keyed (FEAT-621 M13 landed on this branch): no source edit needed in tooling_policy.py / tooling_store.py / toolkit_overrides.py (honest no-op on the three source files). Added the R3 regression (real Postgres, host toolkit tp_probe with an x-secret token ctor param, same-named MCP server, in-memory vault/override stand-ins, policy bypassed as test_tooling_db_mode does since tenant secrets are refused by the write-phase policy by design); runtime hydration is asserted through AgentTalk._apply_user_toolkit_overrides. git diff touches none of toolkit_persistence.py / agent.py / spec.py. OBSERVATION (not fixed, out of scope): in AgentTalk._apply_user_toolkit_overrides the loop variable 'ref' of 'for key, ref in override.secret_refs.items()' shadows the tooling ref, so request_session[f"{ref}_tool_manager"/marker] after the loop could use a vault name when an override has secret refs (the marker key is computed before the loop, the tool_manager key after). Ledger-filed in the summary.
**Mutation evidence**: override key by name => KeyError RED; storage toolkit vault by name => RED; hydration by agent name => RED; restored.

**Deviations from spec**: none (handler modules are now packages; edit sites re-anchored)
