---
id: F007
query_id: [Q026, Q043], [Q033, Q050]
type: read
intent: "PBAC / policy gate: existing enforcement points keyed by tool or capability; where decisions are made relative to the LLM."
executed_at: 2026-10-25T22:46:15Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FC-009, FC-014
lane_origin: FC-009-pbac-policy-gate, FC-014-auth-tokens-navigator-auth
---

# F007 — PBAC is enforced at tool execution today (Layer 1 handler filter + Layer 2 PBACPermissionResolver inside AbstractTool.execute), keyed by tool name; no capability-annotation gate (data class, k-anonymity, row caps)

## Summary

`parrot/auth/resolver.py` defines `AbstractPermissionResolver.can_execute / filter_tools` with `DefaultPermissionResolver`, `AllowAllResolver`, `DenyAllResolver` and `PBACPermissionResolver`, which wraps navigator-auth's `PolicyEvaluator` and bridges `PermissionContext` → `EvalContext` → `PolicyEvaluator.check_access()`; its docstring places Layer 1 at the handler (`Guardian.filter_resources()`) and Layer 2 "inside `AbstractTool.execute()`". `AbstractTool.execute` (tools/abstract.py:916) pops `_resolver` from kwargs and calls `gates.pre_execute_refusal(self, kwargs, pctx, resolver)` before running — i.e. the deterministic refusal already sits below the LLM. Sibling guards: `DataPlanePolicyGuard` (physical resources `driver:connect`), `DatasetPolicyGuard` (DatasetManager incl. column deny), `agent_guard.py`, `eval_context.py` (FEAT-446 canonical EvalContext), `models.py` `PolicyRuleConfig`. ToolManager also has `set_execution_policy`, `set_grant_guard`, `set_confirmation_guard`, `_apply_output_guards` (FC-004). Nothing keys on capability annotations (data class, redaction rule, aggregation minimum, row cap, rate limit); redaction primitives exist in `security/redaction.py` (`ScrubPolicy`) and MCP result caps in server `mcp/result_policy.py` (FC-015).

## Citations

- path: `packages/ai-parrot/src/parrot/auth/resolver.py`
  lines: 25-65
  symbol: `AbstractPermissionResolver.can_execute`, `filter_tools`
- path: `packages/ai-parrot/src/parrot/auth/resolver.py`
  lines: 247-262
  symbol: `PBACPermissionResolver`
  excerpt: |
    class PBACPermissionResolver(AbstractPermissionResolver):
        """PBAC-backed permission resolver — Layer 2 safety net.
        Wraps navigator-auth's PolicyEvaluator and implements the
        Primary enforcement (Layer 1) happens at the handler level via
        Guardian.filter_resources().  This resolver provides defense-in-depth
        by re-checking policies inside AbstractTool.execute() (Layer 2).
- path: `packages/ai-parrot/src/parrot/auth/resolver.py`
  lines: 289-300
  symbol: `PBACPermissionResolver.can_execute`
  excerpt: |
    """Layer 2 PBAC check — evaluate tool execution permission.
    Bridges PermissionContext to EvalContext and delegates to
    PolicyEvaluator.check_access().
- path: `packages/ai-parrot/src/parrot/auth/resolver.py`
  lines: 341
  symbol: `PBACPermissionResolver.filter_tools`
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 916-954
  symbol: `AbstractTool.execute`
  excerpt: |
    async def execute(self, *args, **kwargs) -> ToolResult:
        resolver = kwargs.pop("_resolver", None)
        refused = await gates.pre_execute_refusal(self, kwargs, pctx, resolver)
- path: `packages/ai-parrot/src/parrot/tools/abstract.py`
  lines: 999
  symbol: `_ensure_open` call inside execute
- path: `packages/ai-parrot/src/parrot/auth/dataplane_guard.py`
  lines: 45
  symbol: `DataPlanePolicyGuard`
- path: `packages/ai-parrot/src/parrot/auth/dataset_guard.py`
  lines: 56-63
  symbol: `DatasetPolicyGuard`
  excerpt: |
    class DatasetPolicyGuard:
        """PBAC enforcement for DatasetManager.
- path: `packages/ai-parrot/src/parrot/auth/dataset_guard.py`
  lines: 19-28
  symbol: usage (setup_pbac)
  excerpt: |
    It is a **sibling** of PBACPermissionResolver, NOT a subclass.
    - PBACPermissionResolver → ResourceType.TOOL, action tool:execute
    pdp, evaluator, guardian = setup_pbac(app, policy_dir="policies")
- path: `packages/ai-parrot/src/parrot/auth/eval_context.py`
  lines: 1-5
  symbol: module docstring
  excerpt: |
    """Canonical PBAC EvalContext builder for AI-Parrot (FEAT-446).
