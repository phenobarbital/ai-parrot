---
id: FW-008
query_id: Q007
type: wiki_page
intent: "Orient: PBAC / policy enforcement at tool execution."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 2
---

# FW-008 — PBAC exists as a TOOL_CALL guardrail over navigator-auth's PolicyEvaluator (resource=TOOL, action=tool:execute); no capability-keyed gate, no attenuated tokens

## Summary

`PBACToolCallGuardrail` (FEAT-406) runs first in `ToolManager.execute_tool()`, builds an `EvalContext` from `PermissionContext` (`parrot.auth.permission`), optionally enriches it from `UserInfoService`, and calls `PolicyEvaluator.check_access(resource_type=ResourceType.TOOL, resource_name=tool_name, action="tool:execute")`; fail-closed by default with a per-policy `enforcement: fail_open` override; denials return a sanitized `PolicyDenialReport`. Policies are YAML (`policies/*.yaml`) and can be declared per bot (`BotConfig.policies`). The semantic layer spec adds `DataPlanePolicyGuard.authorize_source()/rls_predicates()` for data-plane decisions. Nothing keys policy on a *capability contract* with data-class/redaction/aggregation-minimum/row-cap annotations, and the wiki has no hit for biscuit/macaroon/capability tokens — auth is OAuth2/JWT/mTLS via navigator-auth and the A2A security module. The enforcement *location* the brainstorm wants (below any LLM, at execution) is exactly where the guardrail already sits.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py`
  symbol: `PBACToolCallGuardrail.check`
  wiki_page_id: file:packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py (score 1.00)
  excerpt: |
    name = "pbac"; stages = {GuardrailStage.TOOL_CALL}; priority = 10; on_error = "fail_closed"
    result = self._evaluator.check_access(ctx=eval_ctx, resource_type=ResourceType.TOOL,
                                          resource_name=tool_name, action="tool:execute", env=env)
- path: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py`
  symbol: `PolicyDenialReport`
  excerpt: |
    class PolicyDenialReport(BaseModel): rule, message, tool_name, retry_hint   # never raw policy YAML
- path: `packages/ai-parrot/src/parrot/auth/permission.py`
  symbol: `PermissionContext`
  excerpt: |
    class UserSession: user_id, tenant_id, roles, metadata (TASK-4476 contract: line 21)
    class PermissionContext: session; request_id; channel; trace_context; extra (line 81)
- path: `packages/ai-parrot/src/parrot/auth/resolver.py`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/resolver.py (score 0.39)
  excerpt: |
    Permission resolvers for granular tool/toolkit access control. (PBACPermissionResolver = Layer-2 safety net)
- path: `docs/security/pbac-guardrails.md`
  wiki_page_id: file:docs/security/pbac-guardrails.md (score 0.89)
- path: `sdd/specs/semantic-layer.spec.md`
  symbol: `DataPlanePolicyGuard`
  excerpt: |
    | parrot.auth.dataplane_guard.DataPlanePolicyGuard.authorize_source() / .rls_predicates() | PBAC gate (driver:connect, table:read) on every request |
- path: `packages/ai-parrot-server/src/parrot/mcp/oauth_server.py`
  wiki_page_id: file:packages/ai-parrot-server/src/parrot/mcp/oauth_server.py (score 0.77)
  excerpt: |
    OAuth server-side classes for MCP (RFC 9728 protected-resource metadata, TASK-2608)

## Notes

- Known limitation recorded in pbac.py: `_policy_enforcement` matches on resource only, not subject — relevant if per-caller rate limits are expressed as policies.
- Wiki queries for "biscuit", "macaroon", "capability token", "attenuation" returned only OAuth/JWT material → brainstorm VERIFY "attenuation is not implemented" holds.
- Ledger issue:4b1f15a44706 / 3f62e384b388 (tooling policy resolver edge cases) show the policy resolver surface is actively changing.
