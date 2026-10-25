---
id: F010
query_id: Q036
type: grep
intent: "Locate PBAC / policy enforcement classes — is there a reusable gate keyed by capability, and where tool execution is policy-checked."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FC-013
---

# F010 — PBAC gates tool execution per call; no agent-to-agent grant

## Summary

Matches cluster in `bots/guardrails/builtin/pbac.py` (`PBACToolCallGuardrail`, TOOL_CALL stage, priority 10, `on_error='fail_closed'`), `bots/guardrails/registry.py`, `bots/abstract.py`, `tools/manager.py`, `tools/executors/policy.py` (`ExecutionPolicy` routes tools to executors — not auth), `tools/tooling_policy.py`, `tools/egress.py`, `tools/dataset_manager/sources/authorizing.py`, `security/{redaction,command_sanitizer,python_sanitizer,groundedness/policy}.py`. The guardrail builds an `EvalContext` from `PermissionContext` and calls navigator-auth `PolicyEvaluator.check_access(resource_type=ResourceType.TOOL, resource_name=tool_name, action='tool:execute')`. Q045 (grep `allowed_agents|can_call|inter_agent|agent_permissions|def register_agent` over registry, bots/abstract.py, security): **zero matches** — no inter-agent grant / capability-scoped agent-to-agent permission exists; the VERIFY claim holds.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py`
  lines: 53-72
  symbol: `PBACToolCallGuardrail`
  excerpt: |
    class PBACToolCallGuardrail(Guardrail):
        name = "pbac"
        stages: ClassVar[set] = {GuardrailStage.TOOL_CALL}
        priority = 10
        on_error = "fail_closed"

- path: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py`
  lines: 233-283
  symbol: `PBACToolCallGuardrail.check`
  excerpt: |
    permission_context: PermissionContext | None = ctx.extras.get("permission_context")
    if permission_context is None:
        return GuardrailResult(action=GuardrailAction.PASS)
    result = self._evaluator.check_access(ctx=eval_ctx, resource_type=ResourceType.TOOL,
        resource_name=tool_name, action="tool:execute", env=env)

- path: `packages/ai-parrot/src/parrot/bots/guardrails/builtin/pbac.py`
  lines: 143-200
  symbol: `PBACToolCallGuardrail._policy_enforcement`
  excerpt: |
    for policy in index.get_for_resource_type(ResourceType.TOOL): if policy.covers_resource(ResourceType.TOOL, tool_name):

- path: `packages/ai-parrot/src/parrot/tools/executors/policy.py`
  lines: 147-223
  symbol: `ExecutionPolicy`
  excerpt: |
    class ExecutionPolicy(BaseModel):
        def match(self, tool: Any) -> Optional[Tuple[str, ExecutorSpec]]:
        def resolve(self, tool: Any) -> Optional[AbstractToolExecutor]:
        def apply_to_tool(self, tool: Any) -> bool:

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 443-455
  symbol: `ToolManager.set_resolver`
  excerpt: |
    def set_resolver(self, resolver: "AbstractPermissionResolver") -> None:

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 528-543
  symbol: `ToolManager.set_grant_guard`
  excerpt: |
    def set_grant_guard(self, guard: "GrantGuard") -> None:
        # tools with routing_meta["requires_grant"] = True require an active grant or HITL approval

- path: `packages/ai-parrot/src/parrot/registry/registry.py`
  lines: 379-463
  symbol: `AgentRegistry._collect_and_register_policies / register_db_bot_policies`
  excerpt: |
    def _collect_and_register_policies(  def register_db_bot_policies(

## Notes

The policy gate is keyed by *tool name* (`ResourceType.TOOL`). Mounting a remote capability as a local tool (brainstorm `catalog.mount`) would make it fall under this same gate for free, on the *caller* side; the *serving* agent's gate needs the caller's `PermissionContext` to travel with the message.
