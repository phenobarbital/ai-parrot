"""Policy Rule Configuration models for AI-Parrot PBAC.

This module provides the ``PolicyRuleConfig`` Pydantic model for declaring
access rules at the bot/agent level. Rules are converted to the policy dict
format expected by ``PolicyEvaluator.load_policies()``.

Typical usage::

    class MyBot(AbstractBot):
        policy_rules = [
            {"action": "agent:chat", "effect": "allow", "groups": ["engineering"]},
        ]

Or in BotConfig YAML::

    policies:
      - action: agent:chat
        effect: allow
        groups: [engineering, ops]
        priority: 10

Public API:
    - ``PolicyRuleConfig``: Pydantic model for a single policy rule.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class PolicyRuleConfig(BaseModel):
    """Simple policy rule format for bot-level declaration.

    Represents a single access-control rule that can be declared on an
    AbstractBot subclass or in a BotConfig YAML ``policies:`` section.

    Rules default to ``priority=10``, which is below operator YAML files
    (``priority >= 20``) so that operators can always override code-declared rules.

    Attributes:
        action: The action this rule controls, e.g. ``"agent:chat"``,
            ``"agent:configure"``, ``"agent:list"``, ``"tool:list"``.
        effect: ``"allow"`` (default) or ``"deny"``.
        groups: Subject groups this rule applies to. ``None`` means any group.
        roles: Subject roles this rule applies to. ``None`` means any role.
        priority: Evaluation priority — higher number evaluated first.
            Default is ``10`` (below operator YAML at ``>= 20``).
        description: Human-readable description of this rule.
        conditions: Reserved for future extensibility (time windows, IP
            restrictions, etc.). Passed through to the policy dict if present.

    Example::

        rule = PolicyRuleConfig(
            action="agent:chat",
            effect="allow",
            groups=["engineering"],
            priority=10,
        )
        policy_dict = rule.to_resource_policy("my_finance_bot")
    """

    action: str = Field(..., min_length=1, description="Action this rule controls")
    effect: Literal["allow", "deny"] = Field(
        default="allow",
        description="Effect when this rule matches: allow or deny",
    )
    groups: Optional[list[str]] = Field(
        default=None,
        description="Subject groups this rule applies to",
    )
    roles: Optional[list[str]] = Field(
        default=None,
        description="Subject roles this rule applies to",
    )
    priority: int = Field(
        default=10,
        description="Evaluation priority (higher = evaluated first). Default 10 < operator YAML 20+",
    )
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description of this rule",
    )
    conditions: Optional[dict[str, Any]] = Field(
        default=None,
        description="Reserved for future extensibility (time, IP, attributes, etc.)",
    )

    @field_validator("action")
    @classmethod
    def action_must_be_nonempty(cls, v: str) -> str:
        """Validate that action is non-empty string.

        Args:
            v: The action string to validate.

        Returns:
            The validated action string.

        Raises:
            ValueError: If action is empty or whitespace.
        """
        if not v.strip():
            raise ValueError("action must not be empty or whitespace")
        return v

    def to_resource_policy(self, agent_name: str) -> dict:
        """Convert this rule to a navigator-auth policy dict.

        Produces the dict format expected by ``PolicyEvaluator.load_policies()``,
        which mirrors the YAML policy schema used in ``policies/agents.yaml``.

        Args:
            agent_name: The bot/agent name to embed in the resource identifier,
                e.g. ``"finance_bot"`` → resource ``"agent:finance_bot"``.

        Returns:
            A policy dict with keys ``name``, ``effect``, ``resources``,
            ``actions``, ``subjects``, ``priority``, and optionally
            ``conditions`` and ``description``.

        Example::

            rule = PolicyRuleConfig(action="agent:chat", groups=["finance"])
            policy = rule.to_resource_policy("finance_bot")
            # {
            #     "name": "code_rule_finance_bot_agent:chat",
            #     "effect": "allow",
            #     "resources": ["agent:finance_bot"],
            #     "actions": ["agent:chat"],
            #     "subjects": {"groups": ["finance"]},
            #     "priority": 10,
            # }
        """
        # Build subjects dict — only include non-None fields
        subjects: dict[str, Any] = {}
        if self.groups is not None:
            subjects["groups"] = self.groups
        if self.roles is not None:
            subjects["roles"] = self.roles

        policy: dict[str, Any] = {
            "name": f"code_rule_{agent_name}_{self.action}",
            "effect": self.effect,
            "resources": [f"agent:{agent_name}"],
            "actions": [self.action],
            "subjects": subjects,
            "priority": self.priority,
        }

        if self.description is not None:
            policy["description"] = self.description

        if self.conditions is not None:
            policy["conditions"] = self.conditions

        return policy
