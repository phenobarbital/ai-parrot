# TASK-3983: Wire the tenant tooling policy into FEAT-593 writes and the generic assign (M7 wiring, part 1)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3978, TASK-3979
**Assigned-to**: unassigned
**Wave**: 2 (spec §9) · **Module**: M7 tenant-tooling-policy (wiring: writes)

---

## Context

Spec §2 "Tenant tooling policy" enforcement table, phase **write**: `AgentToolingStore.put_toolkit`,
`put_mcp_servers` (`tooling_store.py:177`, `:204`) must call `enforce_tenant_tooling(app, resulting_tooling,
subject=ToolingSubject(..., phase="write"))` on the **complete resulting** tooling of the agent, before
`_split_secrets` / `store_vault_credential` / any persistence; the generic assign (`toolkits.py:443-459`) too.
`delete_toolkit` also re-checks the resulting tooling. Storage services wire their own calls (FEAT-621 W2).
Refusals map to HTTP 422 `tooling_not_permitted` with `details.reason` / `details.item` (X14).

---

## Scope

- `tooling_store.py`: build the resulting `NormalizedTooling` (existing specs with the candidate replacing its
  slug / the full new MCP list) and call `enforce_tenant_tooling` **before** `_split_secrets` (put_toolkit) and
  **before** the per-server vault loop (put_mcp_servers); same in `delete_toolkit` before the vault delete.
  Client-supplied `secret_refs` / `vault_owner` in a payload are refused (`secret_ref_not_permitted`) — the
  policy's write phase does it; make sure the candidate passed carries them when the client sent them.
- Subject: `ToolingSubject(tenant=<partition tenant>, agent_id=<state agent id or None>, actor=<user id>, phase="write")`
  — tenant from the handler's `_studio_partition()` (FEAT-621 X5) via the store's `handler`.
- `toolkit_config.py::_map_exc`: `TenantToolingRefused` → 422 `tooling_not_permitted` with
  `details={"reason":…, "item":…}` (check it before the generic `ValueError` branch).
- `toolkits.py` generic assign (`_assign_generic`) and the first-class branches: `policy.check_tool(slug, subject=…phase="write")`
  before construction; refusal → `_ToolkitAssignError(422, "tooling_not_permitted", …)`.
- Regression tests `test_tenant_stdio_refused_before_any_process` and `test_approved_host_config_still_works`.

**NOT in scope**: attach / execute / catalogue (TASK-3984); storage `StudioToolingService` /
`StudioDraftService` activation (FEAT-621 W2/W3 call the hook themselves); vault-name scheme (FEAT-621 M13 / TASK-3988).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | MODIFY | enforce_tenant_tooling before vault/persist in put_toolkit / put_mcp_servers / delete_toolkit |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` | MODIFY | _map_exc: TenantToolingRefused → 422 tooling_not_permitted |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` | MODIFY | assign: check_tool before construction |
| `packages/ai-parrot-server/tests/studio/test_tenant_tooling_writes.py` | CREATE | R1 regressions: stdio refused before any process; approved host config works |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.tooling_policy import (  # TASK-3977
    TenantToolingRefused, ToolingSubject, enforce_tenant_tooling, get_tenant_tooling_policy,
)
from parrot.tools.spec import NormalizedTooling  # spec.py:50
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py
class AgentToolingStore:  # :78 — self.handler (:82)
    async def put_toolkit(self, name, slug, params, user_overridable) -> ToolkitSpec:  # :177
        self._reject_server_managed(schema, params)  # :185
        spec = await self._split_secrets(...)  # :187 ← policy must run BEFORE this line
    async def delete_toolkit(self, name, slug) -> None:  # :193 — delete_vault_credential :201
    async def put_mcp_servers(self, name, servers) -> list[AgentMCPServerSpec]:  # :204
        candidate = AgentMCPServerSpec.model_validate({**payload, "params": params})  # :218 (occurrences: 1)
        await store_vault_credential(state.owner, vault_name, current)  # :242 ← policy must run BEFORE the loop that reaches this
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py
def _map_exc(self, exc)  # :48-58 — ValueError → 422 invalid_params (:52-53)
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py
def _assign_generic(self, bot, slug, params)  # :443-460; _assign_infographic :421; raise _ToolkitAssignError(status, code, msg, details=)
```

### Does NOT Exist
- ~~`StudioBaseView._studio_partition()`~~ — FEAT-621 W1 (returns GLOBAL), overridden by FEAT-605 W2.1; does not exist on `dev` @ 32b1a45d4. This task waits for it.
- ~~`ToolingState.tooling_ref` / `agent_id` on `ToolingState`~~ — FEAT-621 M13/W3; read `agent_id` only through what storage provides, else `None`.
- ~~a policy check in `_split_secrets`~~ — the hook runs once, on the resulting tooling, before it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_tenant_tooling_writes.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore.put_toolkit",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore.put_mcp_servers",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore.delete_toolkit",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py#_ToolingViewMixin._map_exc",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py#StudioToolkitsHandler._assign_generic"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- One helper `AgentToolingStore._enforce(state, tooling, *, name)` builds the subject and calls the hook —
  keeps the three write methods within R4.
- `test_tenant_stdio_refused_before_any_process`: tenant partition; `PUT …/mcp-servers` with stdio, and with
  `transport`/`command` inside `params` → 422 `tooling_not_permitted`, nothing persisted or vaulted (vault spy);
  a bundle carrying the same entry is refused at save and activation (FEAT-621 draft service, through its call
  to the hook); a row planted in storage is skipped at build (`bind_tooling_policy` path);
  `asyncio.create_subprocess_exec` patched to fail — call count 0 on every path (`no_subprocess` fixture).
- `test_approved_host_config_still_works`: named `HostMCPServer` + allow-listed https endpoint (served by a
  local test MCP server) + a host toolkit; write, activation and build succeed and tools register.

### Cross-feature ordering
- `tooling_store.py`, `toolkits.py`, `toolkit_config.py`: merge **after FEAT-621 W3** for each of those files
  (and after FEAT-621 M13 on the identity file `tooling_store.py`) and rebase (X16 per-file rule).
- The tenant subject needs FEAT-621 W1 `_studio_partition()` and FEAT-605 W2.1 (tenant partitions); the
  activation/bundle legs of the regression test need FEAT-621 W2 `StudioDraftService` wired to the hook.

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
1. Add `_enforce` and call it before any vault write in the three methods — *why*: refuse before persistence (R1).
2. Map `TenantToolingRefused` in `_map_exc` — *why*: X14 code and status.
3. Guard the assign branches with `check_tool` — *why*: enforcement table row "write: generic assign".
4. Regression tests with vault spies and the `no_subprocess` fixture; mutation: remove `_enforce` ⇒ RED.

### `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'spec = await self._split_secrets(state, slug, name, schema, params, user_overridable)' tooling_store.py)
# BEFORE — insert above that line (verified: tooling_store.py:187)
        self._enforce(state, self._with_toolkit_candidate(state, slug, params, user_overridable), name=name)
