---
id: FC-014
query_id: Q029
type: grep
intent: "Locate HITL approval primitives in parrot.human (approval request, confirm/deny, escalation tier)."
executed_at: 2026-11-07T01:24:35Z
duration_ms: 1500
parent_id: null
depth: 0
---

# FC-014 — HITL lives in core parrot/human (not the integrations package): HumanInteractionManager.request_human_input + EscalationPolicy/EscalationTier; ConfirmationGuard in parrot/auth

## Summary

Grep for approval/confirmation/escalation classes: the HITL surface is in **core** `packages/ai-parrot/src/parrot/human/` (`manager.py` 60.8K, `models.py`, `node.py`, `tool.py`, `actions/{notify,ticket}.py`, `channels/`, `backends/`), while `packages/ai-parrot-integrations/src/parrot/human/` holds only `channels/` (`teams.py`, `telegram.py`). `HumanInteractionManager` (manager.py:51) exposes `register_policy`, `register_channel`, `request_human_input` (321) and `request_human_input_async` (502). `EscalationTier` (models.py:278) has `level`, `channel_type`, `target_humans`, `timeout`, `action_type ∈ {interact, notify, ticket}`, `min_severity`, `business_hours`; `EscalationPolicy` (325) orders tiers. Separately, `parrot/auth/confirmation.py` has `ConfirmationGuard.confirm()` (417) with a windowed `ConfirmationDecision`, and `parrot/flows/dev_loop/session_state.py:297` has an `ApprovalGate` frozen model. These are the ESCALATE_HITL building blocks; none is wired into /sdd-done today (FC-010's telegram/push builtins are one-way).

## Citations

- path: `packages/ai-parrot/src/parrot/human/manager.py`
  lines: 51-51
  symbol: `HumanInteractionManager`
  excerpt: |
    class HumanInteractionManager:

- path: `packages/ai-parrot/src/parrot/human/manager.py`
  lines: 99-99
  symbol: `HumanInteractionManager.register_policy`
  excerpt: |
        def register_policy(self, policy: EscalationPolicy) -> None:

- path: `packages/ai-parrot/src/parrot/human/manager.py`
  lines: 321-321
  symbol: `HumanInteractionManager.request_human_input`
  excerpt: |
        async def request_human_input(

- path: `packages/ai-parrot/src/parrot/human/manager.py`
  lines: 502-502
  symbol: `HumanInteractionManager.request_human_input_async`
  excerpt: |
        async def request_human_input_async(

- path: `packages/ai-parrot/src/parrot/human/models.py`
  lines: 270-276
  symbol: `EscalationActionType`
  excerpt: |
    class EscalationActionType(str, Enum):
        INTERACT = "interact"  # Standard bi-directional interaction
        NOTIFY = "notify"  # One-way notification
        TICKET = "ticket"  # Open a ticket in an external system

- path: `packages/ai-parrot/src/parrot/human/models.py`
  lines: 278-293
  symbol: `EscalationTier`
  excerpt: |
    class EscalationTier(BaseModel):
        level: int = Field(ge=1, description="1-based tier ordering")
        name: str
        channel_type: Optional[str] = Field(
        target_humans: List[str] = Field(default_factory=list)
        timeout: float = Field(default=3600.0, gt=0, description="Seconds")
        action_type: EscalationActionType = EscalationActionType.INTERACT

- path: `packages/ai-parrot/src/parrot/human/models.py`
  lines: 325-329
  symbol: `EscalationPolicy`
  excerpt: |
    class EscalationPolicy(BaseModel):
        """A series of tiered levels for escalating human-in-the-loop requests."""
        policy_id: str = Field(default_factory=lambda: str(uuid4()))
        name: str
        tiers: List[EscalationTier] = Field(default_factory=list)

- path: `packages/ai-parrot/src/parrot/auth/confirmation.py`
  lines: 378-417
  symbol: `ConfirmationGuard`
  excerpt: |
    class ConfirmationGuard:
        async def confirm(

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py`
  lines: 297-297
  symbol: `ApprovalGate`
  excerpt: |
    class ApprovalGate(_Frozen):

- path: `packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py`
  lines: 1-1
  symbol: null
  excerpt: |
    (file exists: packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py; teams.py alongside)

## Notes

- Q030 (read of the top hit) is folded here: `human/models.py` lines 265-345 read; `manager.py` outline only (depth-1 follow-up).
- The brainstorm's "HITL integrations in parrot/human/ (Telegram / Teams)" is correct for channels; the manager/models are in core, so a host-side escrow CLI can import them without the integrations package.
- The `HumanInteractionManager` is an in-process async service (server context) — for a host CLI fallback, /sdd-escrow approve|reject writing a ledger event is the realistic v1.
