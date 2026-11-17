---
id: F037
query_id: Q004
type: wiki_query
intent: "Orient: existing human-in-the-loop approval flows (confirmation, escalation tier, Teams/Telegram channels)."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 1400
parent_id: null
depth: 1
merged_from: [FW-008]
---

# F037 — HITL approval exists as HumanManager.request_human_input(HumanInteraction[APPROVAL], channel=…) with BLOCK/SUSPEND wait strategies, fail-closed timeouts, and tiered EscalationPolicy in parrot.human.models; it is an in-process agent facility (Teams/Telegram channels), not a host CLI

## Summary

Q004 hits: `wiki/integrations/hitl-confirmation.md` (FEAT-235, module `parrot.auth.confirmation`), `documentation/hitl_tiered_escalation_example.md`, `parrot/human/tool.py:HumanTool`, `test_human_manager.py` (Tier-1 policy start). `ConfirmationGuard._ask_approval` (`parrot/auth/confirmation.py:594-706`) builds `HumanInteraction(interaction_type=InteractionType.APPROVAL, question, timeout, default_response=False  # fail-closed on timeout)` and either `await human_manager.request_human_input(interaction, channel=channel)` (BLOCK) or `request_human_input_async(...)` + `raise HumanInteractionInterrupt(interaction_id)` (SUSPEND). Escalation: `EscalationPolicy(tiers=[EscalationTier(level, target_humans, timeout, action_type=INTERACT|NOTIFY|TICKET, action_metadata)])` registered on the manager; `ask_human.execute(question, interaction_type="approval", policy_id=…)`. Channels live in `packages/ai-parrot-integrations/src/parrot/human/channels/{teams,telegram}.py`. Everything is async, inside a running agent process with a `HumanManager`; nothing is exposed as a host-side `parrot …` command, so a v1 `ESCALATE_HITL` from a host script needs either an agent process hosting the manager or the FEAT-764 `telegram.send`/`push.send` builtins plus a CLI `approve|reject` fallback (FW-006).

## Citations

- path: `packages/ai-parrot/src/parrot/auth/confirmation.py`
  lines: 594-706
  symbol: `ConfirmationGuard._ask_approval`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/auth/confirmation.py#ConfirmationGuard._ask_approval
  excerpt: |
    interaction = HumanInteraction(interaction_type=InteractionType.APPROVAL, question=briefing,
                                   timeout=self.config.approval_timeout, default_response=False)  # fail-closed on timeout
    if wait_strategy == WaitStrategy.SUSPEND:
        interaction_id = await self.human_manager.request_human_input_async(interaction, channel=channel, schedule_timeout=False)
        raise HumanInteractionInterrupt(prompt=briefing, interaction_id=interaction_id)
    result = await self.human_manager.request_human_input(interaction, channel=channel)
- path: `packages/ai-parrot/src/parrot/human/models.py`
  lines: 1-1
  symbol: `EscalationPolicy`
  wiki_page_id: file:documentation/hitl_tiered_escalation_example.md
  score: 0.72
  excerpt: |
    from parrot.human.models import EscalationPolicy, EscalationTier, EscalationActionType
    EscalationTier(level=1, target_humans=["jlara"], timeout=300, action_type=EscalationActionType.INTERACT)
    EscalationTier(level=2, ..., action_type=EscalationActionType.NOTIFY, action_metadata={"channel": "email"})
    EscalationTier(level=3, ..., action_type=EscalationActionType.TICKET, action_metadata={"platform": "jira"})
- path: `packages/ai-parrot/src/parrot/human/tool.py`
  lines: 1-1
  symbol: `HumanTool`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/human/tool.py#HumanTool
  excerpt: |
    HumanTool — Tool that pauses agent execution to request human input.
- path: `wiki/integrations/hitl-confirmation.md`
  lines: 1-30
  symbol: `HITL Tool-Call Confirmation (FEAT-235)`
  wiki_page_id: file:wiki/integrations/hitl-confirmation.md
  excerpt: |
    ToolManager.execute_tool(): 1. GrantGuard.authorize() (FEAT-211) 2. ConfirmationGuard.confirm() (FEAT-235) -> deny -> ToolResult(cancelled|timeout)
- path: `packages/ai-parrot-integrations/src/parrot/human/channels/teams.py`
  lines: 1-1
  symbol: `teams channel`
- path: `packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py`
  lines: 1-1
  symbol: `telegram channel`
- path: `packages/ai-parrot/src/parrot/human/manager.py`
  lines: 1-1
  symbol: `HumanManager.request_human_input`
  wiki_page_id: sym:packages/ai-parrot/tests/test_human_manager.py#TestRequestHumanInput.test_level1_policy_start_does_not_terminate_immediately

## Notes

`parrot/human/` is split: models/manager/tool in core (`packages/ai-parrot/src/parrot/human/`), channels in the integrations satellite. [cross-lane: type=grep, intent=codebase lane Q029/Q030 should pin `HumanManager.request_human_input` signature and whether a manager can run headless outside a bot.] [cross-lane: type=git_log, intent=git lane Q046 — the escalation-tier work (hitl-escalation-tier.spec.md) recency.]
