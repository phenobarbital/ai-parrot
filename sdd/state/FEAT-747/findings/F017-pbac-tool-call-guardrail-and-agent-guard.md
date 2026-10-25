---
id: F017
query_id: Q005
type: wiki_page
intent: "Orient: PBAC / policy enforcement at tool execution — is there a reusable policy gate."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FW-006
---

# F017 — PBAC exists at two layers: PBACToolCallGuardrail (first guard in ToolManager.execute_tool) and agent_guard.enforce_agent_access (bot resolution); no capability-scoped agent-to-agent grant

## Summary

Policy enforcement below the LLM already exists and is reusable: `bots/guardrails/builtin/pbac.py::PBACToolCallGuardrail` (FEAT-406) evaluates the shared `PolicyEvaluator` (from `setup_pbac()`) at `GuardrailStage.TOOL_CALL` and 'runs FIRST in `ToolManager.execute_tool()`, before `GrantGuard`/`ConfirmationGuard`'; it returns a `PolicyDenialReport{rule, message, tool_name}` on BLOCK and has fail-open/fail-closed modes (`_engine_unavailable_result`). `auth/agent_guard.py::enforce_agent_access(evaluator, bot_name, request)` raises `AgentAccessDenied` at bot-resolution entry points (`BotManager.get_bot`, `AgentRegistry.get_instance`) and `parse_bot_permissions` reads `navigator.ai_bots.permissions` JSONB — i.e. PBAC already decides *which subject may resolve which agent*, which is the nearest existing thing to an 'inter-agent communication grant'. The evaluation context is `parrot.auth.permission.PermissionContext → to_eval_context`, enriched with `UserInfoService` attributes. ToolManager also carries `set_resolver` (permission resolver), `set_execution_policy`, `set_broker` (credential broker), `set_grant_guard`, `set_confirmation_guard` (FW-010). NOT found: a grant keyed by capability pattern (`hr.*`) for agent→agent calls, or policy annotations (data class, row cap, aggregation minimum) on a capability — confirms the brainstorm's VERIFY item, with the nuance that the enforcement *machinery* (PolicyEvaluator, guard chain) is in place.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py`
  lines: 1-50
  symbol: `PBACToolCallGuardrail / PolicyDenialReport`
  wiki_page_id: file:packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py (score=0.64)
  excerpt: |
    Evaluates the shared PolicyEvaluator (from setup_pbac()) at the GuardrailStage.TOOL_CALL pre-execution stage
    Guard-chain position: this guardrail runs FIRST in ToolManager.execute_tool(), before GrantGuard/ConfirmationGuard
    from parrot.auth.permission import PermissionContext, to_eval_context

- path: `packages/ai-parrot/src/parrot/auth/agent_guard.py`
  lines: 1-45
  symbol: `enforce_agent_access / AgentAccessDenied / parse_bot_permissions`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/agent_guard.py
  excerpt: |
    enforcing PBAC policies at the bot-resolution entry points (BotManager.get_bot and AgentRegistry.get_instance)
    parse_bot_permissions: Validate and parse the JSONB shape stored in navigator.ai_bots.permissions

- path: `docs/security/pbac-guardrails.md`
  lines: n/a
  symbol: `PBAC Guardrails — Policy-Driven Tool-Call Denial (FEAT-406)`
  wiki_page_id: file:docs/security/pbac-guardrails.md (score=0.55)

- path: `sdd/specs/pbac-guardrails.spec.md`
  lines: n/a
  symbol: `FEAT-406 spec`
  wiki_page_id: file:sdd/specs/pbac-guardrails.spec.md (score=0.42)

- path: `sdd/specs/dataplane-authz.spec.md`
  lines: n/a
  symbol: `dataplane authz spec`
  wiki_page_id: file:sdd/specs/dataplane-authz.spec.md (score=0.44)

- path: `policies/tool-business-hours.yaml`
  lines: n/a
  symbol: `sample PBAC policy YAML`
  wiki_page_id: file:policies/tool-business-hours.yaml

## Notes

Also relevant brainstorms: `sdd/proposals/policy-rules-abstractbot.brainstorm.md` (declarative PBAC on AbstractBot), `sdd/proposals/policy-based-access-control.brainstorm.md`. `[cross-lane: type=grep, intent=ToolManager.execute_tool guard chain order + where PermissionContext (caller identity) is built per session]`.

[citation-check: verified] auth/agent_guard.py — enforce_agent_access l.172, AgentAccessDenied l.27, parse_bot_permissions l.73 (the cited 1-45 range is the module docstring)