# FILL IN: _with_toolkit_candidate (resulting NormalizedTooling, candidate replaces same slug) and the
#   put_mcp_servers equivalent: validate ALL candidates first, then _enforce on the full new list, then vault
    def _enforce(self, state: ToolingState, tooling: NormalizedTooling, *, name: str) -> None:
        """Apply the host tenant tooling policy to the complete resulting tooling (FEAT-622 M7)."""
        app = self.handler.request.app
        subject = ToolingSubject(
            tenant=None,  # FILL IN: partition tenant from the handler (FEAT-621 X5 `_studio_partition`)
            agent_id=None,  # FILL IN: storage agent id when the row exists
            actor=None,  # FILL IN: authenticated user id
            phase="write",
        )
        enforce_tenant_tooling(app, tooling, subject=subject)
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` (MODIFY)
```python
# AFTER — insert at the top of `_map_exc` body (verified: toolkit_config.py:48-50)
        if isinstance(exc, TenantToolingRefused):
            return self._error(
                str(exc), status=422, code=exc.code, details={"reason": exc.reason, "item": exc.item}
            )
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` (MODIFY)
```python
# FILL IN: in the POST dispatcher before branching to _assign_wiki/_assign_infographic/_assign_generic:
#   get_tenant_tooling_policy(app).check_tool(slug, subject=...) when the subject applies; on TenantToolingRefused
#   raise _ToolkitAssignError(422, "tooling_not_permitted", str(exc), details={"reason": exc.reason, "item": exc.item})
```

### FILL IN checklist
- [ ] `tooling_store.py::_enforce` subject fields — bounded by X5/X17 (partition tenant, never the URL name).
- [ ] `put_mcp_servers` — validate-all → enforce → vault order; bounded by "nothing persisted or vaulted".
- [ ] `toolkits.py` — assign guard placement; bounded by the enforcement table.

---

## Acceptance Criteria

- [ ] Tenant partition: stdio / `params` smuggling / `command` → 422 `tooling_not_permitted`; vault and persistence spies record 0 calls.
- [ ] `create_subprocess_exec` call count 0 on write, activation and build paths.
- [ ] Named host server + allow-listed endpoint + host toolkit: write, activation and build succeed.
- [ ] GLOBAL partition without `apply_to_global` behaves exactly as before (existing FEAT-593 tests pass).

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_tenant_tooling_writes.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tooling_store.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_config.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkits.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_tenant_tooling_writes.py
async def test_tenant_stdio_refused_before_any_process(host_plugins, no_subprocess): ...   # R1 regression
async def test_approved_host_config_still_works(host_plugins, no_subprocess): ...           # R1 regression
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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**Mutation evidence**: <for each new assertion: the code reverted, the test that went RED>

**Deviations from spec**: none | describe if any
