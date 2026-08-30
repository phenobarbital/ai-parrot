# TASK-2605: PBAC filtering, re-verification and audit

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2604
**Assigned-to**: unassigned

---

## Context

Implements the authorization half of spec §3 **Module 3** — goal **G6**.

Spec OQ6 makes this **load-bearing, not defense-in-depth**: navigator-auth's upstream
access gate is keyed `(user_id, client_uid)` and Claude registers a single client, so it
*cannot* express a per-agent grant. **ai-parrot's PBAC layer is the only place per-agent
and per-tool authorization can happen.**

---

## Scope

- Filter `tools/list` per principal: ask the PBAC resolver for each candidate tool against
  `mcp:agent:{name}:tool:{tool}` and return only permitted entries.
- Re-verify on `tools/call` against the **same** canonical resource. **The list is never
  trusted as an authorization record.**
- Deny-by-default, consistent with `setup_pbac()`'s `PolicyEffect.DENY`.
- A denied `tools/call` returns a clean MCP error — never a stack trace — and is audited as
  a denial.
- Append every `tools/call` to the canonical `AuditLedger`: principal, agent, tool,
  argument hash, decision, duration.
- Unit tests.

**NOT in scope**: size policy / deadline (TASK-2606), principal resolution (TASK-2604,
consume it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/principal_guard.py` | MODIFY | Add filter + re-verify + audit |
| `packages/ai-parrot-server/tests/mcp/test_pbac_guard.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED against `dev` on 2026-08-31.

### Verified Imports
```python
from parrot.auth.pbac import setup_pbac
from parrot.auth.resolver import PBACPermissionResolver
from parrot.auth.permission import PermissionContext
from parrot.security.audit_ledger import AuditLedger      # CANONICAL — NOT parrot.auth.audit
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/pbac.py
def setup_pbac(app, policy_dir="policies", cache_ttl=30,
               default_effect=None) -> tuple[PDP|None, PolicyEvaluator|None, Guardian|None]   # :67
# deny-by-default (PolicyEffect.DENY); fail-closed when PARROT_SAAS_MODE=true

# packages/ai-parrot/src/parrot/auth/resolver.py
class PBACPermissionResolver(AbstractPermissionResolver):   # :247
    def __init__(self, ...)                                 # :275

# packages/ai-parrot/src/parrot/security/audit_ledger.py   — CANONICAL (OQ3)
class AuditLedgerEntry(BaseModel):     # :80
class AuditLedger:                     # :296
    async def append(self, ...)        # :338

# packages/ai-parrot/src/parrot/mcp/server_base.py
async def handle_tools_list(self, params) -> dict[str, Any]   # :100  takes NO principal today
async def handle_tools_call(self, params) -> dict[str, Any]   # :111
```

### Does NOT Exist
- ~~PBAC enforcement inside any MCP transport~~ — no MCP module imports `parrot.auth.pbac`
  or `PBACPermissionResolver` today. You are adding the first.
- ~~`parrot.auth.audit.AuditLedger`~~ — that module declares itself **DEPRECATED**
  (`auth/audit.py:1`, FEAT-264/TASK-1675). Use `parrot.security.audit_ledger`.
- ~~A PBAC shadow / audit-only mode~~ — **does not exist in either repo**. navigator-auth's
  `enforcing: false` means *"non-short-circuiting ordinary policy"*, NOT dry-run. Do not
  plan a safe observation period on it.
- ~~A per-agent grant in navigator-auth~~ — the access gate is per `(user_id, client_uid)`.
- ~~`MCPServerConfig.allowed_tools` as a policy hook~~ — it is a static, process-wide name
  filter applied in `RemoteMCPServerBase.register_tool` (`base.py:65`). Not per-principal.

---

## Implementation Notes

### Pattern to Follow
```python
CANONICAL = "mcp:agent:{agent}:tool:{tool}"

async def filtered_tools_list(self, params, pctx):
    out = []
    for name, adapter in self.tools.items():
        if await self._permitted(pctx, agent, name):
            out.append(adapter.to_mcp_tool_definition())
    return {"tools": out}

async def guarded_tools_call(self, params, pctx):
    name = params["name"]
    if not await self._permitted(pctx, agent, name):     # RE-VERIFY, never trust the list
        await self._audit(pctx, agent, name, decision="deny")
        return mcp_error("not permitted")                # clean error, no stack trace
    ...
```

### Key Constraints
- The re-verification is not redundant — `tools/list` and `tools/call` are separate
  requests and policy may have changed between them.
- Both the per-agent and aggregate name forms must resolve to the same canonical resource
  (consume TASK-2602's helper).
- Audit **every** call, permitted or denied. Hash arguments; never log raw argument values.
- Deny-by-default: an unknown tool or an unresolvable resource denies.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/pbac.py:67` — deny-by-default setup
- `packages/ai-parrot/src/parrot/security/audit_ledger.py:338` — `append()` signature

---

## Acceptance Criteria

- [ ] `tools/list` omits tools the principal may not call
- [ ] `tools/call` re-evaluates policy and denies independently of the list
- [ ] A denial returns a clean MCP error with no stack trace, and is audited
- [ ] Deny-by-default holds for unknown tools and unresolvable resources
- [ ] Every `tools/call` appends principal, agent, tool, argument hash, decision, duration
- [ ] `parrot.auth.audit` is NOT imported anywhere in the change
- [ ] Aggregate and per-agent names hit the same canonical resource
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/mcp/test_pbac_guard.py -v`
- [ ] No linting errors

---

## Test Specification

```python
class TestPBACGuard:
    async def test_tools_list_filtered_by_policy(self, guard, denied_pctx):
        listed = await guard.tools_list({}, denied_pctx)
        assert "restricted_tool" not in [t["name"] for t in listed["tools"]]

    async def test_tools_call_reverifies_policy(self, guard, denied_pctx):
        resp = await guard.tools_call({"name": "restricted_tool"}, denied_pctx)
        assert resp["isError"] is True
        assert "Traceback" not in json.dumps(resp)

    async def test_denial_is_audited(self, guard, denied_pctx, ledger_spy):
        await guard.tools_call({"name": "restricted_tool"}, denied_pctx)
        assert ledger_spy.last["decision"] == "deny"

    async def test_every_call_audited_with_arg_hash(self, guard, ok_pctx, ledger_spy):
        await guard.tools_call({"name": "forecast", "arguments": {"q": "secret"}}, ok_pctx)
        entry = ledger_spy.last
        assert entry["decision"] == "allow" and "duration" in entry
        assert "secret" not in json.dumps(entry)      # hashed, never raw

    async def test_deny_by_default_unknown_tool(self, guard, ok_pctx):
        resp = await guard.tools_call({"name": "nope"}, ok_pctx)
        assert resp["isError"] is True

    async def test_aggregate_name_same_resource(self, guard, ok_pctx):
        assert guard.resource_for("finance__forecast") == "mcp:agent:finance:tool:forecast"
```

---

## Agent Instructions

1. **Read the spec** — §2 Overview #5, §3 Module 3, OQ6 in §8.
2. **Check dependencies** — TASK-2604 completed.
3. **Verify the Codebase Contract** — note the deprecated audit module.
4. **Update status** → `"in-progress"`. 5. **Implement**. 6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`. 8. **Update index** → `"done"`. 9. **Completion Note**.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
