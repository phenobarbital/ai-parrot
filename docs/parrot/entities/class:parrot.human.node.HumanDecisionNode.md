---
type: Wiki Entity
title: HumanDecisionNode
id: class:parrot.human.node.HumanDecisionNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pseudo-agent that pauses an AgentsFlow for human input.
---

# HumanDecisionNode

Defined in [`parrot.human.node`](../summaries/mod:parrot.human.node.md).

```python
class HumanDecisionNode
```

Pseudo-agent that pauses an AgentsFlow for human input.

Implements the minimal agent interface (``name`` property and
``ask()`` coroutine) so it can be wrapped in a ``FlowNode`` and
participate in the FSM-based workflow like any other agent.

The human's response becomes the node's result, which downstream
transition predicates can evaluate to determine branching.

On **successful completion**, ``ask()`` returns
``result.consolidated_value`` — the raw human answer (bool, str,
list, dict, etc.).  On **timeout** or **cancellation** it returns
the full :class:`~parrot.human.models.InteractionResult` so
predicates can distinguish those states from a normal response by
inspecting ``result.status``.  On unexpected infrastructure errors
(e.g. Redis down) it re-raises so the FSM can apply its own failure
policy rather than silently treating the failure as a blank response.

It also satisfies ``_ensure_agent_ready`` by exposing
``is_configured = True``, so the FSM never calls ``configure()``
on it (which doesn't exist).

For **multi-human consensus**, either:
- Set ``target_humans`` and ``consensus_mode`` on the
  ``interaction_config``, or
- Pass them as constructor kwargs (used when no config is given).

Usage::

    from parrot.human import (
        HumanDecisionNode, HumanInteraction,
        ConsensusMode, InteractionType,
    )

    # Single approver
    approval_gate = HumanDecisionNode(
        name="approval_gate",
        manager=hitl_manager,
        interaction_config=HumanInteraction(
            question="Approve the research findings?",
            interaction_type=InteractionType.APPROVAL,
            target_humans=["telegram:12345"],
        ),
    )

    # Multi-human majority vote (no interaction_config)
    vote_gate = HumanDecisionNode(
        name="team_vote",
        manager=hitl_manager,
        target_humans=["telegram:111", "telegram:222", "telegram:333"],
        consensus_mode=ConsensusMode.MAJORITY,
        interaction_type=InteractionType.APPROVAL,
    )

Args:
    name: Unique name for this node within the flow.
    manager: HumanInteractionManager instance.
    interaction_config: Optional pre-configured HumanInteraction.
        If provided, each call to ask() copies it with a fresh
        interaction_id. If not provided, ask() builds an interaction
        from the runtime question.
    channel: Channel name to dispatch interactions through.
    target_humans: Default human IDs (used when no interaction_config).
    consensus_mode: How to consolidate multiple responses.
    interaction_type: Interaction type for the no-config path
        (default FREE_TEXT). Ignored when interaction_config is given.
    source_agent: Name of the parent agent (for traceability).
    source_flow: Name of the parent flow (for traceability).
    escalation_policy_id: Optional policy ID to attach to the built
        HumanInteraction.  When provided, the manager's escalation
        chain is activated for this interaction.  Constructor kwargs
        take precedence over any value in *interaction_config*.
    severity: Declared criticality level for the built interaction.
        Affects which tier the escalation chain starts at.
        Defaults to :attr:`Severity.NORMAL`.

Example::

    node = HumanDecisionNode(
        name="hr_approval",
        manager=hitl_manager,
        escalation_policy_id="hr-policy",
        severity=Severity.HIGH,
    )

## Methods

- `def name(self) -> str`
- `async def ask(self, question: str='', **kwargs: Any) -> Any` — Called by FlowNode.execute() during workflow execution.
