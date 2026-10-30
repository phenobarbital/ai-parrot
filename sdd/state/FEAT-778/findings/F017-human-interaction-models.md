---
id: F017
query_id: Q037
type: read
intent: "Human-in-the-loop gate primitives (parrot/human): models and node for approve/request-changes gates."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 500
parent_id: null
depth: 0
merged_from: [FC-018-human-interaction-models]
---

# F017 — `parrot/human/models.py`: `HumanInteraction` (question/options/form_schema/timeout/consensus), `EscalationPolicy` tiers with business hours, `Severity`, `TimeoutAction`

## Summary

551 lines. Generic HITL request model (`HumanInteraction`: interaction_type FREE_TEXT|..., `options: List[ChoiceOption]`, `form_schema`, `default_response`, `target_humans`, `consensus_mode`, `timeout`), plus `EscalationPolicy`/`EscalationTier` (level, channel_type, timeout, action_type, min_severity, business_hours) and enums `WaitStrategy`, `InteractionStatus`, `TimeoutAction`, `ConsensusMode`. This is the channel-facing half (Telegram/Teams/CLI) of a gate; the dev_loop `ApprovalGate` (FC-017) is the session-state half. The two are separate today.

## Citations

- path: `packages/ai-parrot/src/parrot/human/models.py`
  lines: 31-100
  symbol: `WaitStrategy / InteractionType / InteractionStatus / TimeoutAction / ConsensusMode`
  excerpt: |
    class WaitStrategy(str, Enum): ... class InteractionType(str, Enum): ...
    class TimeoutAction(str, Enum): ... class ConsensusMode(str, Enum): ...

- path: `packages/ai-parrot/src/parrot/human/models.py`
  lines: 278-330
  symbol: `EscalationTier / EscalationPolicy`
  excerpt: |
    class EscalationTier(BaseModel): level: int; name: str; channel_type; target_humans; timeout: float = 3600.0
        action_type: EscalationActionType; min_severity: Optional[Severity]; business_hours: Optional[BusinessHours]
    class EscalationPolicy(BaseModel): policy_id; name; tiers: List[EscalationTier]

- path: `packages/ai-parrot/src/parrot/human/models.py`
  lines: 380-398
  symbol: `HumanInteraction`
  excerpt: |
    class HumanInteraction(BaseModel):
        interaction_id; question: str; context; interaction_type = FREE_TEXT
        options: Optional[List[ChoiceOption]]; form_schema; default_response
        target_humans: List[str]; consensus_mode = FIRST_RESPONSE; timeout: float = 7200.0

## Notes

Also `human/node.py`, `human/tool.py`, `human/manager.py` exist (not read).