- path: `packages/ai-parrot/src/parrot/auth/models.py`
  lines: 32
  symbol: `PolicyRuleConfig`
- path: `packages/ai-parrot/src/parrot/auth/pbac.py`
  lines: 1
  symbol: (setup_pbac module — not read)
- path: `packages/ai-parrot/src/parrot/security/redaction.py`
  lines: 128
  symbol: `ScrubPolicy`
- path: `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py`
  lines: 52
  symbol: `pbac_action_namespace`
  excerpt: |
    pbac_action_namespace: "integration".

## Notes

The two-layer PBAC pattern (handler filter + in-tool re-check) and `setup_pbac(app, policy_dir)` are the natural homes for a capability-keyed policy gate (D11). `tools/gates` (the `gates.pre_execute_refusal` module) was not read.


<!-- merged from FC-014 -->

# FC-014 — navigator-auth integration is session/OAuth2/PBAC based (token exchange, grants, approval tokens, OAuth2 providers); zero hits for biscuit / macaroon / attenuated capability tokens

## Summary

`parrot/auth/` contains `token_exchange.py` (`TokenExchangeClient(auth_url, timeout, prefer_id_token).exchange(...) -> ExchangeResult` with reasons `ok|user_not_found|backend_not_loaded|invalid_token|expired|transport_error` — exchanges an external provider token for a Navigator session), `grants.py`, `approval_token.py`, `confirmation.py`, `credentials.py`, `broker/{core,byok,factory}.py` (CredentialBroker), `identity.py`, `session_identity.py`, `system_account.py`, `manifest.py`, `rls_registry.py`, the OAuth2 stack `oauth2/{service,registry,models,persistence,mcp_provider,jira_provider,o365_*,workiq_provider}.py` and `oauth2_routes.py`. A case-insensitive grep for `biscuit|macaroon` over every package returned nothing, confirming the VERIFY claim: attenuated capability tokens do not exist. MCP servers authenticate via API key / bearer / OAuth internal or external (`RemoteMCPServerBase._authenticate_*`, FC-003); the mTLS-identifies-the-agent model of the brainstorm has no counterpart found.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/token_exchange.py`
  lines: 1-21
  symbol: module docstring + reason constants
  excerpt: |
    """Exchange an external provider token for a Navigator session."""
    REASON_OK = "ok"
    REASON_USER_NOT_FOUND = "user_not_found"
    REASON_INVALID_TOKEN = "invalid_token"
    REASON_EXPIRED = "expired"
- path: `packages/ai-parrot/src/parrot/auth/token_exchange.py`
  lines: 25-63
  symbol: `ExchangeResult`, `TokenExchangeClient`, `exchange`
  excerpt: |
    class TokenExchangeClient:
        def __init__(self, auth_url: str, timeout: int = 15, prefer_id_token: bool = True) -> None:
        async def exchange(
- path: `packages/ai-parrot/src/parrot/auth/approval_token.py`
  lines: 1
  symbol: (approval token module — not read)
- path: `packages/ai-parrot/src/parrot/auth/grants.py`
  lines: 1
  symbol: (grants module — not read)
- path: `packages/ai-parrot/src/parrot/auth/broker/core.py`
  lines: 1
  symbol: `CredentialBroker` (imported by A2AServer as `from parrot.auth.broker import CredentialBroker`)
- path: `packages/ai-parrot/src/parrot/auth/oauth2/service.py`
  lines: 1
  symbol: (OAuth2 service — matched navigator-auth grep)
- path: `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py`
  lines: 52
  symbol: `pbac_action_namespace`
- path: `packages/ai-parrot-server/src/parrot/a2a/server.py`
  lines: 217-219
  symbol: CredentialBroker wiring
  excerpt: |
    from parrot.auth.broker import CredentialBroker as _CB
    _b = _CB(audit_ledger=audit_ledger)

## Notes

The `grants.py` + `GrantGuard` (ToolManager.set_grant_guard, FC-004) mechanism may be the closest in-repo notion of a scoped delegation; not read. [cross-lane: type=wiki_query, intent="grant guard scoped grants delegation" to characterise grants.py]

- [citation-check: stale] packages/ai-parrot/src/parrot/auth/resolver.py — `can_execute` (44/166/220/236/289) and `filter_tools` (65/341) are defined on several resolver classes; the cited 289-300 / 341 lines belong to PBACPermissionResolver as stated.
